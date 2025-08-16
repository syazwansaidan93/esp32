#include <Wire.h>
#include <Adafruit_INA219.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include "esp32-hal-cpu.h"
#include <WiFi.h>
#include <BluetoothSerial.h>

// INA219 Definitions
Adafruit_INA219 ina219;
bool ina219_found = false;

// DS18B20 Definitions
#define DS18B20_PIN 4
OneWire oneWireBus(DS18B20_PIN);
DallasTemperature sensors(&oneWireBus);

// Relay Definition
#define RELAY_PIN 5

// DS18B20 Device Addresses
DeviceAddress outdoorThermometer;
DeviceAddress indoorThermometer;

// Global variables for automated relay control
float voltage_on_threshold = 12.6;
float voltage_off_threshold = 12.4;
bool auto_relay_mode = true;

// Functions for INA219 power control
void setINA219PowerDown() {
  // Put the INA219 in power-down mode
  uint16_t config_value = 0x399F;
  config_value &= ~0x0007; // Clear the mode bits
  Wire.beginTransmission(0x40);
  Wire.write(0x00); // INA219_REG_CONFIG
  Wire.write((config_value >> 8) & 0xFF);
  Wire.write(config_value & 0xFF);
  Wire.endTransmission();
}

void setINA219Active() {
  // Bring the INA219 back to its active state
  uint16_t config_value = 0x399F;
  Wire.beginTransmission(0x40);
  Wire.write(0x00); // INA219_REG_CONFIG
  Wire.write((config_value >> 8) & 0xFF);
  Wire.write(config_value & 0xFF);
  Wire.endTransmission();
}

// Functions to print specific sensor data with markers
void printOutdoorTemp() {
  sensors.requestTemperatures();
  float outdoor_temp_C = sensors.getTempC(outdoorThermometer);
  Serial.print("{ \"sensor\": \"o_temp\", \"value\": ");
  if (outdoor_temp_C != DEVICE_DISCONNECTED_C) {
    Serial.print(outdoor_temp_C);
  } else {
    Serial.print("\"error\"");
  }
  Serial.println(" }");
}

void printIndoorTemp() {
  sensors.requestTemperatures();
  float indoor_temp_C = sensors.getTempC(indoorThermometer);
  Serial.print("{ \"sensor\": \"i_temp\", \"value\": ");
  if (indoor_temp_C != DEVICE_DISCONNECTED_C) {
    Serial.print(indoor_temp_C);
  } else {
    Serial.print("\"error\"");
  }
  Serial.println(" }");
}

// This function now wakes up, reads, and then puts the sensor back to sleep.
void printSolarData() {
  setINA219Active(); // Wake up sensor
  delay(50); // Give it a moment to take a reading
  Serial.print("{ \"sensor\": \"solar_pwr\", ");
  if (!ina219_found) {
    Serial.println("\"status\": \"error\" }");
  } else {
    float ina219_voltage_V = ina219.getBusVoltage_V();
    float ina219_current_mA = ina219.getCurrent_mA();
    float ina219_power_mW = ina219.getPower_mW();
    Serial.print("\"voltage_V\": ");
    Serial.print(ina219_voltage_V);
    Serial.print(", \"current_mA\": ");
    Serial.print(ina219_current_mA);
    Serial.print(", \"power_mW\": ");
    Serial.print(ina219_power_mW);
    Serial.println(" }");
  }
  setINA219PowerDown(); // Put it back to sleep
}

// Function to print both temperature readings in one go
void printBothTemps() {
  sensors.requestTemperatures(); // Request temperatures only once
  float outdoor_temp_C = sensors.getTempC(outdoorThermometer);
  float indoor_temp_C = sensors.getTempC(indoorThermometer);
  Serial.print("{ \"o_temp\": ");
  if (outdoor_temp_C != DEVICE_DISCONNECTED_C) {
    Serial.print(outdoor_temp_C);
  } else {
    Serial.print("\"error\"");
  }
  Serial.print(", \"i_temp\": ");
  if (indoor_temp_C != DEVICE_DISCONNECTED_C) {
    Serial.print(indoor_temp_C);
  } else {
    Serial.print("\"error\"");
  }
  Serial.println(" }");
}

// Function to print relay status
void printRelayStatus() {
  int relayStatus = digitalRead(RELAY_PIN);
  if (relayStatus == HIGH) {
    Serial.println("{\"sensor\": \"relay\", \"value\": \"ON\"}");
  } else {
    Serial.println("{\"sensor\": \"relay\", \"value\": \"OFF\"}");
  }
}

// --- NEW FUNCTIONALITY FOR AUTO-RELAY CONTROL ---
void checkAndControlRelay() {
  if (!ina219_found) {
    return; // Do nothing if sensor isn't found
  }
  setINA219Active();
  delay(50);
  float current_voltage = ina219.getBusVoltage_V();
  setINA219PowerDown();

  int current_relay_status = digitalRead(RELAY_PIN);
  
  if (current_relay_status == LOW && current_voltage >= voltage_on_threshold) {
    digitalWrite(RELAY_PIN, HIGH);
    Serial.println("{\"relay_event\": \"auto_on\", \"voltage\": " + String(current_voltage) + "}");
  } else if (current_relay_status == HIGH && current_voltage <= voltage_off_threshold) {
    digitalWrite(RELAY_PIN, LOW);
    Serial.println("{\"relay_event\": \"auto_off\", \"voltage\": " + String(current_voltage) + "}");
  }
}

void printRelaySettings() {
  Serial.print("{ \"relay_settings\": { \"mode\": \"");
  if (auto_relay_mode) {
    Serial.print("auto");
  } else {
    Serial.print("manual");
  }
  Serial.print("\", \"voltage_on_threshold\": ");
  Serial.print(voltage_on_threshold);
  Serial.print(", \"voltage_off_threshold\": ");
  Serial.print(voltage_off_threshold);
  Serial.println(" } }");
}

void setup() {
  Serial.begin(115200);
  setCpuFrequencyMhz(80);
  
  // Turn off radio to save power
  WiFi.mode(WIFI_OFF);
  btStop();

  Wire.begin(6, 7); // Changed to use pins 6 and 7 as suggested.
  
  // Initialize INA219 and store the result
  ina219_found = ina219.begin();
  if (!ina219_found) {
    Serial.println("Error: INA219 not found!");
  } else {
    // The INA219 will now use the default calibration from the library.
  }

  // Initialize DS18B20 sensors
  sensors.begin();
  if (sensors.getDeviceCount() < 2) {
    Serial.println("Error: Not enough DS18B20 sensors found!");
  } else {
    // Manually assign addresses to avoid swapping issues
    const DeviceAddress outdoorAddress = { 0x28, 0x09, 0x8A, 0xC0, 0x00, 0x00, 0x00, 0xC7 };
    const DeviceAddress indoorAddress = { 0x28, 0x07, 0xBB, 0x83, 0x00, 0x00, 0x00, 0xF5 };
    
    memcpy(outdoorThermometer, outdoorAddress, 8);
    memcpy(indoorThermometer, indoorAddress, 8);

    sensors.setResolution(outdoorThermometer, 10);
    sensors.setResolution(indoorThermometer, 10);
  }
  
  // Initialize Relay
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW); // Start with the relay off
  setINA219PowerDown(); // Put the INA219 into power down mode after initialization
}

void loop() {
  // If in automatic mode, check and control the relay
  if (auto_relay_mode) {
    checkAndControlRelay();
  }
  
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim(); // Remove any leading/trailing whitespace or newlines

    if (command == "o") {
      printOutdoorTemp();
    } else if (command == "i") {
      printIndoorTemp();
    } else if (command == "s") {
      printSolarData();
    } else if (command == "r") {
      printRelayStatus();
    } else if (command == "r1") {
      auto_relay_mode = false; // Disable auto mode on manual command
      digitalWrite(RELAY_PIN, HIGH);
      printRelayStatus();
    } else if (command == "r0") {
      auto_relay_mode = false; // Disable auto mode on manual command
      digitalWrite(RELAY_PIN, LOW);
      printRelayStatus();
    } else if (command == "t") {
      printBothTemps();
    } else if (command == "auto") {
      auto_relay_mode = true;
      Serial.println("{\"mode\": \"auto\", \"status\": \"enabled\"}");
    } else if (command == "manual") {
      auto_relay_mode = false;
      Serial.println("{\"mode\": \"manual\", \"status\": \"enabled\"}");
    } else if (command.startsWith("set_on_V")) {
      float new_threshold = command.substring(command.indexOf(' ') + 1).toFloat();
      if (new_threshold > 0) {
        voltage_on_threshold = new_threshold;
        Serial.println("{\"command\": \"set_on_V\", \"value\": " + String(voltage_on_threshold) + "}");
      } else {
        Serial.println("{\"command\": \"set_on_V\", \"status\": \"error\", \"message\": \"invalid value\"}");
      }
    } else if (command.startsWith("set_off_V")) {
      float new_threshold = command.substring(command.indexOf(' ') + 1).toFloat();
      if (new_threshold > 0) {
        voltage_off_threshold = new_threshold;
        Serial.println("{\"command\": \"set_off_V\", \"value\": " + String(voltage_off_threshold) + "}");
      } else {
        Serial.println("{\"command\": \"set_off_V\", \"status\": \"error\", \"message\": \"invalid value\"}");
      }
    } else if (command == "get_settings") {
      printRelaySettings();
    } else {
      Serial.println("Invalid command.");
    }
  }
}
