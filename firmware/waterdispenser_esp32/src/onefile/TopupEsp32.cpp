// SmartDispenser — Device B, TOPUP dan pengelolaan jadwal kartu.
// Wallet pelanggan memakai Block 8; referensi compact, counter, dan MAC berada
// di Block 9; Block 10 adalah jurnal commit. Key A masih bersifat referensi;
// format ini belum anti-clone penuh.

#include <Arduino.h>
#include "Esp32Board.h"
#include <Wire.h>
#include <EEPROM.h>
#include <LiquidCrystal_PCF8574.h>
#include <PN532_I2C.h>
#include <PN532.h>
#include <cstring>
#include <cstdio>
#include <cstdarg>
#include "CompactCardSecurity.h"
#include "CompactCardWallet.h"

constexpr int kLedPin = waterdispenser_esp32::kLedPin;
constexpr bool kLedActiveLow = waterdispenser_esp32::kLedActiveLow;
constexpr uint32_t kI2cSdaPin = waterdispenser_esp32::kI2cSdaPin, kI2cSclPin = waterdispenser_esp32::kI2cSclPin;
constexpr uint8_t kLcdI2cAddress = 0x27u;
const uint8_t (&kCardKeyA)[6] = smartdispenser::compact_card_private::kMifareKeyA;

constexpr int kEepromMasterFlag = 0, kEepromMasterUid = 1;
constexpr int kEepromCountsMagic = 8, kEepromCountPagi = 9, kEepromCountSiang = 11, kEepromCountSore = 13;
constexpr uint8_t kCountsMagic = 0xC3;
constexpr uint8_t kWalletBlock = smartdispenser::compact_card::kWalletBlock;
constexpr uint8_t kMetadataBlock = smartdispenser::compact_card::kMetadataBlock;
constexpr uint8_t kJournalBlock = smartdispenser::compact_card::kJournalBlock;
constexpr uint8_t kScheduleNone = smartdispenser::compact_card::kScheduleNone;
constexpr uint8_t kSchedulePagi = smartdispenser::compact_card::kSchedulePagi;
constexpr uint8_t kScheduleSiang = smartdispenser::compact_card::kScheduleSiang;
constexpr uint8_t kScheduleSore = smartdispenser::compact_card::kScheduleSore;

HardwareSerial logger(1);
LiquidCrystal_PCF8574 lcd(kLcdI2cAddress);
bool lcdReady = false;
PN532_I2C pn532i2c(Wire);
PN532 nfc(pn532i2c);
bool nfcReady = false;
uint32_t nfcLastInitAttempt = 0;
bool masterSet = false, operatorMode = false;
uint8_t masterUid[4] = {0,0,0,0};
enum class MasterEnrollState { Idle, Waiting, Holding, Ready };
MasterEnrollState masterEnrollState = MasterEnrollState::Idle;
uint8_t masterEnrollUid[4] = {0,0,0,0};
constexpr uint32_t kNfcPollIntervalMs = 100, kCardAbsentGraceMs = 500;
uint32_t masterEnrollSince = 0, lastNfcPoll = 0, lastCardSeen = 0;
bool cardPresent = false, awaitingRemoval = false;
uint8_t cardUid[4] = {0,0,0,0}, awaitingRemovalUid[4] = {0,0,0,0};
// Sama seperti Perso: Test Card adalah jalur presence-only yang terisolasi.
// Mode ini tidak membaca Wallet, tidak membuka sesi master, dan menerima
// kartu master maupun kartu pelanggan.
bool cardTestMode = false, cardTestPresent = false;
bool cardWatchMode = false;
uint8_t cardTestUid[4] = {0,0,0,0};
uint32_t cardTestLastSeen = 0, cardTestDetections = 0;
uint16_t countPagi = 0, countSiang = 0, countSore = 0;
uint32_t feedbackUntil = 0;
char feedbackLine1[17] = {}, feedbackLine2[17] = {};

void logPrefix() { logger.print('['); logger.print(millis()); logger.print("] "); }
void lcdShow(const char *l1, const char *l2) {
  if (!lcdReady) return;
  char a[17], b[17]; std::memset(a, ' ', 16); std::memset(b, ' ', 16); a[16] = b[16] = 0;
  const size_t n1 = strnlen(l1, 16), n2 = strnlen(l2, 16);
  std::memcpy(a + (16 - n1) / 2, l1, n1); std::memcpy(b + (16 - n2) / 2, l2, n2);
  lcd.setCursor(0, 0); lcd.print(a); lcd.setCursor(0, 1); lcd.print(b);
}
void showFeedback(const char *l1, const char *l2, uint32_t durationMs = 3000) {
  std::memset(feedbackLine1, 0, sizeof(feedbackLine1)); std::memset(feedbackLine2, 0, sizeof(feedbackLine2));
  std::memcpy(feedbackLine1, l1, strnlen(l1, 16)); std::memcpy(feedbackLine2, l2, strnlen(l2, 16));
  feedbackUntil = millis() + durationMs; lcdShow(feedbackLine1, feedbackLine2);
}

using Wallet = smartdispenser::compact_card::Wallet;
enum class WalletRead { Ok, Legacy, Invalid };
bool reselectCard(uint8_t uid[4]);
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
  uint8_t block[16]{};
  if (!nfc.mifareclassic_ReadDataBlock(kWalletBlock, block)) return WalletRead::Invalid;
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
  if (block[0] == 'W' && block[3] <= 100 && block[4] <= 1) {
    out.available = block[3]; out.permitted = block[4] != 0; out.schedule = kScheduleNone; out.day = 0; out.usedToday = 0; out.reserved = 0;
    return WalletRead::Legacy;
  }
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
  if (!reselectCard(uid)) return false;
  Wallet verify{}; smartdispenser::compact_card::Metadata verified{};
  const bool committed = readWallet(uid, verify, &verified) == WalletRead::Ok && smartdispenser::compact_card::walletEqual(verify, w) &&
                         verified.cardReference == next.cardReference && verified.transactionCounter == next.transactionCounter;
  if (committed) {
    uint8_t blankJournal[16]{};
    (void)writeProtectedBlockWithRetry(uid, kJournalBlock, blankJournal);
  }
  return committed;
}

uint16_t eepromRead16(int address) { return static_cast<uint16_t>((EEPROM.read(address) << 8) | EEPROM.read(address + 1)); }
void eepromWrite16(int address, uint16_t value) { waterdispenser_esp32::updateStorage(address, static_cast<uint8_t>(value >> 8)); waterdispenser_esp32::updateStorage(address + 1, static_cast<uint8_t>(value)); }
void loadCounts() {
  if (EEPROM.read(kEepromCountsMagic) != kCountsMagic) {
    countPagi = countSiang = countSore = 0; waterdispenser_esp32::updateStorage(kEepromCountsMagic, kCountsMagic);
    eepromWrite16(kEepromCountPagi, 0); eepromWrite16(kEepromCountSiang, 0); eepromWrite16(kEepromCountSore, 0); return;
  }
  countPagi = eepromRead16(kEepromCountPagi); countSiang = eepromRead16(kEepromCountSiang); countSore = eepromRead16(kEepromCountSore);
}
void saveCounts() { eepromWrite16(kEepromCountPagi, countPagi); eepromWrite16(kEepromCountSiang, countSiang); eepromWrite16(kEepromCountSore, countSore); }
void adjustCount(uint8_t oldGroup, uint8_t newGroup) {
  if (oldGroup == kSchedulePagi && countPagi) --countPagi;
  if (oldGroup == kScheduleSiang && countSiang) --countSiang;
  if (oldGroup == kScheduleSore && countSore) --countSore;
  if (newGroup == kSchedulePagi) ++countPagi;
  if (newGroup == kScheduleSiang) ++countSiang;
  if (newGroup == kScheduleSore) ++countSore;
  saveCounts();
}
const char *scheduleName(uint8_t schedule) { return schedule == kSchedulePagi ? "PAGI" : schedule == kScheduleSiang ? "SIANG" : schedule == kScheduleSore ? "SORE" : "BELUM ADA"; }

void loadMaster() { masterSet = EEPROM.read(kEepromMasterFlag) == 0xA5; for (uint8_t i = 0; i < 4; ++i) masterUid[i] = EEPROM.read(kEepromMasterUid + i); }
void saveMaster(const uint8_t uid[4]) { for (uint8_t i = 0; i < 4; ++i) waterdispenser_esp32::updateStorage(kEepromMasterUid + i, uid[i]); waterdispenser_esp32::updateStorage(kEepromMasterFlag, 0xA5); masterSet = true; std::memcpy(masterUid, uid, 4); }

bool configureSamForI2cReader() {
  // Board ESP32 memakai PN532 I2C polling-only (GPIO4/GPIO5), tanpa jalur IRQ.
  // Gunakan command SAM bounded yang sama dengan firmware Perso agar boot
  // tidak terkunci selamanya ketika PN532 belum siap.
  const uint8_t command[] = {0x14, 0x01, 0x14, 0x00};
  uint8_t response[8]{};
  if (pn532i2c.writeCommand(command, sizeof(command)) != 0) return false;
  return pn532i2c.readResponse(response, sizeof(response), 1000) >= 0;
}
bool initializeNfc() {
  nfc.begin();
  nfcLastInitAttempt = millis();
  if (nfc.getFirmwareVersion() == 0) return false;
  if (!configureSamForI2cReader()) return false;
  nfc.setPassiveActivationRetries(0x19);
  return true;
}

// Bridge COM v1. Tombol tidak dipakai; LCD hanya menampilkan status pasif.
char commandLine[96]{}; uint8_t commandLength = 0;
bool compactCommandPending = false;
void replyLine(const char *format, ...) {
  char line[256]{};
  va_list args; va_start(args, format);
  const int used=std::vsnprintf(line,sizeof(line)-2,format,args);
  va_end(args);
  if (used<0) return;
  const size_t size=static_cast<size_t>(used)<sizeof(line)-2 ? static_cast<size_t>(used) : sizeof(line)-2;
  line[size]='\r'; line[size+1]='\n';
  logger.write(reinterpret_cast<const uint8_t *>(line),size+2);
}
void replyError(const char *id, const char *reason) { replyLine("RES %s ERR %s",id,reason); }
void emitEvent(const char *scope, const char *state) { replyLine("EVT %s %s",scope,state); }
bool readPassiveCard(uint8_t uid[7], uint8_t &len) {
  len=0;
  return nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A,uid,&len) && len==4;
}
bool reselectCard(uint8_t uid[4]) {
  uint8_t freshUid[7]{}; uint8_t freshLen=0;
  if (!readPassiveCard(freshUid,freshLen) || std::memcmp(uid,freshUid,4)!=0) return false;
  std::memcpy(uid,freshUid,4);
  return true;
}
const char *masterEnrollStateName() {
  switch (masterEnrollState) {
    case MasterEnrollState::Waiting: return "waiting";
    case MasterEnrollState::Holding: return "holding";
    case MasterEnrollState::Ready: return "ready";
    default: return "idle";
  }
}
void serviceCardPresence(uint32_t now) {
  uint8_t uid[7]{}; uint8_t uidLen=0;
  const bool present=readPassiveCard(uid,uidLen);
  if (cardTestMode) {
    if (!present) {
      if (cardTestPresent && cardTestLastSeen!=0 && now-cardTestLastSeen<kCardAbsentGraceMs) return;
      if (cardTestPresent) emitEvent("card_test","removed");
      cardTestPresent=false; cardTestLastSeen=0;
      return;
    }
    cardTestLastSeen=now;
    if (!cardTestPresent || std::memcmp(uid,cardTestUid,4)!=0) {
      std::memcpy(cardTestUid,uid,4); cardTestPresent=true; ++cardTestDetections;
      emitEvent("card_test","detected");
    }
    return;
  }
  if (!present) {
    if (cardPresent && lastCardSeen!=0 && now-lastCardSeen<kCardAbsentGraceMs) return;
    if (cardPresent && cardWatchMode) emitEvent("card","removed");
    cardPresent=false; lastCardSeen=0;
    if (awaitingRemoval) awaitingRemoval=false;
    if (masterEnrollState==MasterEnrollState::Holding || masterEnrollState==MasterEnrollState::Ready) {
      masterEnrollState=MasterEnrollState::Waiting; masterEnrollSince=0;
      std::memset(masterEnrollUid,0,sizeof(masterEnrollUid));
    }
    return;
  }
  lastCardSeen=now;
  const bool newlyDetected=!cardPresent || std::memcmp(uid,cardUid,4)!=0;
  if (newlyDetected) {
    std::memcpy(cardUid,uid,4); cardPresent=true;
  }
  if (awaitingRemoval && std::memcmp(uid,awaitingRemovalUid,4)==0) return;
  if (awaitingRemoval) awaitingRemoval=false;
  if (!masterSet && masterEnrollState!=MasterEnrollState::Idle) {
    if (masterEnrollState==MasterEnrollState::Waiting || std::memcmp(uid,masterEnrollUid,4)!=0) {
      std::memcpy(masterEnrollUid,uid,4); masterEnrollSince=now;
      masterEnrollState=MasterEnrollState::Holding;
      return;
    }
    if (masterEnrollState==MasterEnrollState::Holding && now-masterEnrollSince>=10000)
      masterEnrollState=MasterEnrollState::Ready;
    return;
  }
  if (masterSet && std::memcmp(uid,masterUid,4)==0) {
    if (!operatorMode) {
      operatorMode=true;
      lcdShow("TOPUP BRIDGE","MASTER AKTIF");
      emitEvent("master","session_opened");
    }
    return;
  }
  if (newlyDetected && cardWatchMode) emitEvent("card","detected");
}
bool selectCurrentCard(uint8_t uid[4]) {
  if (!cardPresent) {
    serviceCardPresence(millis());
    if (!cardPresent) return false;
  }
  std::memcpy(uid,cardUid,4);
  if (!reselectCard(uid)) return false;
  lastCardSeen=millis();
  return true;
}
void replyWallet(const char *id, const Wallet &w, const smartdispenser::compact_card::Metadata &metadata) {
  replyLine("RES %s OK reference=%08lX balance=%u active=%u schedule=%u used=%u reserved=%u legacy=0 revision=%lu",id,static_cast<unsigned long>(metadata.cardReference),static_cast<unsigned>(w.available),w.permitted ? 1u : 0u,static_cast<unsigned>(w.schedule),static_cast<unsigned>(w.usedToday),static_cast<unsigned>(w.reserved),static_cast<unsigned long>(metadata.transactionCounter));
}
void mutate(const char *id, const char *kind, int value) {
  if (!operatorMode) { replyError(id,"master_required"); return; }
  if (!nfcReady) { replyError(id,"nfc_unavailable"); return; }
  uint8_t uid[4]{}; if (!selectCurrentCard(uid)) { replyError(id,"card_absent"); return; }
  if (masterSet && std::memcmp(uid,masterUid,4)==0) { replyError(id,"customer_card_required"); return; }
  Wallet w{}; smartdispenser::compact_card::Metadata metadata{}; WalletRead state=readWallet(uid,w,&metadata);
  if (state==WalletRead::Invalid) { replyError(id,"wallet_invalid"); return; }
  if (state!=WalletRead::Ok) { replyError(id,"secure_metadata_required"); return; }
  Wallet update=w;
  if (std::strcmp(kind,"ADJUST")==0) { int total=static_cast<int>(w.available)+value; if ((value!=10&&value!=20&&value!=30&&value!=-10&&value!=-20&&value!=-30)||total<0||total>100) { replyError(id,"balance_invalid"); return; } update.available=static_cast<uint8_t>(total); }
  else if (std::strcmp(kind,"ACTIVE")==0) { if (value!=0&&value!=1) { replyError(id,"active_invalid"); return; } update.permitted=value==1; }
  else if (std::strcmp(kind,"SCHEDULE")==0) { if (value<1||value>3) { replyError(id,"schedule_invalid"); return; } update.schedule=static_cast<uint8_t>(value); }
  else if (std::strcmp(kind,"UPGRADE")==0) { replyError(id,"upgrade_in_perso_required"); return; }
  else if (std::strcmp(kind,"RELEASE")==0) { if (w.reserved==0 || static_cast<uint16_t>(w.available)+w.reserved>100) { replyError(id,"reserve_invalid"); return; } update.available=static_cast<uint8_t>(w.available+w.reserved); update.reserved=0; }
  // Counter pemakaian harian dipulihkan secara manual hanya dalam sesi
  // master. Saldo aktif, jadwal, status, dan cadangan tidak diubah.
  else if (std::strcmp(kind,"RESET_USED")==0) { update.usedToday=0; }
  else { replyError(id,"command_invalid"); return; }
  if (!writeWallet(uid,update,metadata)) { replyError(id,"write_or_readback_failed"); return; }
  if (std::strcmp(kind,"SCHEDULE")==0) adjustCount(w.schedule,update.schedule);
  ++metadata.transactionCounter; lcdShow("TOPUP BRIDGE","WRITE BERHASIL"); replyWallet(id,update,metadata);
}
void processCommand(char *line) {
  char id[37]{}, kind[16]{}; int value=0; int fields=std::sscanf(line,"REQ %36s %15s %d",id,kind,&value);
  if (fields<2) return;
  if (std::strcmp(kind,"HELLO")==0) { replyLine("RES %s OK bridge=topup-v1 nfc=%s features=reset_used",id,nfcReady ? "ready" : "not_ready"); return; }
  if (std::strcmp(kind,"TEST_START")==0) {
    if (!nfcReady) { replyError(id,"nfc_unavailable"); return; }
    cardWatchMode=false; cardTestMode=true; cardTestPresent=false; cardTestLastSeen=0;
    replyLine("RES %s OK state=ready present=0 detections=%lu",id,static_cast<unsigned long>(cardTestDetections)); return;
  }
  if (std::strcmp(kind,"TEST_STATUS")==0) {
    if (!nfcReady) { replyError(id,"nfc_unavailable"); return; }
    if (!cardTestMode) { replyError(id,"card_test_not_started"); return; }
    replyLine("RES %s OK state=active present=%u detections=%lu",id,cardTestPresent ? 1u : 0u,static_cast<unsigned long>(cardTestDetections)); return;
  }
  if (std::strcmp(kind,"TEST_STOP")==0) {
    cardTestMode=false; cardTestPresent=false; cardTestLastSeen=0;
    replyLine("RES %s OK state=stopped",id); return;
  }
  if (std::strcmp(kind,"WATCH_START")==0) {
    if (!nfcReady) { replyError(id,"nfc_unavailable"); return; }
    cardTestMode=false; cardTestPresent=false; cardTestLastSeen=0; cardWatchMode=true;
    replyLine("RES %s OK state=ready",id);
    if (cardPresent && (!masterSet || std::memcmp(cardUid,masterUid,4)!=0)) emitEvent("card","detected");
    return;
  }
  if (std::strcmp(kind,"WATCH_STOP")==0) {
    cardWatchMode=false;
    replyLine("RES %s OK state=stopped",id); return;
  }
  if (std::strcmp(kind,"ENROLL_BEGIN")==0) {
    if (!nfcReady) { replyError(id,"nfc_unavailable"); return; }
    if (masterSet) { replyError(id,"master_already_set"); return; }
    masterEnrollState=MasterEnrollState::Waiting; masterEnrollSince=0;
    std::memset(masterEnrollUid,0,sizeof(masterEnrollUid)); lcdShow("DAFTAR MASTER","TEMPELKAN KARTU");
    replyLine("RES %s OK state=waiting",id); return;
  }
  if (std::strcmp(kind,"ENROLL_STATUS")==0) {
    if (!nfcReady) { replyError(id,"nfc_unavailable"); return; }
    if (masterSet) { replyLine("RES %s OK state=registered",id); return; }
    replyLine("RES %s OK state=%s",id,masterEnrollStateName()); return;
  }
  if (std::strcmp(kind,"ENROLL_COMMIT")==0) {
    if (!nfcReady) { replyError(id,"nfc_unavailable"); return; }
    if (masterSet) { replyError(id,"master_already_set"); return; }
    if (masterEnrollState!=MasterEnrollState::Ready) { replyError(id,"master_hold_incomplete"); return; }
    saveMaster(masterEnrollUid); operatorMode=true; masterEnrollState=MasterEnrollState::Idle;
    awaitingRemoval=true; std::memcpy(awaitingRemovalUid,masterEnrollUid,4);
    lcdShow("TOPUP BRIDGE","MASTER TERSIMPAN"); replyLine("RES %s OK master=enrolled",id); return;
  }
  if (std::strcmp(kind,"LOCK")==0) {
    operatorMode=false;
    if (cardPresent && masterSet && std::memcmp(cardUid,masterUid,4)==0) {
      awaitingRemoval=true; std::memcpy(awaitingRemovalUid,cardUid,4);
    }
    replyLine("RES %s OK master=locked",id); return;
  }
  if (std::strcmp(kind,"UNLOCK")==0) {
    if (!masterSet) { replyError(id,"master_not_set"); return; }
    if (!nfcReady) { replyError(id,"nfc_unavailable"); return; }
    if (!operatorMode) serviceCardPresence(millis());
    if (!operatorMode) { replyError(id,"master_not_present"); return; }
    replyLine("RES %s OK master=unlocked",id); return;
  }
  if (std::strcmp(kind,"READ")==0) {
    uint8_t uid[4]{}; Wallet w{}; smartdispenser::compact_card::Metadata metadata{};
    if (!nfcReady) { replyError(id,"nfc_unavailable"); return; }
    if (!selectCurrentCard(uid)) { replyError(id,"card_absent"); return; }
    if (masterSet && std::memcmp(uid,masterUid,4)==0) { replyError(id,"customer_card_required"); return; }
    WalletRead state=readWallet(uid,w,&metadata); if (state==WalletRead::Invalid) { replyError(id,"wallet_invalid"); return; }
    if (state!=WalletRead::Ok || metadata.cardReference==0) { replyError(id,"card_identity_required"); return; }
    lcdShow("TOPUP BRIDGE","KARTU TERBACA"); replyWallet(id,w,metadata); return;
  }
  // RELEASE dan RESET_USED tidak memakai angka dari aplikasi desktop. Hanya
  // mutasi yang memang mengubah nilai/status/jadwal membutuhkan parameter
  // ketiga.
  const bool needsValue = std::strcmp(kind,"ADJUST")==0 ||
                          std::strcmp(kind,"ACTIVE")==0 ||
                          std::strcmp(kind,"SCHEDULE")==0;
  if (needsValue && fields<3) { replyError(id,"value_required"); return; }
  mutate(id,kind,value);
}
void setup() {
  if (kLedPin >= 0) { pinMode(kLedPin,OUTPUT); digitalWrite(kLedPin,kLedActiveLow ? HIGH : LOW); }
  if (!waterdispenser_esp32::beginStorage()) {
    while (true) delay(1000);
  }
  waterdispenser_esp32::beginBridge(logger);
#ifdef SMARTDISPENSER_RESET_TOPUP_MASTER_ON_BOOT
  waterdispenser_esp32::updateStorage(kEepromMasterFlag,0);
#endif
  waterdispenser_esp32::beginI2c();
  Wire.beginTransmission(kLcdI2cAddress); if (Wire.endTransmission()==0) { lcd.begin(16,2,Wire); lcdReady=lcd.isConnected(); lcd.setBacklight(255); }
  nfcReady=initializeNfc(); loadMaster(); loadCounts();
  lcdShow("ALAT TOPUP",nfcReady ? "COM SIAP" : "NFC BELUM SIAP");
  logger.println("TOPUP BRIDGE V1 READY");
}
int readBridgeByte() {
  if (logger.available()) return logger.read();
  return -1;
}
void loop() {
  for (int raw=readBridgeByte(); raw>=0; raw=readBridgeByte()) {
    const char c=static_cast<char>(raw);
    if (c=='!') { commandLength=0; compactCommandPending=true; continue; }
    if (compactCommandPending) {
      compactCommandPending=false;
      if (c=='H') { char request[]="REQ H HELLO"; processCommand(request); }
      else if (c=='L') { char request[]="REQ L LOCK"; processCommand(request); }
      else if (c=='U') { char request[]="REQ U UNLOCK"; processCommand(request); }
      else if (c=='E') { char request[]="REQ E ENROLL_BEGIN"; processCommand(request); }
      else if (c=='Q') { char request[]="REQ Q ENROLL_STATUS"; processCommand(request); }
      else if (c=='C') { char request[]="REQ C ENROLL_COMMIT"; processCommand(request); }
      else if (c=='R') { char request[]="REQ R READ"; processCommand(request); }
      else if (c=='Y') { char request[]="REQ Y TEST_START"; processCommand(request); }
      else if (c=='T') { char request[]="REQ T TEST_STATUS"; processCommand(request); }
      else if (c=='Z') { char request[]="REQ Z TEST_STOP"; processCommand(request); }
      else if (c=='J') { char request[]="REQ J WATCH_START"; processCommand(request); }
      else if (c=='K') { char request[]="REQ K WATCH_STOP"; processCommand(request); }
      continue;
    }
    if (c=='#') { commandLength=0; continue; }
    if (c=='\r') continue;
    if (c=='\n') { commandLine[commandLength]=0; processCommand(commandLine); commandLength=0; }
    else if (commandLength<sizeof(commandLine)-1) commandLine[commandLength++]=c;
    else commandLength=0;
  }
  const uint32_t now=millis();
  if (!nfcReady && now-nfcLastInitAttempt>=3000) {
    nfcReady=initializeNfc();
    if (nfcReady) lcdShow("ALAT TOPUP","NFC PULIH");
  }
  // Sama seperti Perso: hanya loop firmware ini yang memiliki polling PN532.
  // Perintah desktop memakai state kartu hasil polling, sehingga tidak ada
  // pembacaan I2C paralel atau ketergantungan pada satu momen perintah UNLOCK.
  if (nfcReady && now-lastNfcPoll>=kNfcPollIntervalMs) {
    lastNfcPoll=now;
    serviceCardPresence(now);
  }
}
