// SmartDispenser Perso ESP32: ESP32 DevKit + PN532 I2C.
// Serial USB adalah bridge aplikasi, bukan console perintah NFC mentah.

#include <Arduino.h>
#include <EEPROM.h>
#include <PN532.h>
#if defined(PERSO_NFC_SPI)
#include <PN532_SPI.h>
#include <SPI.h>
#else
#include <PN532_I2C.h>
#include <Wire.h>
#endif
#include <cstdio>
#include <cstring>

constexpr uint8_t kSdaPin = 21;
constexpr uint8_t kSclPin = 22;
constexpr uint8_t kNfcI2cAddress = 0x24;
constexpr uint8_t kNfcSpiSckPin = 18;
constexpr uint8_t kNfcSpiMisoPin = 19;
constexpr uint8_t kNfcSpiMosiPin = 23;
constexpr uint8_t kNfcSpiCsPin = 5;
// Temporary hardware diagnostic. This prevents a non-responsive NFC sensor
// from blocking the firmware before the I2C scan can be reported.
constexpr bool kI2cDiagnosticOnly = false;
constexpr uint32_t kBaudRate = 115200;
constexpr uint8_t kWalletBlock = 8;
constexpr uint8_t kTrailerBlock = 11;
constexpr uint8_t kMagic = 0xD7;
constexpr uint8_t kVersion = 2;
constexpr uint8_t kMasterFlag = 0xA5;
constexpr uint32_t kPollMs = 100;
// The library default is 1000 ms. That made a nominal 100 ms scan loop feel
// one second late whenever no card was present. This short timeout is used
// only for presence polling; card read/write operations keep their normal
// timeout.
constexpr uint16_t kPresenceReadTimeoutMs = 60;
// SPI reader/card coupling can briefly drop during a multi-step check.  Keep
// a card present across a short dropout; a real removal still clears within
// well under a second.
constexpr uint32_t kAbsentGraceMs = 650;

uint8_t kKeyA[6] = {0x11, 0x22, 0x33, 0x44, 0x55, 0x66};
uint8_t kKeyB[6] = {0x66, 0x55, 0x44, 0x33, 0x22, 0x11};
uint8_t kFactoryKeys[][6] = {
    {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF},
    {0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5},
    {0xD3, 0xF7, 0xD3, 0xF7, 0xD3, 0xF7},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
};
constexpr uint8_t kFactoryKeyCount = sizeof(kFactoryKeys) / sizeof(kFactoryKeys[0]);

#if defined(PERSO_NFC_SPI)
PN532_SPI pn532spi(SPI, kNfcSpiCsPin);
PN532 nfc(pn532spi);
#else
PN532_I2C pn532i2c(Wire);
PN532 nfc(pn532i2c);
#endif
bool nfcReady = false;
const char *nfcInitState = "not_started";
uint32_t lastNfcInit = 0;
bool masterSet = false;
bool sessionOpen = false;
bool requireMasterRemoval = false;
uint8_t masterUid[4] = {};

enum class Operation { Idle, EnrollMaster, ResetMaster, ArmPerso, ReviewPerso };
enum class CardState { None, Blank, Existing, Foreign };
Operation operation = Operation::Idle;
CardState cardState = CardState::None;
uint8_t cardUid[4] = {};
uint8_t removalUid[4] = {};
bool cardPresent = false;
bool cardReady = false;
bool awaitingRemoval = false;
bool removalNoticeSent = false;
uint32_t cardSince = 0;
uint32_t operationSince = 0;
uint32_t lastCardSeen = 0;
uint32_t lastPoll = 0;
uint32_t cardSession = 0;

void resetCard();

uint8_t rxHeader[2] = {};
uint8_t rxSyncUsed = 0;
uint8_t rxHeaderUsed = 0;
uint16_t rxExpected = 0;
uint16_t rxUsed = 0;
char rxPayload[257] = {};

const char *operationName() {
  switch (operation) {
    case Operation::EnrollMaster: return "master_enroll";
    case Operation::ResetMaster: return "master_reset";
    case Operation::ArmPerso: return "perso_armed";
    case Operation::ReviewPerso: return "perso_review";
    default: return "idle";
  }
}

void emit(const char *type, const char *code) {
  char json[250] = {};
  std::snprintf(json, sizeof(json), "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"type\":\"%s\",\"code\":\"%s\",\"nfc_ready\":%s,\"master_registered\":%s,\"session_open\":%s,\"operation\":\"%s\",\"card_session\":%lu}",
                type, code, nfcReady ? "true" : "false", masterSet ? "true" : "false", sessionOpen ? "true" : "false", operationName(), static_cast<unsigned long>(cardSession));
  const size_t count = strnlen(json, 250);
  const uint8_t prefix[] = {static_cast<uint8_t>(count >> 8u), static_cast<uint8_t>(count)};
  Serial.write(prefix, sizeof(prefix));
  Serial.write(reinterpret_cast<const uint8_t *>(json), count);
}

// Technician-only, read-only map. Keys and sector-trailer bytes are never
// serialized to USB. Block 0 is also masked because it contains the card UID.
void emitTechnicalBlock(uint8_t block, const char *state, const uint8_t *data) {
  const uint8_t sector = block / 4;
  const bool trailer = (block % 4) == 3;
  const bool manufacturer = block == 0;
  char hex[33] = {};
  if (data && !trailer && !manufacturer) {
    for (uint8_t index = 0; index < 16; ++index) {
      std::snprintf(hex + (index * 2), 3, "%02X", data[index]);
    }
  }
  const char *kind = trailer ? "trailer_protected" : (manufacturer ? "manufacturer_masked" : "data");
  char json[250] = {};
  std::snprintf(json, sizeof(json),
                "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"type\":\"technical\",\"code\":\"scan_block\",\"sector\":%u,\"block\":%u,\"kind\":\"%s\",\"state\":\"%s\",\"data\":\"%s\"}",
                sector, block, kind, state, hex);
  const size_t count = strnlen(json, sizeof(json));
  const uint8_t prefix[] = {static_cast<uint8_t>(count >> 8u), static_cast<uint8_t>(count)};
  Serial.write(prefix, sizeof(prefix));
  Serial.write(reinterpret_cast<const uint8_t *>(json), count);
}

void emitTechnicalStatus(const char *code) {
  char json[180] = {};
  std::snprintf(json, sizeof(json),
                "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"type\":\"technical\",\"code\":\"%s\",\"nfc_ready\":%s,\"session_open\":%s}",
                code, nfcReady ? "true" : "false", sessionOpen ? "true" : "false");
  const size_t count = strnlen(json, sizeof(json));
  const uint8_t prefix[] = {static_cast<uint8_t>(count >> 8u), static_cast<uint8_t>(count)};
  Serial.write(prefix, sizeof(prefix));
  Serial.write(reinterpret_cast<const uint8_t *>(json), count);
}

// Read-only preflight for the one fixed wallet location.  This tells the
// desktop whether Block 8 is blank and writable with an approved factory key;
// it never writes card data, keys, or a sector trailer.
void emitWalletSlot(CardState state) {
  const char *slotState = state == CardState::Blank ? "ready" :
                          state == CardState::Existing ? "already_used" : "unavailable";
  char json[200] = {};
  std::snprintf(json, sizeof(json),
                "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"type\":\"technical\",\"code\":\"wallet_slot\",\"state\":\"%s\",\"sector\":%u,\"block\":%u}",
                slotState, kWalletBlock / 4, kWalletBlock);
  const size_t count = strnlen(json, sizeof(json));
  const uint8_t prefix[] = {static_cast<uint8_t>(count >> 8u), static_cast<uint8_t>(count)};
  Serial.write(prefix, sizeof(prefix));
  Serial.write(reinterpret_cast<const uint8_t *>(json), count);
}

// A scan can be read-only yet still be unreliable if the card leaves the
// field mid-scan. Report that separately from access rights: an unknown key
// is not a stability failure.
void emitTechnicalQuality(bool stable) {
  char json[180] = {};
  std::snprintf(json, sizeof(json),
                "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"type\":\"technical\",\"code\":\"scan_quality\",\"stable\":%s}",
                stable ? "true" : "false");
  const size_t count = strnlen(json, sizeof(json));
  const uint8_t prefix[] = {static_cast<uint8_t>(count >> 8u), static_cast<uint8_t>(count)};
  Serial.write(prefix, sizeof(prefix));
  Serial.write(reinterpret_cast<const uint8_t *>(json), count);
}

void emitCardQuality(uint8_t success, uint8_t attempts, uint16_t averageMs, const char *source) {
  char json[200] = {};
  std::snprintf(json, sizeof(json),
                "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"type\":\"technical\",\"code\":\"card_quality\",\"success\":%u,\"attempts\":%u,\"average_ms\":%u,\"source\":\"%s\"}",
                success, attempts, averageMs, source);
  const size_t count = strnlen(json, sizeof(json));
  const uint8_t prefix[] = {static_cast<uint8_t>(count >> 8u), static_cast<uint8_t>(count)};
  Serial.write(prefix, sizeof(prefix));
  Serial.write(reinterpret_cast<const uint8_t *>(json), count);
}

void emitCardQualityAttempt(uint8_t attempt, bool passed, const char *source) {
  char json[180] = {};
  std::snprintf(json, sizeof(json),
                "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"type\":\"technical\",\"code\":\"quality_attempt\",\"attempt\":%u,\"passed\":%s,\"source\":\"%s\"}",
                attempt, passed ? "true" : "false", source);
  const size_t count = strnlen(json, sizeof(json));
  const uint8_t prefix[] = {static_cast<uint8_t>(count >> 8u), static_cast<uint8_t>(count)};
  Serial.write(prefix, sizeof(prefix));
  Serial.write(reinterpret_cast<const uint8_t *>(json), count);
}

void emitNfcInitDiagnostic() {
  char json[180] = {};
  std::snprintf(json, sizeof(json),
                "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"type\":\"diagnostic\",\"code\":\"nfc_init\",\"state\":\"%s\"}",
                nfcInitState);
  const size_t count = strnlen(json, sizeof(json));
  const uint8_t prefix[] = {static_cast<uint8_t>(count >> 8u), static_cast<uint8_t>(count)};
  Serial.write(prefix, sizeof(prefix));
  Serial.write(reinterpret_cast<const uint8_t *>(json), count);
}

// Diagnostic only: this exposes neither card content nor keys. It confirms
// whether the ESP32 can see an I2C responder at the NFC sensor address.
void emitI2cDiagnostic() {
#if !defined(PERSO_NFC_SPI)
  uint8_t deviceCount = 0;
  bool sensorAck = false;
  for (uint8_t address = 0x08; address < 0x78; ++address) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      ++deviceCount;
      if (address == kNfcI2cAddress) sensorAck = true;
    }
  }
  char json[250] = {};
  std::snprintf(json, sizeof(json),
                "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"type\":\"diagnostic\",\"code\":\"i2c_scan\",\"nfc_ready\":%s,\"sensor_i2c_ack\":%s,\"i2c_device_count\":%u}",
                nfcReady ? "true" : "false", sensorAck ? "true" : "false", deviceCount);
  const size_t count = strnlen(json, sizeof(json));
  const uint8_t prefix[] = {static_cast<uint8_t>(count >> 8u), static_cast<uint8_t>(count)};
  Serial.write(prefix, sizeof(prefix));
  Serial.write(reinterpret_cast<const uint8_t *>(json), count);
#endif
}

// Unlike an I2C transaction, reading the two pins cannot block when a sensor
// or wire holds the bus. This is the first physical-health diagnostic.
void emitI2cLineDiagnostic() {
  const bool sdaHigh = digitalRead(kSdaPin) == HIGH;
  const bool sclHigh = digitalRead(kSclPin) == HIGH;
  char json[250] = {};
  std::snprintf(json, sizeof(json),
                "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"type\":\"diagnostic\",\"code\":\"i2c_line_levels\",\"sda_high\":%s,\"scl_high\":%s}",
                sdaHigh ? "true" : "false", sclHigh ? "true" : "false");
  const size_t count = strnlen(json, sizeof(json));
  const uint8_t prefix[] = {static_cast<uint8_t>(count >> 8u), static_cast<uint8_t>(count)};
  Serial.write(prefix, sizeof(prefix));
  Serial.write(reinterpret_cast<const uint8_t *>(json), count);
}

uint16_t crc16(const uint8_t *data, size_t size) {
  uint16_t value = 0xFFFF;
  for (size_t i = 0; i < size; ++i) {
    value ^= static_cast<uint16_t>(data[i]) << 8u;
    for (uint8_t bit = 0; bit < 8; ++bit) value = (value & 0x8000u) ? static_cast<uint16_t>((value << 1u) ^ 0x1021u) : static_cast<uint16_t>(value << 1u);
  }
  return value;
}

void wallet(uint8_t data[16]) {
  std::memset(data, 0, 16);
  data[0] = kMagic;
  data[1] = kVersion;
  data[2] = 1;  // status aktif
  const uint16_t check = crc16(data, 9);
  data[9] = static_cast<uint8_t>(check >> 8u);
  data[10] = static_cast<uint8_t>(check);
}

void loadMaster() {
  masterSet = EEPROM.read(0) == kMasterFlag;
  for (uint8_t i = 0; i < 4; ++i) masterUid[i] = EEPROM.read(1 + i);
}

void saveMaster(const uint8_t uid[4]) {
  for (uint8_t i = 0; i < 4; ++i) EEPROM.write(1 + i, uid[i]);
  EEPROM.write(0, kMasterFlag);
  EEPROM.commit();
  masterSet = true;
  std::memcpy(masterUid, uid, 4);
}

bool initNfc() {
  nfc.begin();
  delay(50);
#if defined(PERSO_NFC_SPI)
  if (nfc.getFirmwareVersion() == 0) {
    nfcInitState = "spi_firmware_query_failed";
    lastNfcInit = millis();
    return false;
  }
  // This particular SPI reader accepts its firmware query but rejects the
  // library SAM command. Its working mode is the module's default passive
  // reader mode, verified by live card detection during the earlier test.
  nfcInitState = "spi_default_reader";
  lastNfcInit = millis();
  return true;
#endif
#if !defined(PERSO_NFC_SPI)
  if (!nfc.setPassiveActivationRetries(0x19)) {
    nfcInitState = "retry_config_failed";
    lastNfcInit = millis();
    return false;
  }
#endif
  delay(20);
  lastNfcInit = millis();
  if (!nfc.SAMConfig()) {
    nfcInitState = "reader_config_failed";
    return false;
  }
  nfcInitState = "ready";
  return true;
}

bool reselect(uint8_t uid[4]) {
  uint8_t fresh[7] = {};
  uint8_t length = 0;
  if (!nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, fresh, &length, 250) || length != 4) return false;
  std::memcpy(uid, fresh, 4);
  return true;
}

bool blank(const uint8_t data[16]) {
  bool zeros = true;
  bool erased = true;
  for (uint8_t i = 0; i < 16; ++i) { zeros = zeros && data[i] == 0; erased = erased && data[i] == 0xFF; }
  return zeros || erased;
}

int8_t authenticateFactory(uint8_t uid[4], uint8_t block) {
  for (uint8_t i = 0; i < kFactoryKeyCount; ++i) {
    if (!reselect(uid)) return -1;
    uint8_t key[6]; std::memcpy(key, kFactoryKeys[i], 6);
    if (nfc.mifareclassic_AuthenticateBlock(uid, 4, block, 0, key)) return static_cast<int8_t>(i);
  }
  return -1;
}

bool authenticateDiagnosticSector(uint8_t uid[4], uint8_t block) {
  // One authentication grants read access to every data block in its sector.
  // The scan uses only the normal factory key and the known wallet key: it is
  // not a brute-force key search.
  if ((block / 4) == (kWalletBlock / 4)) {
    uint8_t key[6]; std::memcpy(key, kKeyA, 6);
    return reselect(uid) && nfc.mifareclassic_AuthenticateBlock(uid, 4, block, 0, key);
  }
  uint8_t key[6]; std::memcpy(key, kFactoryKeys[0], 6);
  return reselect(uid) && nfc.mifareclassic_AuthenticateBlock(uid, 4, block, 0, key);
}

void cardQualityTest(const char *source = "auto");
CardState probe(uint8_t uid[4]);

void reportCardRemovedDuringTest() {
  if (cardPresent) emit("card", "removed");
  resetCard();
}

void technicalScan() {
  if (!sessionOpen) { emit("error", "master_session_required"); return; }
  if (operation != Operation::Idle || !cardPresent) { emit("error", "technical_scan_card_required"); return; }
  uint8_t uid[4] = {}; std::memcpy(uid, cardUid, 4);
  if (!reselect(uid)) { emit("error", "technical_scan_card_lost"); return; }
  emitTechnicalStatus("scan_started");
  bool stable = true;
  bool cardLost = false;
  for (uint8_t sector = 0; sector < 16; ++sector) {
    const uint8_t firstBlock = sector * 4;
    // Probe presence at every sector boundary. The following authentication
    // may still fail because the key is unknown; that does not mark the card
    // unstable.
    const bool presentAtSector = reselect(uid);
    if (!presentAtSector) {
      stable = false;
      cardLost = true;
      break;
    }
    const bool authenticated = presentAtSector && authenticateDiagnosticSector(uid, firstBlock);
    for (uint8_t offset = 0; offset < 4; ++offset) {
      const uint8_t block = firstBlock + offset;
      if (offset == 3) { emitTechnicalBlock(block, "protected", nullptr); continue; }
      if (block == 0) { emitTechnicalBlock(block, "masked", nullptr); continue; }
      uint8_t data[16] = {};
      const bool readOk = authenticated && nfc.mifareclassic_ReadDataBlock(block, data);
      emitTechnicalBlock(block, readOk ? "read_ok" : "no_authorized_read", readOk ? data : nullptr);
    }
  }
  if (!cardLost && !reselect(uid)) {
    stable = false;
    cardLost = true;
  }
  if (cardLost) reportCardRemovedDuringTest();
  emitTechnicalQuality(stable);
  emitTechnicalStatus("scan_complete");
  // Every technical card scan also receives the same ten-read quality check.
  if (!cardLost) cardQualityTest();
}

// A bounded read-reliability test. It neither authenticates, reads, nor writes
// a card block, and sends no UID to the desktop app.
void cardQualityTest(const char *source) {
  if (!sessionOpen) { emit("error", "master_session_required"); return; }
  if (operation != Operation::Idle || !cardPresent) { emit("error", "card_quality_card_required"); return; }
  constexpr uint8_t attempts = 10;
  uint8_t uid[4] = {}; std::memcpy(uid, cardUid, 4);
  uint8_t success = 0;
  uint32_t elapsedTotal = 0;
  emitTechnicalStatus("quality_started");
  for (uint8_t attempt = 0; attempt < attempts; ++attempt) {
    const uint32_t started = millis();
    const bool selected = reselect(uid);
    elapsedTotal += millis() - started;
    if (selected) ++success;
    emitCardQualityAttempt(attempt + 1, selected, source);
    if (!selected) {
      reportCardRemovedDuringTest();
      emitCardQuality(success, attempt + 1, static_cast<uint16_t>(elapsedTotal / (attempt + 1)), source);
      return;
    }
    delay(70);
  }
  emitCardQuality(success, attempts, static_cast<uint16_t>(elapsedTotal / attempts), source);
  // Only a perfect automatic quality result may advance to the wallet-slot
  // preflight. This remains read-only; the app still requires confirmation
  // before personalization can write anything.
  if (std::strcmp(source, "auto") == 0 && success == attempts && cardPresent) {
    uint8_t slotUid[4] = {};
    std::memcpy(slotUid, cardUid, 4);
    if (reselect(slotUid)) emitWalletSlot(probe(slotUid));
    else reportCardRemovedDuringTest();
  }
}

CardState probe(uint8_t uid[4]) {
  uint8_t key[6]; std::memcpy(key, kKeyA, 6);
  if (nfc.mifareclassic_AuthenticateBlock(uid, 4, kWalletBlock, 0, key)) return CardState::Existing;
  if (authenticateFactory(uid, kWalletBlock) < 0) return CardState::Foreign;
  uint8_t data[16] = {};
  return nfc.mifareclassic_ReadDataBlock(kWalletBlock, data) && blank(data) ? CardState::Blank : CardState::Foreign;
}

bool writeBlock(uint8_t uid[4], uint8_t block, const uint8_t key[6], uint8_t data[16]) {
  for (uint8_t attempt = 0; attempt < 3; ++attempt) {
    if (attempt > 0 && !reselect(uid)) return false;
    uint8_t authKey[6]; std::memcpy(authKey, key, 6);
    if (nfc.mifareclassic_AuthenticateBlock(uid, 4, block, 0, authKey) && nfc.mifareclassic_WriteDataBlock(block, data)) return true;
  }
  return false;
}

bool personalize(uint8_t uid[4]) {
  const int8_t factoryIndex = authenticateFactory(uid, kTrailerBlock);
  if (factoryIndex < 0) return false;
  uint8_t trailer[16] = {kKeyA[0], kKeyA[1], kKeyA[2], kKeyA[3], kKeyA[4], kKeyA[5], 0xFF, 0x07, 0x80, 0x00,
                         kKeyB[0], kKeyB[1], kKeyB[2], kKeyB[3], kKeyB[4], kKeyB[5]};
  emit("progress", "write_protection");
  if (!writeBlock(uid, kTrailerBlock, kFactoryKeys[factoryIndex], trailer) || !reselect(uid)) return false;
  uint8_t data[16] = {}; wallet(data);
  emit("progress", "write_wallet");
  if (!writeBlock(uid, kWalletBlock, kKeyA, data) || !reselect(uid)) return false;
  uint8_t key[6]; uint8_t actual[16] = {}; std::memcpy(key, kKeyA, 6);
  emit("progress", "verify_wallet");
  return nfc.mifareclassic_AuthenticateBlock(uid, 4, kWalletBlock, 0, key) && nfc.mifareclassic_ReadDataBlock(kWalletBlock, actual) && std::memcmp(data, actual, 16) == 0;
}

void resetCard() { cardPresent = false; cardReady = false; cardState = CardState::None; cardSince = 0; lastCardSeen = 0; }

bool isCommand(const char *payload, const char *type) {
  char expected[64] = {};
  std::snprintf(expected, sizeof(expected), "\"type\":\"%s\"", type);
  return std::strstr(payload, expected) != nullptr;
}

void command(const char *payload) {
  if (std::strstr(payload, "\"v\":1") == nullptr) { emit("error", "bad_version"); return; }
  const uint32_t now = millis();
  if (isCommand(payload, "status_request")) { emit("status", "perso_ready"); emitNfcInitDiagnostic(); return; }
  if (isCommand(payload, "cancel")) { operation = Operation::Idle; resetCard(); emit("status", "cancelled"); return; }
  // Closing the desktop application must end its authorization session. If a
  // master card is still resting on the reader, it must be removed and tapped
  // again before it can open a fresh session.
  if (isCommand(payload, "session_lock")) {
    sessionOpen = false;
    operation = Operation::Idle;
    resetCard();
    requireMasterRemoval = true;
    emit("status", "session_locked");
    return;
  }
  if (isCommand(payload, "technical_scan")) { technicalScan(); return; }
  if (isCommand(payload, "card_quality_test")) { cardQualityTest("manual"); return; }
  if (isCommand(payload, "register_master_begin")) {
    if (masterSet) { emit("error", "master_already_registered"); return; }
    operation = Operation::EnrollMaster; resetCard(); emit("status", "master_enroll_wait_card"); return;
  }
  if (isCommand(payload, "register_master_commit")) {
    if (operation != Operation::EnrollMaster || !cardPresent || now - cardSince < 10000) { emit("error", "master_hold_incomplete"); return; }
    saveMaster(cardUid); sessionOpen = true; operation = Operation::Idle; std::memcpy(removalUid, cardUid, 4); awaitingRemoval = true; removalNoticeSent = false; emit("result", "master_registered"); return;
  }
  if (isCommand(payload, "reset_master_begin")) {
    if (!masterSet) { emit("error", "master_not_registered"); return; }
    operation = Operation::ResetMaster; operationSince = now; emit("status", "master_reset_hold"); return;
  }
  if (isCommand(payload, "reset_master_commit")) {
    if (operation != Operation::ResetMaster || now - operationSince < 10000) { emit("error", "reset_hold_incomplete"); return; }
    EEPROM.write(0, 0); EEPROM.commit(); masterSet = false; sessionOpen = false; operation = Operation::Idle; emit("result", "master_reset"); return;
  }
  if (isCommand(payload, "perso_arm")) {
    if (!sessionOpen) { emit("error", "master_session_required"); return; }
    operation = Operation::ArmPerso; resetCard(); emit("status", "perso_wait_card"); return;
  }
  if (isCommand(payload, "perso_commit")) {
    if (operation != Operation::ReviewPerso || !cardPresent || !cardReady || cardState != CardState::Blank) { emit("error", "perso_not_ready"); return; }
    emit("progress", "start"); operation = Operation::Idle; const bool ok = personalize(cardUid); cardReady = false;
    std::memcpy(removalUid, cardUid, 4); awaitingRemoval = true; removalNoticeSent = false; emit("result", ok ? "perso_success" : "perso_failed"); return;
  }
  emit("error", "command_not_allowed");
}

void serialBridge() {
  while (Serial.available() > 0) {
    const uint8_t input = static_cast<uint8_t>(Serial.read());
    // Desktop requests start with A5 5A. Ignore any other incoming bytes so
    // an old serial monitor or boot noise cannot desynchronise the bridge.
    if (rxSyncUsed == 0) {
      if (input == 0xA5) rxSyncUsed = 1;
      continue;
    }
    if (rxSyncUsed == 1) {
      rxSyncUsed = input == 0x5A ? 2 : (input == 0xA5 ? 1 : 0);
      continue;
    }
    if (rxHeaderUsed < 2) {
      rxHeader[rxHeaderUsed++] = input;
      if (rxHeaderUsed == 2) {
        rxExpected = static_cast<uint16_t>((rxHeader[0] << 8u) | rxHeader[1]);
        rxUsed = 0;
        if (rxExpected == 0 || rxExpected > 256) {
          rxSyncUsed = 0; rxHeaderUsed = 0; emit("error", "frame_length_invalid");
        }
      }
      continue;
    }
    rxPayload[rxUsed++] = static_cast<char>(input);
    if (rxUsed == rxExpected) {
      rxPayload[rxUsed] = 0;
      command(rxPayload);
      rxSyncUsed = 0; rxHeaderUsed = 0; rxUsed = 0; rxExpected = 0;
    }
  }
}

void cardPresence(uint32_t now) {
  uint8_t uid[7] = {}; uint8_t uidLength = 0;
  const bool found = nfc.readPassiveTargetID(
      PN532_MIFARE_ISO14443A, uid, &uidLength, kPresenceReadTimeoutMs) && uidLength == 4;
  if (!found) {
    if (requireMasterRemoval) requireMasterRemoval = false;
    if ((cardPresent || awaitingRemoval) && lastCardSeen != 0 && now - lastCardSeen < kAbsentGraceMs) return;
    if (cardPresent) emit("card", "removed");
    resetCard(); awaitingRemoval = false; removalNoticeSent = false; return;
  }
  lastCardSeen = now;
  if (requireMasterRemoval) return;
  if (awaitingRemoval && std::memcmp(uid, removalUid, 4) == 0) { if (!removalNoticeSent) { removalNoticeSent = true; emit("status", "remove_card_before_next"); } return; }
  const bool isMaster = masterSet && std::memcmp(uid, masterUid, 4) == 0;
  if (isMaster && operation == Operation::Idle) {
    bool newlyDetected = false;
    if (!cardPresent || std::memcmp(uid, cardUid, 4) != 0) {
      std::memcpy(cardUid, uid, 4);
      cardPresent = true;
      cardSince = now;
      ++cardSession;
      emit("card", "detected");
      // Generic acknowledgement only: the desktop never receives the UID.
      emit("master", "tapped");
      newlyDetected = true;
    }
    if (!sessionOpen) {
      sessionOpen = true;
      emit("master", "session_opened");
    }
    // The master is also a physical NFC card and can be quality tested. This
    // does not read/write its sectors or reveal identity data.
    if (newlyDetected && sessionOpen) cardQualityTest();
    return;
  }
  // Idle presence indication is deliberately generic: no UID or card data is
  // sent to the desktop app, only a detected/removed state.
  if (operation == Operation::Idle) {
    if (!cardPresent || std::memcmp(uid, cardUid, 4) != 0) {
      std::memcpy(cardUid, uid, 4);
      cardPresent = true;
      cardSince = now;
      ++cardSession;
      emit("card", "detected");
      // The board already knows this is not the master card. Start the
      // read-only scan immediately so a short operator tap cannot disappear
      // before the desktop has sent a follow-up command.
      // A newly detected non-master card starts a Technical Debug scan only
      // while idle.  During ArmPerso/ReviewPerso it belongs to the final
      // Block-8 check and must not restart the whole scan flow.
      if (sessionOpen && operation == Operation::Idle) technicalScan();
    }
    return;
  }
  if (operation != Operation::EnrollMaster && operation != Operation::ArmPerso && operation != Operation::ReviewPerso) return;
  if (!cardPresent || std::memcmp(uid, cardUid, 4) != 0) { std::memcpy(cardUid, uid, 4); cardPresent = true; cardReady = false; cardState = CardState::None; cardSince = now; ++cardSession; emit("card", "detected"); return; }
  if (operation == Operation::EnrollMaster) { if (now - cardSince >= 10000 && !cardReady) { cardReady = true; emit("status", "master_hold_ready"); } return; }
  if (operation == Operation::ArmPerso && now - cardSince >= 3000) {
    emit("progress", "precheck"); cardState = probe(cardUid); cardReady = true; operation = Operation::ReviewPerso;
    emit("precheck", cardState == CardState::Blank ? "blank" : cardState == CardState::Existing ? "already_personalized" : "foreign_or_invalid");
  }
}

void setup() {
  Serial.begin(kBaudRate);
#if defined(PERSO_NFC_SPI)
  SPI.begin(kNfcSpiSckPin, kNfcSpiMisoPin, kNfcSpiMosiPin, kNfcSpiCsPin);
#else
  Wire.begin(kSdaPin, kSclPin, 100000);
#endif
  EEPROM.begin(64);
  loadMaster();
  if (!kI2cDiagnosticOnly) nfcReady = initNfc();
  emit("status", kI2cDiagnosticOnly ? "i2c_diagnostic_ready" : (nfcReady ? "boot_ready" : "nfc_unavailable"));
}

void loop() {
  serialBridge();
  const uint32_t now = millis();
  if (!kI2cDiagnosticOnly && !nfcReady && now - lastNfcInit >= 3000) { nfcReady = initNfc(); if (nfcReady) emit("status", "nfc_recovered"); }
  if (nfcReady && now - lastPoll >= kPollMs) { lastPoll = now; cardPresence(now); }
}
