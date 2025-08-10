# ESP32-C3 GPIO Web Server

This project provides a simple and reliable way to control a connected ESP32-C3's GPIO pins via a Python-based web server. The server runs on an Orange Pi Zero 3 and communicates with the ESP32 over a serial connection.

The web server is designed to be resilient, automatically reconnecting to the ESP32 if the device is unplugged or the connection is lost. It is also configured to run as a background service using `systemd`.

## Features

* **Web API:** A simple HTTP endpoint to control GPIO pins.
* **Auto-Reconnect:** Automatically detects and re-establishes the serial connection if the ESP32 is unplugged.
* **Systemd Service:** Configured to run as a reliable background service on boot.

## Requirements

### Hardware
* Orange Pi Zero 3
* ESP32-C3 board
* USB-C cable for serial communication

### Software
* Python 3.x
* `venv` (Python Virtual Environment)
* `Flask`
* `pyserial`

## Setup

1.  **Code Placement:** Place the main Python script (e.g., `app.py`) in your desired working directory, such as `/home/wan/`.

2.  **Install Dependencies:** From your working directory, set up and activate a Python virtual environment and install the required packages.

    ```bash
    # Create the virtual environment
    python3 -m venv venv

    # Activate the virtual environment
    source venv/bin/activate

    # Install the required packages
    pip install Flask pyserial
    ```

3.  **Create Systemd Service:** Create a service file to run the application in the background.

    ```bash
    sudo nano /etc/systemd/system/esp32-flask.service
    ```

    Paste the following configuration into the file and save it:

    ```ini
    [Unit]
    Description=ESP32 Flask Web Server
    After=network.target

    [Service]
    User=wan
    Group=wan
    WorkingDirectory=/home/wan
    ExecStart=/home/wan/venv/bin/python /home/wan/app.py
    Restart=always

    [Install]
    WantedBy=multi-user.target
    ```

4.  **Start the Service:** Reload `systemd` to recognize the new service, then start and enable it.

    ```bash
    sudo systemctl daemon-reload
    sudo systemctl start esp32-flask.service
    sudo systemctl enable esp32-flask.service
    ```
