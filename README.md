# ESP32-C3 Data Logger and Control Hub

This project is a Python Flask application designed to run on a host machine, such as an Orange Pi Zero 3, to communicate with an ESP32-C3 microcontroller. It acts as a central hub for reading sensor data from the ESP32 and providing a web-based API for remote monitoring and control.

### Features

* **Serial Communication:** Establishes and manages a serial connection to the ESP32-C3.

* **Robustness:** Automatically re-connects to the serial port if the connection is lost.

* **Data Logging:** Periodically fetches sensor data (temperature and solar) and stores it in a SQLite database.

* **Data Pruning:** Automatically prunes old data to save disk space.

* **Web API:** Exposes RESTful endpoints to get the latest sensor readings and control a connected relay.

* **Background Operation:** Designed to run as a `systemd` service for reliable, continuous operation.

### Prerequisites

* **Hardware**

  * Orange Pi Zero 3 (or any SBC)

  * ESP32-C3 with a compatible serial-over-USB connection

  * DS18B20 temperature sensors

  * INA219 current/power sensor

  * A relay connected to the ESP32

* **Software**

  * Armbian (or another Linux distribution)

  * Python 3.x

  * `pip`

  * `venv` (Python Virtual Environment)

  * `systemd` (pre-installed on Armbian)

### Installation

1. **Navigate to your working directory:**

   ```
   cd /home/wan/
   ```

2. **Create and activate a Python virtual environment:**

   ```
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install the required Python packages:**

   ```
   pip install pyserial Flask APScheduler
   ```

### Configuration

You can adjust the following constants at the top of the `app.py` script to match your setup:

* `BAUD_RATE`: The baud rate for serial communication.

* `DATA_TIMEOUT`: The timeout in seconds for a serial response.

* `DB_FILE`: The name of the SQLite database file.

### Usage

To start the Flask application, navigate to your project directory and run:

```
source venv/bin/activate
python app.py
```

You can then access the following API endpoints using `curl` or a web browser:

* `http://localhost:5000/r/on` - Turn the relay ON (POST request)

* `http://localhost:5000/r/off` - Turn the relay OFF (POST request)

* `http://localhost:5000/s/latest` - Get the latest solar power data

* `http://localhost:5000/t/latest` - Get the latest temperature data

### API Endpoints

Here is a full list of all available API endpoints and their functions.

#### Control Endpoints

These endpoints are used to send commands to the ESP32 to control the relay and other settings.

* `POST /r/on` - Turns the relay ON.

* `POST /r/off` - Turns the relay OFF.

* `POST /settings/auto` - Enables automatic control mode for the relay.

* `POST /settings/manual` - Enables manual control mode for the relay.

* `POST /settings/set_power_on_mW?value=...` - Sets the solar power threshold (in mW) to turn the relay ON.

* `POST /settings/set_power_off_mW?value=...` - Sets the solar power threshold (in mW) to turn the relay OFF.

* `POST /settings/set_voltage_cutoff_V?value=...` - Sets the voltage cutoff threshold (in V) for the relay.

#### Data Retrieval Endpoints

These endpoints are used to retrieve the latest sensor data and historical logs from the database.

* `GET /r/latest` - Gets the current status of the relay.

* `GET /o/latest` - Gets the latest outdoor temperature.

* `GET /i/latest` - Gets the latest indoor temperature.

* `GET /s/latest` - Gets the latest solar power data (voltage, current, and power).

* `GET /t/latest` - Gets both the latest indoor and outdoor temperature readings.

* `GET /o/24` - Retrieves outdoor temperature data from the last 24 hours.

* `GET /o/48` - Retrieves outdoor temperature data from the last 48 hours.

* `GET /i/24` - Retrieves indoor temperature data from the last 24 hours.

* `GET /i/48` - Retrieves indoor temperature data from the last 48 hours.

* `GET /t/24` - Retrieves both indoor and outdoor temperature data from the last 24 hours.

* `GET /t/48` - Retrieves both indoor and outdoor temperature data from the last 48 hours.

* `GET /s/24` - Retrieves solar data from the last 24 hours.

* `GET /s/48` - Retrieves solar data from the last 48 hours.

* `GET /settings` - Gets the current relay settings, including thresholds and mode.

### Running as a `systemd` Service

For reliable, hands-free operation, it is recommended to run the application as a `systemd` service.

1. **Create the service file:**

   ```
   sudo nano /etc/systemd/system/esp32-data-logger.service
   ```

2. **Paste the following content into the file:**

   ```
   [Unit]
   Description=ESP32 Data Logger Flask App
   After=network.target
   
   [Service]
   User=wan
   Group=wan
   WorkingDirectory=/home/wan/
   ExecStart=/home/wan/venv/bin/python /home/wan/app.py
   Restart=always
   
   [Install]
   WantedBy=multi-user.target
   ```

3. **Save the file and exit the editor.**

4. **Reload `systemd` to recognize the new service:**

   ```
   sudo systemctl daemon-reload
   ```

5. **Enable and start the service:**

   ```
   sudo systemctl enable esp32-data-logger
   sudo systemctl start esp32-data-logger
   ```

### Troubleshooting and Debugging

You can use the `journalctl` command to check the status and logs of your service.

* **Check the service status:**

  ```
  sudo systemctl status esp32-data-logger
  ```

* **View the logs (including warnings and errors):**

  ```
  sudo journalctl -u esp32-data-logger -f
  
