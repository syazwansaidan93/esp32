#include <Wire.h>
#include <Adafruit_INA219.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include "esp32-hal-cpu.h"
#include <WiFi.h>
#include <BluetoothSerial.h>

// INA219 Definitions
Adafruit_INA219 ina219;

// DS18B20 Definitions
#define DS18B20_PIN 4
OneWire oneWireBus(DS18B20_PIN);
DallasTemperature sensors(&oneWireBus);

// DS18B20 Device Addresses
DeviceAddress outdoorThermometer;
DeviceAddress indoorThermometer;

// INA219 Register Definitions for manual configuration
#define INA219_REG_CONFIG (0x00)
#define INA219_REG_CALIBRATION (0x05)

// Functions for INA219 power control
void setINA219PowerDown() {
  // Put the INA219 in power-down mode
  uint16_t config_value = 0x399F;
  config_value &= ~0x0007; // Clear the mode bits
  Wire.beginTransmission(0x40);
  Wire.write(INA219_REG_CONFIG);
  Wire.write((config_value >> 8) & 0xFF);
  Wire.write(config_value & 0xFF);
  Wire.endTransmission();
}

void setINA219Active() {
  // Bring the INA219 back to its active state
  uint16_t config_value = 0x399F;
  Wire.beginTransmission(0x40);
  Wire.write(INA219_REG_CONFIG);
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

void printSolarData() {
  Serial.print("{ \"sensor\": \"solar_pwr\", ");
  setINA219Active(); // Wake up sensor
  delay(50); // Adjusted delay for a more stable conversion
  if (!ina219.success()) {
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

void setup() {
  Serial.begin(115200);
  setCpuFrequencyMhz(80);
  
  // Turn off radio to save power
  WiFi.mode(WIFI_OFF);
  btStop();

  Wire.begin();
  
  // Initialize INA219
  if (!ina219.begin()) {
    Serial.println("Error: INA219 not found!");
  } else {
    float shunt_resistor = 0.1;
    float max_current_amp = 3.2;
    float current_lsb_amp = 0.0001; 
    uint16_t cal_value = (uint16_t) (0.04096 / (current_lsb_amp * shunt_resistor));
    Wire.beginTransmission(0x40);
    Wire.write(INA219_REG_CALIBRATION);
    Wire.write((cal_value >> 8) & 0xFF);
    Wire.write(cal_value & 0xFF);
    Wire.endTransmission();
    uint16_t config_value = 0x399F;
    Wire.beginTransmission(0x40);
    Wire.write(INA219_REG_CONFIG);
    Wire.write((config_value >> 8) & 0xFF);
    Wire.write(config_value & 0xFF);
    Wire.endTransmission();
  }
  setINA219PowerDown();

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
}

void loop() {
  if (Serial.available() > 0) {
    char command = Serial.read();
    switch (command) {
      case 'o':
        printOutdoorTemp();
        break;
      case 'i':
        printIndoorTemp();
        break;
      case 's':
        printSolarData();
        break;
      default:
        Serial.println("Invalid command. Use 'o', 'i', or 's'.");
        break;
    }
  }
}
