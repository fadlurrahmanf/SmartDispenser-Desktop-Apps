// SmartDispenser — Device A. Wallet V2 berada di Block 8; referensi compact,
// counter, dan MAC berada di Block 9. Block 10 adalah jurnal commit. Build ini
// belum anti-clone penuh.

#include <Arduino.h>
#include <HardwareTimer.h>
#include <Wire.h>
#include <EEPROM.h>
#include <LiquidCrystal_PCF8574.h>
#include <PN532_I2C.h>
#include <PN532.h>
#include <cstring>
#include <cstdio>
#include "CompactCardSecurity.h"
#include "CompactCardWallet.h"

constexpr uint32_t kLedPin = PC13;
constexpr bool kLedActiveLow = true;
constexpr uint32_t kI2cSdaPin = PB9, kI2cSclPin = PB8;
constexpr uint8_t kLcdI2cAddress = 0x27u, kRtcI2cAddress = 0x68u;
constexpr uint32_t kButtonP1Pin = PB3, kButtonP2Pin = PB4, kButtonP3Pin = PA11;
constexpr uint32_t kIndicatorPb0Pin = PB0, kIndicatorPb1Pin = PB1, kFlowPin = PA0;
// Hasil uji perangkat: kanal solenoid terbalik terhadap asumsi awal.
// PA3 = SET (solenoid buka), PA2 = RST (solenoid tutup).
constexpr uint32_t kRelay1SetPin = PA3, kRelay1ResetPin = PA2;
// Hasil uji perangkat: kanal pompa terbalik terhadap asumsi awal.
// PB2 = SET (pompa ON), PA4 = RST (pompa OFF).
constexpr uint32_t kRelay2SetPin = PB2, kRelay2ResetPin = PA4;
constexpr uint8_t kWalletBlock = smartdispenser::compact_card::kWalletBlock;
constexpr uint8_t kMetadataBlock = smartdispenser::compact_card::kMetadataBlock;
constexpr uint8_t kJournalBlock = smartdispenser::compact_card::kJournalBlock;
constexpr uint8_t kScheduleNone = smartdispenser::compact_card::kScheduleNone;
constexpr uint8_t kSchedulePagi = smartdispenser::compact_card::kSchedulePagi;
constexpr uint8_t kScheduleSiang = smartdispenser::compact_card::kScheduleSiang;
constexpr uint8_t kScheduleSore = smartdispenser::compact_card::kScheduleSore;
constexpr uint8_t kDailyQuotaLitres = smartdispenser::compact_card::kDailyQuotaLitres;
// Kalibrasi YF-B10 khusus unit ini. Pengukuran setelah iterasi sebelumnya
// menunjukkan kelebihan proporsional: 1 L -> 1,03 L, 2 L -> 2,06 L, dan
// 10 L -> 10,30 L. Faktor efektifnya 400 pulsa/L, bukan nilai umum YF-B10.
constexpr uint16_t kPulsesPerLitre = 400;
// Air masih mengalir kira-kira 50 ml sesudah pulsa target terakhir. Pada
// 400 pulsa/L, kompensasinya 20 pulsa; target dikurangi sebelum pompa hidup.
constexpr uint16_t kStopFlowCompensationPulses = 20;
// Jadwal dan kuota adalah aturan keselamatan bisnis. Tanpa RTC tepercaya,
// transaksi ditolak (fail-closed), bukan dibypass seperti mode demo lama.
constexpr bool kUseRtc = true;
constexpr int kEepromMasterFlag = 0, kEepromMasterUid = 1;
constexpr int kEepromPendingBase = 16;
// D5 adalah format jurnal lama. D6 menambahkan mode agar transaksi baru tetap
// dapat dicatat ketika kartu sudah membawa cadangan dari transaksi sebelumnya.
constexpr uint8_t kPendingMagicLegacy = 0xD5, kPendingMagic = 0xD6;
constexpr uint8_t kPendingModeCardReserve = 0xA5, kPendingModeSeparateReserve = 0x5A;
const uint8_t (&kCardKeyA)[6] = smartdispenser::compact_card_private::kMifareKeyA;

Uart logger(PA10, PA9);
LiquidCrystal_PCF8574 lcd(kLcdI2cAddress);
bool lcdReady = false;
PN532_I2C pn532i2c(Wire);
PN532 nfc(pn532i2c);
bool masterSet = false;
uint8_t masterUid[4] = {0,0,0,0};
using Wallet = smartdispenser::compact_card::Wallet;

void logPrefix() { logger.print('['); logger.print(millis()); logger.print("] "); }
void emitCardEvent(const char *state, uint32_t reference, const Wallet *wallet = nullptr) {
  logger.print("EVT card state="); logger.print(state);
  if (reference != 0) { logger.print(" reference="); logger.print(reference, HEX); }
  if (wallet) {
    logger.print(" balance="); logger.print(wallet->available);
    logger.print(" active="); logger.print(wallet->permitted ? 1 : 0);
    logger.print(" schedule="); logger.print(wallet->schedule);
    logger.print(" used="); logger.print(wallet->usedToday);
    logger.print(" reserved="); logger.print(wallet->reserved);
  }
  logger.println();
}
void emitTransactionEvent(const char *state, uint32_t reference, uint8_t schedule,
                          uint8_t requested, uint8_t actual, uint8_t balance,
                          uint32_t revision, const char *reason) {
  logger.print("EVT transaction state="); logger.print(state);
  logger.print(" reference="); logger.print(reference, HEX);
  logger.print(" schedule="); logger.print(schedule);
  logger.print(" requested="); logger.print(requested);
  logger.print(" actual="); logger.print(actual);
  logger.print(" balance="); logger.print(balance);
  logger.print(" revision="); logger.print(revision);
  logger.print(" reason="); logger.println(reason);
}
void lcdShow(const char *l1, const char *l2) {
  if (!lcdReady) return;
  char a[17], b[17]; std::memset(a, ' ', 16); std::memset(b, ' ', 16); a[16] = b[16] = 0;
  const size_t n1 = strnlen(l1, 16), n2 = strnlen(l2, 16);
  std::memcpy(a + (16 - n1) / 2, l1, n1); std::memcpy(b + (16 - n2) / 2, l2, n2);
  a[15] = (millis() / 500) % 2 == 0 ? '*' : ' ';
  lcd.setCursor(0, 0); lcd.print(a); lcd.setCursor(0, 1); lcd.print(b);
}

enum class WalletRead { Ok, Legacy, Invalid };
bool reselectCard(uint8_t uid[4]) {
  uint8_t freshUid[7]{}, freshLen = 0;
  if (!nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, freshUid, &freshLen) || freshLen != 4) return false;
  if (std::memcmp(uid, freshUid, 4) != 0) return false;
  return true;
}
bool writeProtectedBlockWithRetry(uint8_t uid[4], uint8_t blockNumber, uint8_t data[16]) {
  for (uint8_t attempt = 0; attempt < 3; ++attempt) {
    if (!reselectCard(uid)) return false;
    uint8_t key[6]; std::memcpy(key, kCardKeyA, 6);
    if (!nfc.mifareclassic_AuthenticateBlock(uid, 4, blockNumber, 0, key)) continue;
    if (nfc.mifareclassic_WriteDataBlock(blockNumber, data)) return true;
  }
  return false;
}
WalletRead readWallet(uint8_t uid[4], Wallet &out, smartdispenser::compact_card::Metadata *metadata = nullptr) {
  uint8_t key[6]; std::memcpy(key, kCardKeyA, 6);
  if (!nfc.mifareclassic_AuthenticateBlock(uid, 4, kWalletBlock, 0, key)) return WalletRead::Invalid;
  uint8_t block[16]{}; if (!nfc.mifareclassic_ReadDataBlock(kWalletBlock, block)) return WalletRead::Invalid;
  if (smartdispenser::compact_card::decodeWallet(block, out)) {
    uint8_t metadataBlock[16]{};
    if (!nfc.mifareclassic_ReadDataBlock(kMetadataBlock, metadataBlock)) return WalletRead::Invalid;
    smartdispenser::compact_card::Metadata decoded{};
    if (!smartdispenser::compact_card::decodeAndVerify(uid, block, metadataBlock, decoded)) {
      uint8_t journalBlock[16]{};
      if (!nfc.mifareclassic_ReadDataBlock(kJournalBlock, journalBlock)) return WalletRead::Invalid;
      smartdispenser::compact_card::Metadata recovered{};
      if (!smartdispenser::compact_card::decodeAndVerify(uid, block, journalBlock, recovered)) {
        return smartdispenser::compact_card::isBlank(metadataBlock) ? WalletRead::Legacy : WalletRead::Invalid;
      }
      if (!writeProtectedBlockWithRetry(uid, kMetadataBlock, journalBlock)) return WalletRead::Invalid;
      decoded = recovered;
    }
    if (metadata) *metadata = decoded;
    return WalletRead::Ok;
  }
  if (block[0] == 'W' && block[3] <= 100 && block[4] <= 1) return WalletRead::Legacy;
  return WalletRead::Invalid;
}
bool writeWallet(uint8_t uid[4], const Wallet &w, const smartdispenser::compact_card::Metadata &current) {
  uint8_t block[16]{}; smartdispenser::compact_card::encodeWallet(w, block);
  smartdispenser::compact_card::Metadata next = current;
  if (next.cardReference == 0 || next.transactionCounter == 0xFFFFFFFFu) return false;
  ++next.transactionCounter;
  uint8_t metadataBlock[16]{};
  if (!smartdispenser::compact_card::encode(uid, block, next, metadataBlock)) return false;
  if (!writeProtectedBlockWithRetry(uid, kJournalBlock, metadataBlock)) return false;
  if (!writeProtectedBlockWithRetry(uid, kWalletBlock, block)) return false;
  if (!writeProtectedBlockWithRetry(uid, kMetadataBlock, metadataBlock)) return false;
  Wallet verify{}; smartdispenser::compact_card::Metadata verified{};
  if (readWallet(uid, verify, &verified) != WalletRead::Ok || !smartdispenser::compact_card::walletEqual(verify, w) ||
      verified.cardReference != next.cardReference || verified.transactionCounter != next.transactionCounter) return false;
  uint8_t blankJournal[16]{};
  (void)writeProtectedBlockWithRetry(uid, kJournalBlock, blankJournal);
  return true;
}

uint8_t bcdToDec(uint8_t value) { return static_cast<uint8_t>((value >> 4) * 10 + (value & 0x0F)); }
uint8_t decToBcd(uint8_t value) { return static_cast<uint8_t>(((value / 10) << 4) | (value % 10)); }
struct RtcTime { uint16_t year = 2026; uint8_t month = 1, day = 1, hour = 0, minute = 0, second = 0; };
bool rtcRead(RtcTime &out) {
  Wire.beginTransmission(kRtcI2cAddress); Wire.write(0); if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(kRtcI2cAddress, static_cast<uint8_t>(7)) != 7) return false;
  uint8_t raw[7]{}; for (uint8_t i = 0; i < 7; ++i) raw[i] = Wire.read();
  Wire.beginTransmission(kRtcI2cAddress); Wire.write(0x0F); if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(kRtcI2cAddress, static_cast<uint8_t>(1)) != 1) return false;
  if ((Wire.read() & 0x80) != 0) return false; // oscillator stop: waktu belum dipercaya.
  out.second = bcdToDec(raw[0] & 0x7F); out.minute = bcdToDec(raw[1] & 0x7F); out.hour = bcdToDec(raw[2] & 0x3F);
  out.day = bcdToDec(raw[4] & 0x3F); out.month = bcdToDec(raw[5] & 0x1F); out.year = static_cast<uint16_t>(2000 + bcdToDec(raw[6]));
  return out.year >= 2026 && out.month >= 1 && out.month <= 12 && out.day >= 1 && out.day <= 31 && out.hour < 24 && out.minute < 60 && out.second < 60;
}
bool rtcWrite(const RtcTime &time) {
  Wire.beginTransmission(kRtcI2cAddress); Wire.write(0); Wire.write(decToBcd(0)); Wire.write(decToBcd(time.minute)); Wire.write(decToBcd(time.hour)); Wire.write(1);
  Wire.write(decToBcd(time.day)); Wire.write(decToBcd(time.month)); Wire.write(decToBcd(static_cast<uint8_t>(time.year - 2000)));
  if (Wire.endTransmission() != 0) return false;
  Wire.beginTransmission(kRtcI2cAddress); Wire.write(0x0F); Wire.write(0); return Wire.endTransmission() == 0;
}
bool leap(uint16_t year) { return (year % 4 == 0 && year % 100 != 0) || year % 400 == 0; }
uint16_t dayId(const RtcTime &time) {
  static const uint16_t daysBeforeMonth[] = {0,0,31,59,90,120,151,181,212,243,273,304,334};
  uint32_t total = 0; for (uint16_t year = 2026; year < time.year; ++year) total += leap(year) ? 366 : 365;
  total += daysBeforeMonth[time.month] + time.day - 1; if (time.month > 2 && leap(time.year)) ++total; return static_cast<uint16_t>(total);
}
uint8_t scheduleForHour(uint8_t hour) { return hour >= 6 && hour < 10 ? kSchedulePagi : hour >= 10 && hour < 14 ? kScheduleSiang : hour >= 14 && hour < 18 ? kScheduleSore : kScheduleNone; }
const char *scheduleName(uint8_t schedule) { return schedule == kSchedulePagi ? "PAGI" : schedule == kScheduleSiang ? "SIANG" : schedule == kScheduleSore ? "SORE" : "-"; }

void loadMaster() { masterSet = EEPROM.read(kEepromMasterFlag) == 0xA5; for (uint8_t i = 0; i < 4; ++i) masterUid[i] = EEPROM.read(kEepromMasterUid + i); }
void saveMaster(const uint8_t uid[4]) { for (uint8_t i = 0; i < 4; ++i) EEPROM.update(kEepromMasterUid + i, uid[i]); EEPROM.update(kEepromMasterFlag, 0xA5); masterSet = true; std::memcpy(masterUid, uid, 4); }

struct PendingSettlement {
  bool valid = false;
  bool usesCardReserve = true;
  uint32_t reference = 0;
  uint8_t requested = 0;
  uint8_t actual = 0;
  uint8_t schedule = kScheduleNone;
};
uint16_t pendingChecksumLegacy(uint32_t reference, uint8_t requested, uint8_t actual, uint8_t schedule) {
  uint8_t raw[7] = {
    static_cast<uint8_t>(reference >> 24), static_cast<uint8_t>(reference >> 16),
    static_cast<uint8_t>(reference >> 8), static_cast<uint8_t>(reference),
    requested, actual, schedule
  };
  return smartdispenser::compact_card::walletCrc16Ccitt(raw, sizeof(raw));
}
uint16_t pendingChecksum(uint32_t reference, uint8_t requested, uint8_t actual, uint8_t schedule, bool usesCardReserve) {
  uint8_t raw[8] = {
    static_cast<uint8_t>(reference >> 24), static_cast<uint8_t>(reference >> 16),
    static_cast<uint8_t>(reference >> 8), static_cast<uint8_t>(reference),
    requested, actual, schedule, static_cast<uint8_t>(usesCardReserve ? 1 : 0)
  };
  return smartdispenser::compact_card::walletCrc16Ccitt(raw, sizeof(raw));
}
void clearPendingSettlement() { EEPROM.update(kEepromPendingBase, 0); }
void savePendingSettlement(uint32_t reference, uint8_t requested, uint8_t actual, uint8_t schedule, bool usesCardReserve) {
  clearPendingSettlement();
  EEPROM.update(kEepromPendingBase + 1, static_cast<uint8_t>(reference >> 24));
  EEPROM.update(kEepromPendingBase + 2, static_cast<uint8_t>(reference >> 16));
  EEPROM.update(kEepromPendingBase + 3, static_cast<uint8_t>(reference >> 8));
  EEPROM.update(kEepromPendingBase + 4, static_cast<uint8_t>(reference));
  EEPROM.update(kEepromPendingBase + 5, requested);
  EEPROM.update(kEepromPendingBase + 6, actual);
  EEPROM.update(kEepromPendingBase + 7, schedule);
  const uint16_t checksum = pendingChecksum(reference, requested, actual, schedule, usesCardReserve);
  EEPROM.update(kEepromPendingBase + 8, static_cast<uint8_t>(checksum >> 8));
  EEPROM.update(kEepromPendingBase + 9, static_cast<uint8_t>(checksum));
  EEPROM.update(kEepromPendingBase + 10, usesCardReserve ? kPendingModeCardReserve : kPendingModeSeparateReserve);
  EEPROM.update(kEepromPendingBase, kPendingMagic);
}
PendingSettlement loadPendingSettlement() {
  PendingSettlement pending{};
  const uint8_t magic = EEPROM.read(kEepromPendingBase);
  if (magic != kPendingMagic && magic != kPendingMagicLegacy) return pending;
  pending.reference = (static_cast<uint32_t>(EEPROM.read(kEepromPendingBase + 1)) << 24) |
                      (static_cast<uint32_t>(EEPROM.read(kEepromPendingBase + 2)) << 16) |
                      (static_cast<uint32_t>(EEPROM.read(kEepromPendingBase + 3)) << 8) |
                      static_cast<uint32_t>(EEPROM.read(kEepromPendingBase + 4));
  pending.requested = EEPROM.read(kEepromPendingBase + 5);
  pending.actual = EEPROM.read(kEepromPendingBase + 6);
  pending.schedule = EEPROM.read(kEepromPendingBase + 7);
  const uint16_t saved = static_cast<uint16_t>((EEPROM.read(kEepromPendingBase + 8) << 8) |
                                                EEPROM.read(kEepromPendingBase + 9));
  if (magic == kPendingMagicLegacy) {
    pending.usesCardReserve = true;
    pending.valid = saved == pendingChecksumLegacy(pending.reference, pending.requested, pending.actual, pending.schedule);
  } else {
    const uint8_t mode = EEPROM.read(kEepromPendingBase + 10);
    if (mode != kPendingModeCardReserve && mode != kPendingModeSeparateReserve) return pending;
    pending.usesCardReserve = mode == kPendingModeCardReserve;
    pending.valid = saved == pendingChecksum(pending.reference, pending.requested, pending.actual, pending.schedule, pending.usesCardReserve);
  }
  pending.valid = pending.valid && pending.reference != 0 && pending.requested <= kDailyQuotaLitres &&
                  pending.actual <= pending.requested && pending.schedule <= kScheduleSore;
  return pending;
}

volatile uint32_t pulses = 0, target = 0, lastPulseUs = 0;
volatile bool running = false, targetReached = false;
HardwareTimer coilTimer(TIM2);
// Reset pompa tetap diberi pulsa 60 ms. Tidak ada jeda tambahan sebelum
// solenoid ditutup: jeda 300 ms sebelumnya menyumbang sekitar 150 ml setelah
// target flow tercapai pada pengukuran kalibrasi unit ini.
constexpr uint32_t kCoilPulseMs = 60, kSolenoidSettleMs = 300, kPumpStopSettleMs = 0, kBootResetDelayMs = 1000;
volatile uint32_t relay1PulseAt = 0, relay2PulseAt = 0;
volatile bool relay1PulseActive = false, relay2PulseActive = false;

void pulseRelay1(bool set) {
  digitalWrite(set ? kRelay1ResetPin : kRelay1SetPin, LOW);
  digitalWrite(set ? kRelay1SetPin : kRelay1ResetPin, HIGH);
  relay1PulseAt = millis(); relay1PulseActive = true;
}
void pulseRelay2(bool set) {
  digitalWrite(set ? kRelay2ResetPin : kRelay2SetPin, LOW);
  digitalWrite(set ? kRelay2SetPin : kRelay2ResetPin, HIGH);
  relay2PulseAt = millis(); relay2PulseActive = true;
}
void coilTick() {
  const uint32_t now = millis();
  if (relay1PulseActive && now - relay1PulseAt >= kCoilPulseMs) {
    digitalWrite(kRelay1SetPin, LOW); digitalWrite(kRelay1ResetPin, LOW); relay1PulseActive = false;
  }
  if (relay2PulseActive && now - relay2PulseAt >= kCoilPulseMs) {
    digitalWrite(kRelay2SetPin, LOW); digitalWrite(kRelay2ResetPin, LOW); relay2PulseActive = false;
  }
}
void commandSolenoid(bool open) { pulseRelay1(open); logPrefix(); logger.println(open ? "SOLENOID SET" : "SOLENOID RST"); }
void commandPump(bool on) { pulseRelay2(on); logPrefix(); logger.println(on ? "POMPA SET" : "POMPA RST"); }
void onFlow() {
  static uint32_t previous = 0; const uint32_t now = micros();
  if (!running || static_cast<uint32_t>(now - previous) < 2000) return;
  previous = now; lastPulseUs = now; ++pulses;
  digitalWrite(kIndicatorPb0Pin, (pulses & 1) ? LOW : HIGH);
  if (pulses >= target) { running = false; targetReached = true; }
}

struct Key { uint32_t changed = 0; bool raw = false, stable = false; bool update(bool pressed, uint32_t now) { if (pressed != raw) { raw = pressed; changed = now; } if (stable != raw && now - changed >= 30) { stable = raw; return stable; } return false; } } keyP1, keyP2, keyP3;
enum class Page { Idle, Menu, Dispensing, Done, Rejected, ClockEdit };
enum class ActuatorState { BootWait, BootResetSolenoid, BootResetPump, Safe, OpeningSolenoid, OpeningDelay, PumpStarting, PumpRunning, StopWaitPumpPulse, PumpStopping, StoppingDelay, ClosingSolenoid };
enum class StopReason { None, TargetReached, UserStop, CardLost };
Page page = Page::Idle;
ActuatorState actuatorState = ActuatorState::BootWait;
StopReason stopReason = StopReason::None;
uint8_t boundUid[4] = {0,0,0,0}, heldMasterUid[4] = {0,0,0,0};
uint8_t selectedLitres = 0, clockField = 0;
uint8_t transactionSchedule = kScheduleNone;
uint32_t transactionCardReference = 0;
uint32_t pageAt = 0, masterHoldAt = 0, presenceAt = 0, actuatorAt = 0;
bool masterHolding = false, noFlowWarning = false, stopSequenceComplete = false, transactionUsesCardReserve = true;
uint8_t cardTraceStage = 0;
RtcTime editTime{};

bool actuatorIsBooting() { return actuatorState == ActuatorState::BootWait || actuatorState == ActuatorState::BootResetSolenoid || actuatorState == ActuatorState::BootResetPump; }
void beginDispenseActuation(uint8_t litres) {
  const uint32_t requestedPulses = static_cast<uint32_t>(litres) * kPulsesPerLitre;
  const uint32_t compensatedTarget = requestedPulses > kStopFlowCompensationPulses
    ? requestedPulses - kStopFlowCompensationPulses
    : requestedPulses;
  noInterrupts(); pulses = 0; target = compensatedTarget; lastPulseUs = micros(); running = false; targetReached = false; interrupts();
  stopReason = StopReason::None; stopSequenceComplete = false; noFlowWarning = false;
  commandSolenoid(true); actuatorState = ActuatorState::OpeningSolenoid;
}
void beginStopSequence(StopReason reason) {
  if (actuatorState == ActuatorState::Safe || actuatorIsBooting() || actuatorState == ActuatorState::StopWaitPumpPulse || actuatorState == ActuatorState::PumpStopping || actuatorState == ActuatorState::StoppingDelay || actuatorState == ActuatorState::ClosingSolenoid) return;
  noInterrupts(); running = false; interrupts();
  stopReason = reason;
  // Jangan memberi RST pada pompa selama pulsa SET-nya masih aktif.
  actuatorState = ActuatorState::StopWaitPumpPulse;
}
void serviceActuators(uint32_t now) {
  switch (actuatorState) {
    case ActuatorState::BootWait:
      if (now - actuatorAt >= kBootResetDelayMs) { commandSolenoid(false); actuatorState = ActuatorState::BootResetSolenoid; }
      break;
    case ActuatorState::BootResetSolenoid:
      if (!relay1PulseActive) { commandPump(false); actuatorState = ActuatorState::BootResetPump; }
      break;
    case ActuatorState::BootResetPump:
      if (!relay2PulseActive) { actuatorState = ActuatorState::Safe; logPrefix(); logger.println("INTERLOCK SIAP"); }
      break;
    case ActuatorState::OpeningSolenoid:
      if (!relay1PulseActive) { actuatorAt = now; actuatorState = ActuatorState::OpeningDelay; }
      break;
    case ActuatorState::OpeningDelay:
      if (now - actuatorAt >= kSolenoidSettleMs) { commandPump(true); actuatorState = ActuatorState::PumpStarting; }
      break;
    case ActuatorState::PumpStarting:
      if (!relay2PulseActive) { noInterrupts(); running = true; lastPulseUs = micros(); interrupts(); actuatorState = ActuatorState::PumpRunning; logPrefix(); logger.println("AIR MULAI"); }
      break;
    case ActuatorState::StopWaitPumpPulse:
      if (!relay2PulseActive) { commandPump(false); actuatorState = ActuatorState::PumpStopping; }
      break;
    case ActuatorState::PumpStopping:
      if (!relay2PulseActive) { actuatorAt = now; actuatorState = ActuatorState::StoppingDelay; }
      break;
    case ActuatorState::StoppingDelay:
      if (now - actuatorAt >= kPumpStopSettleMs) { commandSolenoid(false); actuatorState = ActuatorState::ClosingSolenoid; }
      break;
    case ActuatorState::ClosingSolenoid:
      if (!relay1PulseActive) { actuatorState = ActuatorState::Safe; stopSequenceComplete = true; logPrefix(); logger.println("AIR BERHENTI: INTERLOCK AMAN"); }
      break;
    case ActuatorState::Safe:
    case ActuatorState::PumpRunning:
      break;
  }
}

void showClockEdit() {
  const char *label = clockField == 0 ? "TAHUN" : clockField == 1 ? "BULAN" : clockField == 2 ? "TANGGAL" : clockField == 3 ? "JAM" : "MENIT";
  unsigned value = clockField == 0 ? editTime.year : clockField == 1 ? editTime.month : clockField == 2 ? editTime.day : clockField == 3 ? editTime.hour : editTime.minute;
  char l[17], b[17]; std::snprintf(l, sizeof(l), "SET %s: %u", label, value); std::snprintf(b, sizeof(b), "P1+ P2> P3 OK"); lcdShow(l, b);
}
void bumpClockField() { if (clockField == 0) editTime.year = editTime.year >= 2099 ? 2026 : editTime.year + 1; else if (clockField == 1) editTime.month = editTime.month == 12 ? 1 : editTime.month + 1; else if (clockField == 2) editTime.day = editTime.day == 31 ? 1 : editTime.day + 1; else if (clockField == 3) editTime.hour = editTime.hour == 23 ? 0 : editTime.hour + 1; else editTime.minute = editTime.minute == 59 ? 0 : editTime.minute + 1; }

void setup() {
  pinMode(kLedPin, OUTPUT); digitalWrite(kLedPin, kLedActiveLow ? HIGH : LOW); pinMode(kIndicatorPb0Pin, OUTPUT); pinMode(kIndicatorPb1Pin, OUTPUT); digitalWrite(kIndicatorPb0Pin, HIGH); digitalWrite(kIndicatorPb1Pin, HIGH);
  pinMode(kButtonP1Pin, INPUT_PULLUP); pinMode(kButtonP2Pin, INPUT_PULLUP); pinMode(kButtonP3Pin, INPUT_PULLUP);
  pinMode(kRelay1SetPin, OUTPUT); pinMode(kRelay1ResetPin, OUTPUT); pinMode(kRelay2SetPin, OUTPUT); pinMode(kRelay2ResetPin, OUTPUT); digitalWrite(kRelay1SetPin, LOW); digitalWrite(kRelay1ResetPin, LOW); digitalWrite(kRelay2SetPin, LOW); digitalWrite(kRelay2ResetPin, LOW);
  logger.begin(115200); Wire.setSDA(kI2cSdaPin); Wire.setSCL(kI2cSclPin); Wire.begin(); Wire.setClock(100000);
  Wire.beginTransmission(kLcdI2cAddress); if (Wire.endTransmission() == 0) { lcd.begin(16, 2, Wire); lcdReady = lcd.isConnected(); lcd.setBacklight(255); }
  nfc.begin(); nfc.setPassiveActivationRetries(0x19); nfc.SAMConfig(); loadMaster();
  coilTimer.setOverflow(1000, HERTZ_FORMAT); coilTimer.attachInterrupt(coilTick); coilTimer.resume(); pinMode(kFlowPin, INPUT_PULLUP); attachInterrupt(digitalPinToInterrupt(kFlowPin), onFlow, FALLING);
  actuatorAt = millis(); actuatorState = ActuatorState::BootWait;
  logPrefix(); logger.println("DISPENSER: BOOT INTERLOCK"); lcdShow("DISPENSER", "MENYIAPKAN");
}
void loop() {
  const uint32_t now = millis();
  serviceActuators(now);
  if (actuatorIsBooting()) { lcdShow("DISPENSER", "MENYIAPKAN"); return; }
  const bool p1 = keyP1.update(digitalRead(kButtonP1Pin) == LOW, now), p2 = keyP2.update(digitalRead(kButtonP2Pin) == LOW, now), p3 = keyP3.update(digitalRead(kButtonP3Pin) == LOW, now);
  if (page == Page::ClockEdit) { if (p1) bumpClockField(); if (p2) clockField = static_cast<uint8_t>((clockField + 1) % 5); if (p3) { if (rtcWrite(editTime)) { lcdShow("JAM TERSIMPAN", ""); page = Page::Done; pageAt = now; } else { lcdShow("RTC GAGAL TULIS", "CEK DS3231"); page = Page::Rejected; pageAt = now; } } if (page == Page::ClockEdit) showClockEdit(); return; }
  if (page == Page::Dispensing) {
    noInterrupts(); const uint32_t count = pulses; const bool stillRunning = running; const uint32_t lastFlow = lastPulseUs; const bool reachedTarget = targetReached; interrupts();
    if (p2) beginStopSequence(StopReason::UserStop);
    if (reachedTarget) beginStopSequence(StopReason::TargetReached);
    if (stopReason == StopReason::None && now - presenceAt >= 500) {
      presenceAt = now; uint8_t seen[7]{}; uint8_t seenLen = 0;
      if (!(nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, seen, &seenLen) && seenLen == 4 && std::memcmp(seen, boundUid, 4) == 0)) beginStopSequence(StopReason::CardLost);
    }
    // Tidak ada flow bukan alasan untuk mematikan proses otomatis. Operator
    // dapat mengecek jalur air/pompa, lalu memilih P2 untuk berhenti manual.
    if (stillRunning && static_cast<uint32_t>(micros() - lastFlow) >= 5000000) noFlowWarning = true;
    if (stopSequenceComplete) {
      const uint8_t actualLitres = static_cast<uint8_t>(min(
        (count + kPulsesPerLitre - 1) / kPulsesPerLitre,
        static_cast<uint32_t>(selectedLitres)));
      bool settled = false;
      Wallet settledWallet{};
      smartdispenser::compact_card::Metadata settledMetadata{};
      if (stopReason != StopReason::CardLost &&
          readWallet(boundUid, settledWallet, &settledMetadata) == WalletRead::Ok &&
          (!transactionUsesCardReserve || settledWallet.reserved == selectedLitres) &&
          static_cast<uint16_t>(settledWallet.available) + selectedLitres <= smartdispenser::compact_card::kMaximumBalanceLitres &&
          static_cast<uint16_t>(settledWallet.usedToday) + actualLitres <= kDailyQuotaLitres) {
        settledWallet.available = static_cast<uint8_t>(settledWallet.available + selectedLitres - actualLitres);
        settledWallet.usedToday = static_cast<uint8_t>(settledWallet.usedToday + actualLitres);
        if (transactionUsesCardReserve) settledWallet.reserved = 0;
        settled = writeWallet(boundUid, settledWallet, settledMetadata);
      }
      if (settled) {
        clearPendingSettlement();
        lcdShow("SELESAI", "SALDO DIPERBARUI");
        emitTransactionEvent("completed", transactionCardReference, transactionSchedule,
                             selectedLitres, actualLitres, settledWallet.available,
                             settledMetadata.transactionCounter + 1, "flow_settled");
      } else {
        savePendingSettlement(transactionCardReference, selectedLitres, actualLitres, transactionSchedule, transactionUsesCardReserve);
        lcdShow("BERHENTI", "CADANGAN BEKU");
        emitTransactionEvent("pending", transactionCardReference, transactionSchedule,
                             selectedLitres, actualLitres, 0, 0,
                             stopReason == StopReason::CardLost ? "card_removed" : "settlement_failed");
      }
      page = Page::Done; pageAt = now; digitalWrite(kIndicatorPb0Pin, HIGH); return;
    }
    if (actuatorState != ActuatorState::PumpRunning) lcdShow(stopReason == StopReason::None ? "MENYIAPKAN AIR" : "MENGHENTIKAN", stopReason == StopReason::None ? "TUNGGU POMPA" : "TUNGGU AMAN");
    else if (noFlowWarning) lcdShow("TIDAK ADA FLOW", "P2 = STOP");
    else {
      const uint8_t shownDone = static_cast<uint8_t>(min(count / kPulsesPerLitre, 99UL));
      // Target pulsa boleh dikompensasi untuk inersia aliran, tetapi angka
      // tujuan yang terlihat operator tetap pilihan 1/2/3 liter.
      const uint8_t shownTarget = selectedLitres;
      char l[17]; std::snprintf(l, sizeof(l), "%u/%u L", static_cast<unsigned>(shownDone), static_cast<unsigned>(shownTarget)); lcdShow("MENYALURKAN", l);
    }
    return;
  }
  if (page == Page::Done || page == Page::Rejected) { if (now - pageAt >= 2000) page = Page::Idle; else return; }

  uint8_t uid[7]{}; uint8_t uidLen = 0; const bool present = nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &uidLen) && uidLen == 4;
  if (!present) {
    if (cardTraceStage != 0 && transactionCardReference != 0) emitCardEvent("removed", transactionCardReference);
    cardTraceStage = 0; transactionCardReference = 0; masterHolding = false; page = Page::Idle; lcdShow("DISPENSER A", "TEMPEL KARTU"); return;
  }
  if (cardTraceStage == 0) { logPrefix(); logger.println("NFC: KARTU TERLIHAT"); cardTraceStage = 1; }
  const bool bothHeld = keyP1.stable && keyP3.stable && !keyP2.stable;
  if (!masterSet && bothHeld) { if (!masterHolding || std::memcmp(uid, heldMasterUid, 4) != 0) { masterHolding = true; masterHoldAt = now; std::memcpy(heldMasterUid, uid, 4); } else if (now - masterHoldAt >= 10000) { saveMaster(uid); masterHolding = false; lcdShow("MASTER TERSIMPAN", ""); } else { char l[17]; std::snprintf(l, sizeof(l), "TAHAN %lu/10", static_cast<unsigned long>((now-masterHoldAt)/1000)); lcdShow("DAFTAR MASTER", l); } return; }
  if (!bothHeld) masterHolding = false;
  if (masterSet && std::memcmp(uid, masterUid, 4) == 0) {
    if (kUseRtc && p1) { if (!rtcRead(editTime)) editTime = RtcTime{}; clockField = 0; page = Page::ClockEdit; showClockEdit(); }
    else lcdShow("MASTER", kUseRtc ? "P1=SET JAM" : "RTC NONAKTIF");
    return;
  }

  if (cardTraceStage == 1) { logPrefix(); logger.println("NFC: MULAI BACA WALLET"); cardTraceStage = 2; }
  Wallet w{}; smartdispenser::compact_card::Metadata metadata{}; const WalletRead result = readWallet(uid, w, &metadata);
  if (cardTraceStage == 2) { logPrefix(); logger.print("NFC: HASIL WALLET="); logger.println(static_cast<unsigned>(result)); cardTraceStage = 3; }
  if (result == WalletRead::Legacy) { lcdShow("KARTU LAMA", "UPGRADE TOPUP"); return; }
  if (result != WalletRead::Ok) { page = Page::Rejected; pageAt = now; lcdShow("PERLU PEMERIKSAAN", "KARTU DITOLAK"); return; }
  PendingSettlement pending = loadPendingSettlement();
  if (pending.valid && pending.reference == metadata.cardReference && pending.usesCardReserve && w.reserved == 0) {
    clearPendingSettlement();  // Settlement already committed; only EEPROM cleanup was interrupted.
    pending.valid = false;
  }
  if (pending.valid && pending.reference == metadata.cardReference &&
      (!pending.usesCardReserve || pending.requested == w.reserved) &&
        static_cast<uint16_t>(w.available) + pending.requested <= smartdispenser::compact_card::kMaximumBalanceLitres &&
        static_cast<uint16_t>(w.usedToday) + pending.actual <= kDailyQuotaLitres) {
      Wallet recovered = w;
      recovered.available = static_cast<uint8_t>(w.available + pending.requested - pending.actual);
      recovered.usedToday = static_cast<uint8_t>(w.usedToday + pending.actual);
      if (pending.usesCardReserve) recovered.reserved = 0;
      if (writeWallet(uid, recovered, metadata)) {
        clearPendingSettlement();
        emitTransactionEvent("completed", metadata.cardReference, pending.schedule,
                             pending.requested, pending.actual, recovered.available,
                             metadata.transactionCounter + 1, "recovered_after_card_return");
        lcdShow("TRANSAKSI PULIH", "SALDO DIPERBARUI");
        page = Page::Done; pageAt = now;
        return;
      }
  }
  // Cadangan adalah nilai terpisah dari saldo aktif. Bila bukan transaksi
  // lokal yang masih bisa dipulihkan, kartu tetap boleh memakai saldo aktif.
  // Nilai cadangan dipertahankan dan tidak dipakai sebagai kuota pengambilan.
  if (w.reserved != 0 && cardTraceStage < 6) {
    char l[17]; std::snprintf(l, sizeof(l), "CADANGAN %u L", w.reserved);
    logPrefix(); logger.print("CADANGAN DIPERTAHANKAN: "); logger.println(l);
    emitTransactionEvent("pending", metadata.cardReference, w.schedule,
                         w.reserved, pending.valid ? pending.actual : 0,
                         w.available, metadata.transactionCounter,
                         pending.valid ? "active_balance_still_usable" : "external_reserve_active_balance_usable");
    cardTraceStage = 6;
  }
  if (!w.permitted) { lcdShow("KARTU NONAKTIF", ""); return; }
  uint8_t allowed = w.available;
  if (kUseRtc) {
    if (cardTraceStage == 3) { logPrefix(); logger.println("RTC: MULAI BACA"); cardTraceStage = 4; }
    RtcTime clock{}; const bool rtcOk = rtcRead(clock);
    if (cardTraceStage == 4) { logPrefix(); logger.println(rtcOk ? "RTC: BACA OK" : "RTC: BACA GAGAL"); cardTraceStage = 5; }
    if (!rtcOk) { lcdShow("RTC BELUM SIAP", "ATUR WAKTU RTC"); return; }
    const uint16_t today = dayId(clock); if (w.day != today) { w.day = today; w.usedToday = 0; }
    const uint8_t activeSchedule = scheduleForHour(clock.hour);
    if (w.schedule == kScheduleNone || w.schedule != activeSchedule) { char l[17]; std::snprintf(l, sizeof(l), "SEKARANG %s", scheduleName(activeSchedule)); lcdShow("LUAR JADWAL", l); return; }
    if (w.usedToday >= kDailyQuotaLitres) { lcdShow("KUOTA HARI INI", "SUDAH HABIS"); return; }
    allowed = min(w.available, static_cast<uint8_t>(kDailyQuotaLitres - w.usedToday));
  }
  if (w.available == 0) { lcdShow("SALDO HABIS", ""); return; }
  // Pilihan pengambilan: P1=10 L, P2=20 L, P3=30 L.
  // Tombol yang nilainya melebihi saldo aktif/kuota hari ini tidak diproses.
  const uint8_t opt1 = allowed < 10 ? allowed : 10, opt2 = allowed >= 20 ? 20 : 0, opt3 = allowed >= 30 ? 30 : 0;
  if (page != Page::Menu || std::memcmp(uid, boundUid, 4) != 0) {
    page = Page::Menu; std::memcpy(boundUid, uid, 4);
    transactionCardReference = metadata.cardReference;
    emitCardEvent("detected", transactionCardReference, &w);
  }
  uint8_t chosen = 0; if (p1 && opt1) chosen = opt1; else if (p2 && opt2) chosen = opt2; else if (p3 && opt3) chosen = opt3;
  if (chosen) {
    Wallet reserved = w;
    reserved.available = static_cast<uint8_t>(w.available - chosen);
    // Jika kartu sudah mempunyai cadangan, jangan menimpanya. Transaksi baru
    // dicatat di jurnal EEPROM dan tetap mengurangi saldo aktif secara aman.
    transactionUsesCardReserve = w.reserved == 0;
    if (transactionUsesCardReserve) reserved.reserved = chosen;
    if (!writeWallet(uid, reserved, metadata)) { page = Page::Rejected; pageAt = now; lcdShow("GAGAL CADANGKAN", "AIR TIDAK MULAI"); return; }
    transactionSchedule = w.schedule;
    transactionCardReference = metadata.cardReference;
    emitTransactionEvent("reserved", transactionCardReference, transactionSchedule,
                         chosen, 0, reserved.available, metadata.transactionCounter + 1, "awaiting_flow");
    selectedLitres = chosen; presenceAt = now; beginDispenseActuation(chosen); page = Page::Dispensing; lcdShow("MENYIAPKAN AIR", "BUKA SOLENOID"); return;
  }
  char l1[17], l2[17];
  std::snprintf(l1, sizeof(l1), "S:%u K:%u/%u", static_cast<unsigned>(w.available), static_cast<unsigned>(w.usedToday), static_cast<unsigned>(kDailyQuotaLitres));
  std::snprintf(l2, sizeof(l2), "1:%02u 2:%02u 3:%02u", static_cast<unsigned>(opt1), static_cast<unsigned>(opt2), static_cast<unsigned>(opt3));
  lcdShow(l1, l2);
}
