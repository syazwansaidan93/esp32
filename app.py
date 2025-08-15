import serial
import json
import time
import serial.tools.list_ports
from flask import Flask, jsonify, request
import threading
from apscheduler.schedulers.background import BackgroundScheduler
import sqlite3
from datetime import datetime, timedelta
import atexit
import os

# --- Flask App Initialization ---
app = Flask(__name__)

# --- Configuration Constants ---
BAUD_RATE = 115200
DATA_TIMEOUT = 5
DB_FILE = 'sensor_data.db'

# --- Global Variables and Locks ---
serial_lock = threading.Lock()
ser = None

# --- Serial Port Management ---

def find_serial_port():
    """
    Scans for a serial port that is likely the ESP32-C3 and returns its path.
    Looks for a port with 'USB' or 'ACM' in its name.
    """
    ports = serial.tools.list_ports.comports()
    for port in ports:
        if "USB" in port.device or "ACM" in port.device:
            print(f"Found potential serial port: {port.device}")
            return port.device
    print("No suitable serial port found.")
    return None

def connect_to_serial():
    """
    Establishes a connection to the detected serial port.
    Returns True on success, False on failure.
    """
    global ser
    serial_port = find_serial_port()
    if serial_port:
        try:
            ser = serial.Serial(serial_port, BAUD_RATE, timeout=DATA_TIMEOUT)
            time.sleep(2)  # Wait for the ESP32 to reset and become ready
            ser.flushInput()
            print(f"Serial port {serial_port} opened successfully.")
            return True
        except serial.SerialException as e:
            print(f"Error opening serial port {serial_port}: {e}")
            ser = None
            return False
    return False

# --- Data Fetching and Processing ---

def fetch_from_serial(command):
    """
    Sends a command to the ESP32 and waits for a JSON response.
    Uses a thread lock to prevent multiple threads from accessing the serial port simultaneously.
    Returns the parsed JSON data or None if an error occurs or a timeout is reached.
    """
    global ser
    if not ser or not ser.is_open:
        print("Serial port not connected. Attempting to reconnect...")
        if not connect_to_serial():
            return None

    with serial_lock:
        try:
            # Ensure the input buffer is clear before sending
            ser.flushInput()
            # Send the command with a newline character
            ser.write(command.encode('utf-8') + b'\n')
            time.sleep(0.1) # Wait briefly for the ESP32 to respond

            start_time = time.time()
            while time.time() - start_time < DATA_TIMEOUT:
                line = ser.readline().decode('utf-8').strip()
                if line:
                    # Check if the line is a valid JSON object
                    if line.startswith('{') and line.endswith('}'):
                        try:
                            data = json.loads(line)
                            return data
                        except json.JSONDecodeError:
                            print(f"Could not parse line as JSON: {line}")
                    else:
                        print(f"Ignoring non-JSON line: {line}")

            print(f"Timed out waiting for a valid JSON response to command: {command}")
            return None
        except serial.SerialException as e:
            print(f"Serial communication error: {e}. Trying to reconnect on next attempt.")
            ser = None
            return None

# --- Database Management ---

def get_db_connection():
    """Returns a connection object to the SQLite database."""
    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn

def setup_database():
    """Creates the necessary tables if they don't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS temperature_readings (
            timestamp TEXT PRIMARY KEY,
            indoor_temp_C REAL,
            outdoor_temp_C REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS solar_readings (
            timestamp TEXT PRIMARY KEY,
            voltage_V REAL,
            current_mA REAL,
            power_mW REAL
        )
    ''')
    conn.commit()
    conn.close()

# --- Scheduled Jobs (using APScheduler) ---

def store_temperature_data_job():
    """Fetches temperature data from ESP32 and stores it in the database."""
    print("Running scheduled job to store temperature data...")
    data = fetch_from_serial('t')

    if data and 'i_temp' in data and 'o_temp' in data:
        record = {
            'timestamp': datetime.now().isoformat(),
            'indoor_temp_C': data['i_temp'],
            'outdoor_temp_C': data['o_temp']
        }
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO temperature_readings (timestamp, indoor_temp_C, outdoor_temp_C)
                VALUES (?, ?, ?)
            ''', (record['timestamp'], record['indoor_temp_C'], record['outdoor_temp_C']))
            conn.commit()
            conn.close()
            print("Temperature data stored successfully.")
        except sqlite3.Error as e:
            print(f"Error storing data to SQLite: {e}")
    else:
        print("Failed to fetch temperature data for storage.")

def store_solar_data_job():
    """Fetches solar data from ESP32 and stores it in the database."""
    print("Running scheduled job to store solar data...")
    s_data = fetch_from_serial('s')

    if s_data and 'voltage_V' in s_data and 'current_mA' in s_data and 'power_mW' in s_data:
        record = {
            'timestamp': datetime.now().isoformat(),
            'voltage_V': s_data['voltage_V'],
            'current_mA': s_data['current_mA'],
            'power_mW': s_data['power_mW']
        }
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO solar_readings (timestamp, voltage_V, current_mA, power_mW)
                VALUES (?, ?, ?, ?)
            ''', (record['timestamp'], record['voltage_V'], record['current_mA'], record['power_mW']))
            conn.commit()
            conn.close()
            print("Solar data stored successfully.")
        except sqlite3.Error as e:
            print(f"Error storing solar data to SQLite: {e}")
    else:
        print("Failed to fetch solar data for storage.")

def prune_old_data_job():
    """Deletes data older than 2 days to keep the database from growing too large."""
    print("Running scheduled job to prune old data...")
    cutoff_time = datetime.now() - timedelta(days=2)
    cutoff_iso = cutoff_time.isoformat()

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM temperature_readings WHERE timestamp < ?', (cutoff_iso,))
        deleted_temp_count = cursor.rowcount
        cursor.execute('DELETE FROM solar_readings WHERE timestamp < ?', (cutoff_iso,))
        deleted_solar_count = cursor.rowcount
        conn.commit()
        conn.close()
        print(f"Successfully pruned {deleted_temp_count} old temperature records and {deleted_solar_count} old solar records.")
    except sqlite3.Error as e:
        print(f"Error pruning old data: {e}")

# --- Flask API Endpoints ---

@app.route('/r/on', methods=['POST'])
def turn_relay_on():
    data = fetch_from_serial('r1')
    if data and data.get('value') == 'ON':
        return jsonify({"status": "success", "message": "Relay turned ON"})
    return jsonify({"status": "error", "message": "Failed to turn relay ON"}), 500

@app.route('/r/off', methods=['POST'])
def turn_relay_off():
    data = fetch_from_serial('r0')
    if data and data.get('value') == 'OFF':
        return jsonify({"status": "success", "message": "Relay turned OFF"})
    return jsonify({"status": "error", "message": "Failed to turn relay OFF"}), 500

@app.route('/r/latest')
def get_r_status():
    data = fetch_from_serial('r')
    if data and 'value' in data:
        return jsonify({"relay_status": data['value']})
    return jsonify({"error": "Failed to fetch data"}), 500

@app.route('/o/latest')
def get_o_temp():
    data = fetch_from_serial('o')
    if data and 'value' in data:
        return jsonify({"outdoor": data['value']})
    return jsonify({"error": "Failed to fetch data"}), 500

@app.route('/i/latest')
def get_i_temp():
    data = fetch_from_serial('i')
    if data and 'value' in data:
        return jsonify({"indoor": data['value']})
    return jsonify({"error": "Failed to fetch data"}), 500

@app.route('/s/latest')
def get_s_pwr():
    data = fetch_from_serial('s')
    if data:
        solar_value = {
            "voltage_V": data.get("voltage_V", "N/A"),
            "current_mA": data.get("current_mA", "N/A"),
            "power_mW": data.get("power_mW", "N/A")
        }
        return jsonify(solar_value)
    return jsonify({"error": "Failed to fetch data"}), 500

@app.route('/t/latest')
def get_t_latest():
    data = fetch_from_serial('t')
    if data and 'i_temp' in data and 'o_temp' in data:
        return jsonify({
            "indoor_temp_C": data['i_temp'],
            "outdoor_temp_C": data['o_temp']
        })
    return jsonify({"error": "Failed to fetch one or more temperature readings"}), 500

@app.route('/o/24')
def get_o_24h():
    conn = get_db_connection()
    cursor = conn.cursor()
    time_24h_ago = datetime.now() - timedelta(hours=24)
    cursor.execute('SELECT timestamp, outdoor_temp_C FROM temperature_readings WHERE timestamp >= ?', (time_24h_ago.isoformat(),))
    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

@app.route('/o/48')
def get_o_48h():
    conn = get_db_connection()
    cursor = conn.cursor()
    time_48h_ago = datetime.now() - timedelta(hours=48)
    cursor.execute('SELECT timestamp, outdoor_temp_C FROM temperature_readings WHERE timestamp >= ?', (time_48h_ago.isoformat(),))
    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

@app.route('/i/24')
def get_i_24h():
    conn = get_db_connection()
    cursor = conn.cursor()
    time_24h_ago = datetime.now() - timedelta(hours=24)
    cursor.execute('SELECT timestamp, indoor_temp_C FROM temperature_readings WHERE timestamp >= ?', (time_24h_ago.isoformat(),))
    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

@app.route('/i/48')
def get_i_48h():
    conn = get_db_connection()
    cursor = conn.cursor()
    time_48h_ago = datetime.now() - timedelta(hours=48)
    cursor.execute('SELECT timestamp, indoor_temp_C FROM temperature_readings WHERE timestamp >= ?', (time_48h_ago.isoformat(),))
    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

@app.route('/t/24')
def get_t_24h():
    conn = get_db_connection()
    cursor = conn.cursor()
    time_24h_ago = datetime.now() - timedelta(hours=24)
    cursor.execute('SELECT * FROM temperature_readings WHERE timestamp >= ?', (time_24h_ago.isoformat(),))
    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

@app.route('/t/48')
def get_t_48h():
    conn = get_db_connection()
    cursor = conn.cursor()
    time_48h_ago = datetime.now() - timedelta(hours=48)
    cursor.execute('SELECT * FROM temperature_readings WHERE timestamp >= ?', (time_48h_ago.isoformat(),))
    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

@app.route('/s/24')
def get_s_24h():
    conn = get_db_connection()
    cursor = conn.cursor()
    time_24h_ago = datetime.now() - timedelta(hours=24)
    cursor.execute('SELECT * FROM solar_readings WHERE timestamp >= ?', (time_24h_ago.isoformat(),))
    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

@app.route('/s/48')
def get_s_48h():
    conn = get_db_connection()
    cursor = conn.cursor()
    time_48h_ago = datetime.now() - timedelta(hours=48)
    cursor.execute('SELECT * FROM solar_readings WHERE timestamp >= ?', (time_48h_ago.isoformat(),))
    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

@app.route('/settings')
def get_settings():
    """Fetches and returns the current relay control settings."""
    data = fetch_from_serial('get_settings')
    if data and 'relay_settings' in data:
        return jsonify(data['relay_settings'])
    return jsonify({"error": "Failed to fetch settings"}), 500

@app.route('/settings/auto', methods=['POST'])
def set_auto_mode():
    """Sets the relay control mode to automatic."""
    fetch_from_serial('auto')
    return jsonify({"status": "success", "message": "Automatic mode enabled"}), 200

@app.route('/settings/manual', methods=['POST'])
def set_manual_mode():
    """Sets the relay control mode to manual."""
    fetch_from_serial('manual')
    return jsonify({"status": "success", "message": "Manual mode enabled"}), 200

@app.route('/settings/set_on_V', methods=['POST'])
def set_on_threshold():
    """Sets the 'turn on' voltage threshold for auto mode."""
    value = request.args.get('value')
    if value is None:
        return jsonify({"status": "error", "message": "Missing 'value' parameter"}), 400
    data = fetch_from_serial(f'set_on_V {value}')
    if data and data.get('command') == 'set_on_V':
        return jsonify({"status": "success", "new_value": data.get('value')})
    return jsonify({"status": "error", "message": "Failed to set threshold"}), 500

@app.route('/settings/set_off_V', methods=['POST'])
def set_off_threshold():
    """Sets the 'turn off' voltage threshold for auto mode."""
    value = request.args.get('value')
    if value is None:
        return jsonify({"status": "error", "message": "Missing 'value' parameter"}), 400
    data = fetch_from_serial(f'set_off_V {value}')
    if data and data.get('command') == 'set_off_V':
        return jsonify({"status": "success", "new_value": data.get('value')})
    return jsonify({"status": "error", "message": "Failed to set threshold"}), 500

if __name__ == '__main__':
    setup_database()
    connect_to_serial()
    scheduler = BackgroundScheduler()
    # Log temperature data every 15 minutes
    scheduler.add_job(store_temperature_data_job, 'interval', minutes=15)
    # Log solar data every 15 minutes, but only during daylight hours (7 AM to 8 PM)
    scheduler.add_job(store_solar_data_job, 'cron', hour='7-20', minute='*/15')
    # Prune old data every 24 hours
    scheduler.add_job(prune_old_data_job, 'interval', hours=24)
    scheduler.start()

    # Ensure the scheduler shuts down cleanly when the app exits
    atexit.register(lambda: scheduler.shutdown(wait=False))

    app.run(host='0.0.0.0', port=5000)
