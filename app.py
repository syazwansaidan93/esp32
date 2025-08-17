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
import logging

# Configure logging
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')

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
    ports = serial.tools.list_ports.comports()
    for port in ports:
        if "USB" in port.device or "ACM" in port.device:
            logging.info(f"Found potential serial port: {port.device}")
            return port.device
    logging.warning("No suitable serial port found.")
    return None

def connect_to_serial():
    global ser
    if ser and ser.is_open:
        return True
    
    serial_port = find_serial_port()
    if not serial_port:
        return False
    
    try:
        ser = serial.Serial(serial_port, BAUD_RATE, timeout=DATA_TIMEOUT)
        time.sleep(2)
        ser.flushInput()
        logging.info(f"Serial port {serial_port} opened successfully.")
        return True
    except serial.SerialException as e:
        logging.error(f"Error opening serial port {serial_port}: {e}")
        ser = None
        return False

def close_serial_port():
    global ser
    if ser and ser.is_open:
        logging.info("Closing serial port...")
        ser.close()
        ser = None

# --- Data Fetching and Processing ---

def fetch_from_serial(command):
    global ser
    with serial_lock:
        if not ser or not ser.is_open:
            logging.warning("Serial port not connected. Attempting to reconnect...")
            if not connect_to_serial():
                logging.error("Failed to reconnect to serial port.")
                return None

        try:
            ser.flushInput()
            ser.write(command.encode('utf-8') + b'\n')
            
            start_time = time.time()
            while time.time() - start_time < DATA_TIMEOUT:
                line = ser.readline().decode('utf-8').strip()
                if line and line.startswith('{') and line.endswith('}'):
                    try:
                        data = json.loads(line)
                        return data
                    except json.JSONDecodeError:
                        logging.warning(f"Could not parse line as JSON: {line}")
                elif line:
                    logging.info(f"Ignoring non-JSON line: {line}")
            
            logging.warning(f"Timed out waiting for a valid JSON response to command: {command}")
            return None
        except serial.SerialException as e:
            logging.error(f"Serial communication error: {e}. Attempting to close and reconnect.")
            close_serial_port()
            return None
        except Exception as e:
            logging.error(f"An unexpected error occurred during serial communication: {e}")
            return None

# --- Database Management ---

def get_db_connection():
    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn

def setup_database():
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
    logging.info("Running scheduled job to store temperature data...")
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
            logging.info("Temperature data stored successfully.")
        except sqlite3.Error as e:
            logging.error(f"Error storing data to SQLite: {e}")
    else:
        logging.warning("Failed to fetch temperature data for storage.")

def store_solar_data_job():
    logging.info("Running scheduled job to store solar data...")
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
            logging.info("Solar data stored successfully.")
        except sqlite3.Error as e:
            logging.error(f"Error storing solar data to SQLite: {e}")
    else:
        logging.warning("Failed to fetch solar data for storage.")

def prune_old_data_job():
    logging.info("Running scheduled job to prune old data...")
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
        logging.info(f"Successfully pruned {deleted_temp_count} old temperature records and {deleted_solar_count} old solar records.")
    except sqlite3.Error as e:
        logging.error(f"Error pruning old data: {e}")

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
    data = fetch_from_serial('get_settings')
    if data and 'relay_settings' in data:
        return jsonify(data['relay_settings'])
    return jsonify({"error": "Failed to fetch settings"}), 500

@app.route('/settings/auto', methods=['POST'])
def set_auto_mode():
    fetch_from_serial('auto')
    return jsonify({"status": "success", "message": "Automatic mode enabled"}), 200

@app.route('/settings/manual', methods=['POST'])
def set_manual_mode():
    fetch_from_serial('manual')
    return jsonify({"status": "success", "message": "Manual mode enabled"}), 200

@app.route('/settings/set_power_on_mW', methods=['POST'])
def set_power_on_threshold():
    value = request.args.get('value')
    if value is None:
        return jsonify({"status": "error", "message": "Missing 'value' parameter"}), 400
    data = fetch_from_serial(f'set_power_on_mW {value}')
    if data and data.get('command') == 'set_power_on_mW':
        return jsonify({"status": "success", "new_value": data.get('value')})
    return jsonify({"status": "error", "message": "Failed to set threshold"}), 500

@app.route('/settings/set_power_off_mW', methods=['POST'])
def set_power_off_threshold():
    value = request.args.get('value')
    if value is None:
        return jsonify({"status": "error", "message": "Missing 'value' parameter"}), 400
    data = fetch_from_serial(f'set_power_off_mW {value}')
    if data and data.get('command') == 'set_power_off_mW':
        return jsonify({"status": "success", "new_value": data.get('value')})
    return jsonify({"status": "error", "message": "Failed to set threshold"}), 500

@app.route('/settings/set_voltage_cutoff_V', methods=['POST'])
def set_voltage_cutoff():
    value = request.args.get('value')
    if value is None:
        return jsonify({"status": "error", "message": "Missing 'value' parameter"}), 400
    data = fetch_from_serial(f'set_voltage_cutoff_V {value}')
    if data and data.get('command') == 'set_voltage_cutoff_V':
        return jsonify({"status": "success", "new_value": data.get('value')})
    return jsonify({"status": "error", "message": "Failed to set threshold"}), 500

if __name__ == '__main__':
    setup_database()
    connect_to_serial()
    atexit.register(close_serial_port)
    scheduler = BackgroundScheduler()
    scheduler.add_job(store_temperature_data_job, 'interval', minutes=15)
    scheduler.add_job(store_solar_data_job, 'cron', hour='7-19', minute='*/10')
    scheduler.add_job(prune_old_data_job, 'interval', hours=24)
    scheduler.start()
    app.run(host='0.0.0.0', port=5000)
