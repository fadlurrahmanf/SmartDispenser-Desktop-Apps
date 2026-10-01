#pragma once

#include <Arduino.h>
#include <EEPROM.h>
#include <HardwareSerial.h>
#include <Wire.h>

// Pin map is transcribed from WaterDispenserESP32 schematic (2026-09-10).
// GPIO4/5: shared I2C bus (PN532 and optional LCD/RTC).
// GPIO10: RLY1, GPIO18: RLY2, GPIO3: FLOW pulse input.
// SW1/SW2/SW3: GPIO6/GPIO7/GPIO19, active LOW, with a shared GND return.
// GPIO20/21: ESP32-C3 UART0 RXD/TXD routed to the USB-UART circuit.
namespace waterdispenser_esp32 {
constexpr int kI2cSdaPin = 4;
constexpr int kI2cSclPin = 5;
constexpr int kRelay1Pin = 10;
constexpr int kRelay2Pin = 18;
constexpr int kFlowPin = 3;
// The supplied PCB source does not prove a separate LED or flow-indicator
// net. GPIO6 and GPIO7 are front-panel switches, so never drive them.
constexpr int kLedPin = -1;
constexpr int kFlowIndicatorPin = -1;
constexpr int kUartRxPin = 20;
constexpr int kUartTxPin = 21;
constexpr bool kRelayActiveHigh = true;
constexpr bool kLedActiveLow = true;

constexpr int kButtonP1Pin = 6;
constexpr int kButtonP2Pin = 7;
constexpr int kButtonP3Pin = 19;

inline bool beginStorage() { return EEPROM.begin(128); }
inline void updateStorage(int address, uint8_t value) {
  if (EEPROM.read(address) == value) return;
  EEPROM.write(address, value);
  EEPROM.commit();
}
inline void beginI2c() { Wire.begin(kI2cSdaPin, kI2cSclPin, 100000); }
inline void beginBridge(HardwareSerial &serial) {
  serial.begin(115200, SERIAL_8N1, kUartRxPin, kUartTxPin);
}
inline void writeRelay(int pin, bool on) {
  digitalWrite(pin, (on == kRelayActiveHigh) ? HIGH : LOW);
}
inline bool buttonPressed(int pin) {
  return pin >= 0 && digitalRead(pin) == LOW;
}
}  // namespace waterdispenser_esp32
