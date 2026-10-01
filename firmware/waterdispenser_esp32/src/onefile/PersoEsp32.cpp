// SmartDispenser — Device B, mode PERSONALISASI KARTU BARU.
// Gaya referensi: satu file, panggil library PN532 langsung, tanpa kelas
// pembungkus. Kunci Key A/B TETAP (sama untuk semua kartu, tidak diturunkan
// per-kartu) -- lihat peringatan keamanan di bawah.
//
// Tugas alat ini SATU SAJA: kenali kartu kosong (belum pernah dipakai), lalu
// tulis saldo awal 0 + status aktif di Block 8 dan metadata compact di Block 9.
// Tidak ada menu topup/status/release di
// sini -- itu tugas Topup.cpp (image firmware terpisah untuk alat B yang
// sama; flash salah satu sesuai kebutuhan operator).
//
// PERINGATAN KEAMANAN (disetujui eksplisit oleh pemilik proyek): Key A/B di
// bawah dikompilasi sama persis di setiap alat dan setiap kartu. Siapa pun
// yang mengekstraknya (mudah dengan Proxmark3/Flipper Zero) bisa
// membaca/menulis/clone semua kartu. UID kartu master tetap dapat dipalsukan;
// MAC Block 9 tidak memperbaiki kelemahan autentikasi MIFARE Classic itu.
// Jangan pakai build ini untuk kartu yang menyimpan nilai nyata.

#include <Arduino.h>
#include "Esp32Board.h"
#include <Wire.h>
#include <EEPROM.h>
#include <LiquidCrystal_PCF8574.h>
#include <PN532_I2C.h>
#include <PN532.h>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include "CompactCardSecurity.h"
#include "CompactCardWallet.h"

constexpr int kLedPin = waterdispenser_esp32::kLedPin;
constexpr bool kLedActiveLow = waterdispenser_esp32::kLedActiveLow;
constexpr uint32_t kI2cSdaPin = waterdispenser_esp32::kI2cSdaPin;
constexpr uint32_t kI2cSclPin = waterdispenser_esp32::kI2cSclPin;
constexpr uint8_t kLcdI2cAddress = 0x27u;
constexpr int kButtonP1Pin = waterdispenser_esp32::kButtonP1Pin;
constexpr int kButtonP2Pin = waterdispenser_esp32::kButtonP2Pin;
constexpr int kButtonP3Pin = waterdispenser_esp32::kButtonP3Pin;
constexpr int kIndicatorPb0Pin = waterdispenser_esp32::kFlowIndicatorPin;
constexpr int kIndicatorPb1Pin = waterdispenser_esp32::kFlowIndicatorPin;

// ---------------- Kunci kartu tetap (lihat peringatan di atas) -----------
const uint8_t (&kCardKeyA)[6] = smartdispenser::compact_card_private::kMifareKeyA;
const uint8_t (&kCardKeyB)[6] = smartdispenser::compact_card_private::kMifareKeyB;
// Kandidat "kunci pabrik" kartu kosong. Semuanya kunci DEFAULT PUBLIK yang
// dipakai berbagai vendor kartu MIFARE Classic kosong (bukan rahasia): FF
// polos, kunci MAD NXP, kunci default NDEF NXP, dan nol polos.
constexpr uint8_t kFactoryKeyCandidateCount = 4;
uint8_t kFactoryKeyCandidates[kFactoryKeyCandidateCount][6] = {
  {0xFF,0xFF,0xFF,0xFF,0xFF,0xFF},
  {0xA0,0xA1,0xA2,0xA3,0xA4,0xA5},
  {0xD3,0xF7,0xD3,0xF7,0xD3,0xF7},
  {0x00,0x00,0x00,0x00,0x00,0x00},
};

// ---------------- EEPROM: UID master tersimpan ----------------------------
// addr0: 0xA5 jika master sudah terdaftar; addr1..4: 4 byte UID master.
constexpr int kEepromMasterFlag = 0;
constexpr int kEepromMasterUid = 1;
bool masterSet = false;
uint8_t masterUid[4] = {0,0,0,0};
void loadMaster() {
  masterSet = EEPROM.read(kEepromMasterFlag) == 0xA5;
  for (uint8_t i = 0; i < 4; ++i) masterUid[i] = EEPROM.read(kEepromMasterUid + i);
}
void saveMaster(const uint8_t uid[4]) {
  for (uint8_t i = 0; i < 4; ++i) waterdispenser_esp32::updateStorage(kEepromMasterUid + i, uid[i]);
  waterdispenser_esp32::updateStorage(kEepromMasterFlag, 0xA5);
  masterSet = true; std::memcpy(masterUid, uid, 4);
}
// Sesi HARUS di-unlock dgn tap kartu master dulu tiap kali alat baru
// dinyalakan/direset, sebelum boleh memperso kartu pelanggan. Direset ke
// false lagi tiap boot (bukan disimpan ke EEPROM) -- disengaja.
bool sessionUnlocked = false;

// ---------------- Layar & komunikasi ---------------------------------------
// Jalur UART dipakai khusus untuk bridge aplikasi desktop. Log diagnostik
// lama disenyapkan agar tidak merusak frame biner bridge.
struct SilentLogger {
  void begin(unsigned long) {}
  template <typename T> void print(const T &) {}
  template <typename T> void print(const T &, int) {}
  template <typename T> void println(const T &) {}
  template <typename T> void println(const T &, int) {}
  void println() {}
};
SilentLogger logger;
HardwareSerial bridgeSerial(1);
LiquidCrystal_PCF8574 lcd(kLcdI2cAddress);
bool lcdReady = false;
PN532_I2C pn532i2c(Wire);
PN532 nfc(pn532i2c);
bool nfcReady = false;
uint32_t nfcLastInitAttempt = 0;

void lcdShow(const char *l1, const char *l2) {
  if (!lcdReady) return;
  char a[17]; char b[17];
  std::memset(a, ' ', 16); a[16] = 0; std::memset(b, ' ', 16); b[16] = 0;
  const size_t n1 = strnlen(l1, 16), n2 = strnlen(l2, 16);
  std::memcpy(a + (16 - n1) / 2, l1, n1); std::memcpy(b + (16 - n2) / 2, l2, n2);
  // Indikator sesi di pojok kanan bawah: 'O' = sudah tap master sesi ini,
  // '-' = belum (perso kartu pelanggan masih terkunci).
  b[15] = sessionUnlocked ? 'O' : '-';
  lcd.setCursor(0, 0); lcd.print(a); lcd.setCursor(0, 1); lcd.print(b);
}
void logPrefix() { logger.print('['); logger.print(millis()); logger.print("] "); }

// ---------------- Kartu: baca/tulis blok wallet polos (block 8, sektor 2) -
// Sektor 2 dipakai (bukan sektor 1) supaya kartu yang sektor 1-nya rusak
// akibat bug versi lama masih bisa dipakai lagi -- lihat MONITOR log 2026-09.
// Format wallet V2 (Block 8, 16 byte):
// [0]=0xD7, [1]=2, [2]=flag aktif, [3]=saldo, [4]=jadwal (0=belum diatur),
// [5..6]=hari kuota, [7]=pemakaian hari ini, [8]=cadangan transaksi,
// [9..10]=CRC16-CCITT byte 0..8, [11..15]=nol. Block 9 memuat referensi,
// counter, dan AES-CMAC 64-bit. Block 10 adalah jurnal commit. Data belum
// dienkripsi.
constexpr uint8_t kWalletBlock = smartdispenser::compact_card::kWalletBlock;
constexpr uint8_t kMetadataBlock = smartdispenser::compact_card::kMetadataBlock;
constexpr uint8_t kJournalBlock = smartdispenser::compact_card::kJournalBlock;
constexpr uint8_t kTrailerBlock = smartdispenser::compact_card::kTrailerBlock;
bool reselectCard(uint8_t uid[4]);
void makeWalletV2(uint8_t block[16], uint8_t balance, bool active, uint8_t schedule = 0) {
  smartdispenser::compact_card::Wallet wallet{};
  wallet.available = balance;
  wallet.permitted = active;
  wallet.schedule = schedule;
  smartdispenser::compact_card::encodeWallet(wallet, block);
}
bool verifyWalletV2(uint8_t uid[4], const uint8_t expected[16]) {
  if (!reselectCard(uid)) return false;
  uint8_t key[6]; std::memcpy(key, kCardKeyA, 6);
  if (!nfc.mifareclassic_AuthenticateBlock(uid, 4, kWalletBlock, 0, key)) return false;
  uint8_t actual[16]{};
  return nfc.mifareclassic_ReadDataBlock(kWalletBlock, actual) && std::memcmp(actual, expected, 16) == 0;
}
bool isWalletV2(const uint8_t block[16]) {
  smartdispenser::compact_card::Wallet wallet{};
  return smartdispenser::compact_card::decodeWallet(block, wallet);
}
bool isBlankBlock(const uint8_t b[16]) {
  bool zero = true, erased = true;
  for (uint8_t i = 0; i < 16; ++i) { zero &= b[i] == 0; erased &= b[i] == 0xFF; }
  return zero || erased;
}
// Cetak kode status mentah dari PN532 setelah sebuah perintah gagal, supaya
// tahu jenis kegagalannya (timeout komunikasi vs NAK akses kartu, dsb).
// Bukan data kartu/kunci -- cuma satu byte kode status protokol.
void logRawStatus(const char *label) {
  uint8_t len = 0;
  uint8_t *buf = nfc.getBuffer(&len);
  logPrefix(); logger.print(label); logger.print(": KODE STATUS PN532=0x");
  logger.println(buf[0], HEX);
}
// Sebagian chip kartu (terutama clone murah) hanya mengizinkan SATU auth per
// siklus seleksi -- harus WUPA ulang sebelum tiap percobaan kunci berikutnya,
// beda dengan chip NXP asli yang biasanya mengizinkan banyak percobaan.
bool reselectCard(uint8_t uid[4]) {
  uint8_t freshUid[7]{}; uint8_t freshLen = 0;
  if (!nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, freshUid, &freshLen) || freshLen != 4) return false;
  return std::memcmp(uid, freshUid, 4) == 0;
}
// Coba semua kandidat kunci pabrik (semuanya kunci default publik, bukan
// rahasia) pada satu block; kembalikan indeksnya kalau cocok, -1 kalau tidak.
int8_t authWithFactoryCandidate(uint8_t uid[4], uint8_t block) {
  for (uint8_t i = 0; i < kFactoryKeyCandidateCount; ++i) {
    if (!reselectCard(uid)) {
      logPrefix(); logger.println("PROBE: RESELECT GAGAL, KARTU TERANGKAT?");
      return -1;
    }
    uint8_t key[6]; std::memcpy(key, kFactoryKeyCandidates[i], 6);
    if (nfc.mifareclassic_AuthenticateBlock(uid, 4, block, 0, key)) return static_cast<int8_t>(i);
  }
  return -1;
}
// Coba auth dgn kunci kita; kalau gagal, coba tiap kandidat kunci pabrik.
// Log diagnostik di sini TIDAK PERNAH mencetak UID/kunci -- hanya status tahap.
enum class CardState { None, Blank, LegacyPersonalized, SecurePersonalized, Foreign };
CardState classifyBlankWallet(uint8_t metadataBlock[16]) {
  if (!nfc.mifareclassic_ReadDataBlock(kMetadataBlock, metadataBlock)) {
    logRawStatus("PROBE-BLOCK9-READ");
    logPrefix(); logger.println("PROBE: BLOK9 TIDAK DAPAT DIBACA -- KARTU DITOLAK");
    return CardState::Foreign;
  }
  if (!smartdispenser::compact_card::isBlank(metadataBlock)) {
    logPrefix(); logger.println("PROBE: BLOK8 KOSONG TETAPI BLOK9 BERISI DATA -- KARTU DITOLAK");
    return CardState::Foreign;
  }
  logPrefix(); logger.println("PROBE: BLOK8 DAN BLOK9 KOSONG -> KARTU BARU");
  return CardState::Blank;
}
CardState classifyProtectedWallet(uint8_t uid[4], const uint8_t wallet[16]) {
  if (!isWalletV2(wallet)) return CardState::Foreign;
  uint8_t metadataBlock[16]{};
  if (!nfc.mifareclassic_ReadDataBlock(kMetadataBlock, metadataBlock)) return CardState::Foreign;
  if (smartdispenser::compact_card::isBlank(metadataBlock)) return CardState::LegacyPersonalized;
  smartdispenser::compact_card::Metadata metadata{};
  return smartdispenser::compact_card::decodeAndVerify(uid, wallet, metadataBlock, metadata)
    ? CardState::SecurePersonalized : CardState::Foreign;
}
CardState probeCard(uint8_t uid[4], uint8_t uidLen) {
  logPrefix(); logger.print("PROBE: UID PANJANG="); logger.println(uidLen);
  uint8_t keyA[6]; std::memcpy(keyA, kCardKeyA, 6);
  if (nfc.mifareclassic_AuthenticateBlock(uid, 4, kWalletBlock, 0, keyA)) {
    logPrefix(); logger.println("PROBE: AUTH KEYA OK");
    uint8_t block[16]{};
    if (!nfc.mifareclassic_ReadDataBlock(kWalletBlock, block)) {
      logRawStatus("PROBE-KEYA-READ");
      logPrefix(); logger.println("PROBE: BACA BLOK8 GAGAL SETELAH AUTH KEYA -- COBA KEY B");
      if (reselectCard(uid)) {
        uint8_t keyB[6]; std::memcpy(keyB, kCardKeyB, 6);
        if (nfc.mifareclassic_AuthenticateBlock(uid, 4, kWalletBlock, 1, keyB)) {
          logPrefix(); logger.println("PROBE: AUTH KEYB OK");
          if (nfc.mifareclassic_ReadDataBlock(kWalletBlock, block)) {
            logPrefix(); logger.println("PROBE: BACA BLOK8 VIA KEYB BERHASIL (ACCESS BITS BLOKIR KEYA-READ)");
          } else {
            logRawStatus("PROBE-KEYB-READ");
            logPrefix(); logger.println("PROBE: BACA BLOK8 VIA KEYB JUGA GAGAL");
            // Auth sektor masih berlaku utk block lain di sektor sama -- baca
            // access-condition trailer (block 11, byte 6-9 SAJA, bukan kunci).
            uint8_t trailer[16]{};
            if (nfc.mifareclassic_ReadDataBlock(kTrailerBlock, trailer)) {
              logPrefix();
              logger.print("PROBE: ACCESS-BITS TRAILER=0x");
              logger.print(trailer[6], HEX); logger.print(' ');
              logger.print(trailer[7], HEX); logger.print(' ');
              logger.print(trailer[8], HEX); logger.print(' ');
              logger.println(trailer[9], HEX);
            } else {
              logRawStatus("PROBE-TRAILER-READ");
              logPrefix(); logger.println("PROBE: BACA TRAILER (BLOCK11) JUGA GAGAL");
            }
            // Precheck harus benar-benar read-only. Jangan memperbaiki access
            // bits atau menulis trailer secara otomatis sebelum konfirmasi.
            logPrefix(); logger.println("PROBE: ACCESS BERMASALAH -- TIDAK ADA PERUBAHAN KARTU");
          }
        } else {
          logPrefix(); logger.println("PROBE: AUTH KEYB GAGAL");
        }
      }
      return CardState::Foreign;
    }
    const bool blank = isBlankBlock(block);
    logPrefix(); logger.println(blank ? "PROBE: BLOK8 KOSONG (SEHARUSNYA TIDAK, SUDAH DI-KEY-A)" : "PROBE: BLOK8 SUDAH ADA ISI");
    if (!blank) return classifyProtectedWallet(uid, block);
    uint8_t metadataBlock[16]{};
    return classifyBlankWallet(metadataBlock);
  }
  logPrefix(); logger.println("PROBE: AUTH KEYA GAGAL, COBA KANDIDAT KUNCI PABRIK");
  const int8_t idx = authWithFactoryCandidate(uid, kWalletBlock);
  if (idx >= 0) {
    logPrefix(); logger.print("PROBE: AUTH KUNCI PABRIK KANDIDAT #"); logger.print(idx); logger.println(" OK");
    uint8_t block[16]{};
    if (!nfc.mifareclassic_ReadDataBlock(kWalletBlock, block)) {
      logPrefix(); logger.println("PROBE: BACA BLOK8 GAGAL SETELAH AUTH PABRIK");
    } else if (isBlankBlock(block)) {
      uint8_t metadataBlock[16]{};
      return classifyBlankWallet(metadataBlock);
    } else {
      logPrefix(); logger.println("PROBE: BLOK8 TIDAK KOSONG PADAHAL KUNCI PABRIK (ANEH)");
    }
  } else {
    logPrefix(); logger.println("PROBE: SEMUA KANDIDAT KUNCI PABRIK GAGAL -- KEMUNGKINAN RE-KEY LAMA ATAU KUNCI VENDOR LAIN");
  }
  return CardState::Foreign;
}
// Sebagian kartu (terutama clone murah) sesekali NAK dgn status "timeout"
// (0x01) pada perintah WRITE walau auth-nya valid -- perlu commit EEPROM
// internal kartu sedikit lebih lama. Retry auth+write beberapa kali (dgn
// reselect di antaranya) sebelum benar-benar dianggap gagal.
bool writeWithRetry(uint8_t uid[4], uint8_t block, uint8_t keyType, const uint8_t key[6], uint8_t data[16], const char *label) {
  for (uint8_t attempt = 0; attempt < 3; ++attempt) {
    if (attempt > 0 && !reselectCard(uid)) return false;
    uint8_t k[6]; std::memcpy(k, key, 6);
    if (!nfc.mifareclassic_AuthenticateBlock(uid, 4, block, keyType, k)) continue;
    if (nfc.mifareclassic_WriteDataBlock(block, data)) return true;
    logRawStatus(label);
    logPrefix(); logger.print(label); logger.print(": PERCOBAAN "); logger.print(attempt + 1); logger.println(" GAGAL");
  }
  return false;
}
void bridgeProgress(const char *code);
bool configureSamForI2cReader() {
  // This ESP32 Perso board is wired as I2C polling-only: GPIO4/GPIO5, no IRQ line.
  // Keep the proven reader-mode command for this hardware while retaining
  // Topup-style one-shot card probes above.
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
bool personalizeCard(uint8_t uid[4], uint32_t cardReference, bool migrateLegacy) {
  uint8_t wallet[16]{};
  if (migrateLegacy) {
    if (!reselectCard(uid)) return false;
    uint8_t key[6]; std::memcpy(key, kCardKeyA, 6);
    if (!nfc.mifareclassic_AuthenticateBlock(uid, 4, kWalletBlock, 0, key) ||
        !nfc.mifareclassic_ReadDataBlock(kWalletBlock, wallet) || !isWalletV2(wallet)) return false;
    bridgeProgress("preserve_wallet");
  } else {
    // Kartu baru: ubah trailer sektor 2 dari kredensial pabrik ke profil proyek.
    const int8_t trailerIdx = authWithFactoryCandidate(uid, kTrailerBlock);
    if (trailerIdx < 0) return false;
    uint8_t trailer[16] = {
      kCardKeyA[0],kCardKeyA[1],kCardKeyA[2],kCardKeyA[3],kCardKeyA[4],kCardKeyA[5],
      0xFF,0x07,0x80,0x00,
      kCardKeyB[0],kCardKeyB[1],kCardKeyB[2],kCardKeyB[3],kCardKeyB[4],kCardKeyB[5]
    };
    bridgeProgress("write_protection");
    if (!writeWithRetry(uid, kTrailerBlock, 0, kFactoryKeyCandidates[trailerIdx], trailer, "PERSO-TRAILER-WRITE")) return false;
    makeWalletV2(wallet, 0, true);
  }

  smartdispenser::compact_card::Metadata metadata{};
  metadata.cardReference = cardReference;
  metadata.transactionCounter = 0;
  uint8_t metadataBlock[16]{};
  if (!smartdispenser::compact_card::encode(uid, wallet, metadata, metadataBlock)) return false;
  // Stage the target identity first. Topup/Dispenser can finish Block 9 if
  // power or card presence is lost after Block 8 has committed.
  if (!writeWithRetry(uid, kJournalBlock, 0, kCardKeyA, metadataBlock, "PERSO-JOURNAL-WRITE")) return false;
  if (!migrateLegacy) {
    bridgeProgress("write_wallet");
    if (!writeWithRetry(uid, kWalletBlock, 0, kCardKeyA, wallet, "PERSO-WALLET-WRITE")) return false;
  }
  bridgeProgress("write_metadata");
  if (!writeWithRetry(uid, kMetadataBlock, 0, kCardKeyA, metadataBlock, "PERSO-METADATA-WRITE")) return false;

  bridgeProgress("verify_wallet");
  if (!verifyWalletV2(uid, wallet)) return false;
  if (!reselectCard(uid)) return false;
  uint8_t key[6]; std::memcpy(key, kCardKeyA, 6);
  uint8_t actualMetadata[16]{};
  smartdispenser::compact_card::Metadata decoded{};
  const bool verified = nfc.mifareclassic_AuthenticateBlock(uid, 4, kMetadataBlock, 0, key) &&
                        nfc.mifareclassic_ReadDataBlock(kMetadataBlock, actualMetadata) &&
                        std::memcmp(actualMetadata, metadataBlock, 16) == 0 &&
                        smartdispenser::compact_card::decodeAndVerify(uid, wallet, actualMetadata, decoded) &&
                        decoded.cardReference == cardReference && decoded.transactionCounter == 0;
  if (!verified) return false;
  uint8_t blankJournal[16]{};
  if (!writeWithRetry(uid, kJournalBlock, 0, kCardKeyA, blankJournal, "PERSO-JOURNAL-CLEAR")) return false;
  if (!reselectCard(uid)) return false;
  std::memcpy(key, kCardKeyA, 6);
  uint8_t actualJournal[16]{};
  return nfc.mifareclassic_AuthenticateBlock(uid, 4, kJournalBlock, 0, key) &&
         nfc.mifareclassic_ReadDataBlock(kJournalBlock, actualJournal) &&
         smartdispenser::compact_card::isBlank(actualJournal);
}

bool removePersonalization(uint8_t uid[4], uint32_t &cardReference) {
  // Remove only Card Identity (Block 9). Wallet Data (Block 8), its balance,
  // schedule, and the protected sector trailer are deliberately preserved.
  if (!reselectCard(uid)) return false;
  uint8_t key[6]; std::memcpy(key, kCardKeyA, 6);
  if (!nfc.mifareclassic_AuthenticateBlock(uid, 4, kWalletBlock, 0, key)) return false;
  uint8_t wallet[16]{}, metadataBlock[16]{};
  if (!nfc.mifareclassic_ReadDataBlock(kWalletBlock, wallet) || !isWalletV2(wallet) ||
      !nfc.mifareclassic_ReadDataBlock(kMetadataBlock, metadataBlock)) return false;
  smartdispenser::compact_card::Metadata metadata{};
  if (!smartdispenser::compact_card::decodeAndVerify(uid, wallet, metadataBlock, metadata)) return false;
  cardReference = metadata.cardReference;

  uint8_t blankMetadata[16]{};
  bridgeProgress("remove_metadata");
  if (!writeWithRetry(uid, kJournalBlock, 0, kCardKeyA, blankMetadata, "PERSO-JOURNAL-REMOVE")) return false;
  if (!writeWithRetry(uid, kMetadataBlock, 0, kCardKeyA, blankMetadata, "PERSO-METADATA-REMOVE")) return false;

  bridgeProgress("verify_removed");
  if (!reselectCard(uid)) return false;
  std::memcpy(key, kCardKeyA, 6);
  uint8_t actualMetadata[16]{}, actualJournal[16]{};
  return nfc.mifareclassic_AuthenticateBlock(uid, 4, kMetadataBlock, 0, key) &&
         nfc.mifareclassic_ReadDataBlock(kMetadataBlock, actualMetadata) &&
         nfc.mifareclassic_ReadDataBlock(kJournalBlock, actualJournal) &&
         smartdispenser::compact_card::isBlank(actualMetadata) &&
         smartdispenser::compact_card::isBlank(actualJournal);
}

// ---------------- Bridge aplikasi desktop ---------------------------------
// Frame: uint16 big-endian panjang + JSON UTF-8. Bridge ini tidak menerima
// APDU, UID, key, atau akses blok mentah.
enum class BridgeOperation { Idle, MasterEnroll, MasterReset, PersoArmed, PersoReview };
BridgeOperation bridgeOperation = BridgeOperation::Idle;
uint8_t candidateUid[4] = {0,0,0,0};
bool candidatePresent = false, candidateReady = false, awaitingRemoval = false;
bool awaitingRemovalAnnounced = false;
uint8_t awaitingRemovalUid[4] = {0,0,0,0};
uint32_t candidateSince = 0, operationSince = 0, cardSession = 0;
// Test Card is an isolated, read-only presence test.  It deliberately does
// not reuse the Perso candidate/session state, so testing a master card can
// never open a session or start a Technical Debug scan.
bool cardTestMode = false, cardTestPresent = false;
uint8_t cardTestUid[4] = {0,0,0,0};
uint32_t cardTestLastSeen = 0;
// Owner Lookup memakai jalur presence polling yang sama dengan Test Card,
// tetapi hanya mengirim card_reference yang MAC-nya valid. UID, key, wallet,
// dan isi blok mentah tetap berada di STM32.
bool ownerLookupMode = false, ownerLookupPresent = false;
uint8_t ownerLookupUid[4] = {0,0,0,0};
uint32_t ownerLookupLastSeen = 0;
// PN532 I2C dapat sesekali kehilangan satu hasil polling walau kartu masih
// menempel. Jangan reset timer stabil hanya karena satu pembacaan miss.
constexpr uint32_t kNfcPollIntervalMs = 100;
constexpr uint32_t kCardAbsentGraceMs = 500;
uint32_t lastNfcPoll = 0, lastCardSeen = 0;
CardState candidateState = CardState::None;

uint8_t rxHeader[2] = {0,0}; uint8_t rxSyncUsed = 0, rxHeaderUsed = 0;
uint16_t rxExpected = 0, rxUsed = 0; char rxPayload[257] = {};

const char *operationCode() {
  switch (bridgeOperation) {
    case BridgeOperation::MasterEnroll: return "master_enroll";
    case BridgeOperation::MasterReset: return "master_reset";
    case BridgeOperation::PersoArmed: return "perso_armed";
    case BridgeOperation::PersoReview: return "perso_review";
    default: return "idle";
  }
}
void sendJson(const char *json) {
  const size_t size = strnlen(json, 250);
  const uint8_t prefix[2] = {static_cast<uint8_t>(size >> 8), static_cast<uint8_t>(size)};
  bridgeSerial.write(prefix, 2); bridgeSerial.write(reinterpret_cast<const uint8_t *>(json), size);
}
void emitEvent(const char *type, const char *code) {
  char json[251]{};
  // Profil wajib ikut pada setiap event. Aplikasi desktop hanya menerima
  // profil ini, sehingga perangkat serial lain tidak bisa dianggap alat Perso.
  std::snprintf(json, sizeof(json), "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"transport\":\"stm32_char\",\"type\":\"%s\",\"code\":\"%s\",\"nfc_ready\":%s,\"master_registered\":%s,\"session_open\":%s,\"operation\":\"%s\",\"card_session\":%lu}",
                type, code, nfcReady ? "true" : "false", masterSet ? "true" : "false", sessionUnlocked ? "true" : "false", operationCode(), static_cast<unsigned long>(cardSession));
  sendJson(json);
}
void emitRemovalResult(const char *code, uint32_t cardReference) {
  char json[251]{};
  std::snprintf(json, sizeof(json), "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"transport\":\"stm32_char\",\"type\":\"result\",\"code\":\"%s\",\"card_reference\":%lu,\"nfc_ready\":%s,\"master_registered\":%s,\"session_open\":%s,\"operation\":\"%s\",\"card_session\":%lu}",
                code, static_cast<unsigned long>(cardReference), nfcReady ? "true" : "false",
                masterSet ? "true" : "false", sessionUnlocked ? "true" : "false",
                operationCode(), static_cast<unsigned long>(cardSession));
  sendJson(json);
}
void bridgeProgress(const char *code) { emitEvent("progress", code); }
void emitStatus(const char *code) {
  if (std::strcmp(code, "perso_ready") != 0) { emitEvent("status", code); return; }
  char json[251]{};
  std::snprintf(json, sizeof(json), "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"transport\":\"stm32_char\",\"card_format\":\"compact_v1\",\"type\":\"status\",\"code\":\"perso_ready\",\"nfc_ready\":%s,\"master_registered\":%s,\"session_open\":%s,\"operation\":\"%s\",\"card_session\":%lu}",
                nfcReady ? "true" : "false", masterSet ? "true" : "false", sessionUnlocked ? "true" : "false", operationCode(), static_cast<unsigned long>(cardSession));
  sendJson(json);
}
void emitTechnicalStatus(const char *code) {
  char json[180]{};
  std::snprintf(json, sizeof(json), "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"type\":\"technical\",\"code\":\"%s\",\"nfc_ready\":%s,\"session_open\":%s}",
                code, nfcReady ? "true" : "false", sessionUnlocked ? "true" : "false");
  sendJson(json);
}
void emitTechnicalScanSummary(uint8_t readable, uint8_t restricted) {
  char json[190]{};
  std::snprintf(json, sizeof(json), "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"type\":\"technical\",\"code\":\"scan_summary\",\"readable\":%u,\"restricted\":%u}", readable, restricted);
  sendJson(json);
}
void emitCardQuality(uint8_t success, uint8_t attempts) {
  char json[180]{};
  std::snprintf(json, sizeof(json), "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"type\":\"technical\",\"code\":\"card_quality\",\"success\":%u,\"attempts\":%u,\"average_ms\":0,\"source\":\"auto\"}", success, attempts);
  sendJson(json);
}
void emitWalletSlot(CardState state) {
  const char *slot = state == CardState::Blank ? "ready" :
    state == CardState::LegacyPersonalized ? "legacy_ready" :
    state == CardState::SecurePersonalized ? "already_used" : "unavailable";
  char json[180]{};
  std::snprintf(json, sizeof(json), "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"type\":\"technical\",\"code\":\"wallet_slot\",\"state\":\"%s\",\"sector\":2,\"block\":8}", slot);
  sendJson(json);
}
void emitOwnerLookup(const char *code, uint32_t cardReference = 0) {
  char json[251]{};
  if (cardReference != 0) {
    std::snprintf(json, sizeof(json), "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"type\":\"owner_lookup\",\"code\":\"%s\",\"card_reference\":%lu,\"nfc_ready\":%s,\"session_open\":%s}",
                  code, static_cast<unsigned long>(cardReference), nfcReady ? "true" : "false", sessionUnlocked ? "true" : "false");
  } else {
    std::snprintf(json, sizeof(json), "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"type\":\"owner_lookup\",\"code\":\"%s\",\"nfc_ready\":%s,\"session_open\":%s}",
                  code, nfcReady ? "true" : "false", sessionUnlocked ? "true" : "false");
  }
  sendJson(json);
}
void emitTechnicalBlock(uint8_t block, const char *state, const uint8_t *data) {
  const bool trailer = (block % 4u) == 3u;
  const bool manufacturer = block == 0;
  char hex[33]{};
  if (data && !trailer && !manufacturer) for (uint8_t i = 0; i < 16; ++i) std::snprintf(hex + (i * 2), 3, "%02X", data[i]);
  const char *kind = trailer ? "trailer_protected" : manufacturer ? "manufacturer_masked" : "data";
  char json[250]{};
  std::snprintf(json, sizeof(json), "{\"v\":1,\"profile\":\"smartdispenser_perso\",\"type\":\"technical\",\"code\":\"scan_block\",\"sector\":%u,\"block\":%u,\"kind\":\"%s\",\"state\":\"%s\",\"data\":\"%s\"}", block / 4u, block, kind, state, hex);
  sendJson(json);
}
void resetCandidate() { candidatePresent = candidateReady = false; candidateState = CardState::None; candidateSince = 0; lastCardSeen = 0; }
void technicalScan(const uint8_t uid[4]);
void cardQualityTest(const uint8_t uid[4]);
CardState readOnlyWalletProbe(uint8_t uid[4]);
void serviceCardPresence(uint32_t now);
bool commandIs(const char *payload, const char *type) {
  char expected[64]{}; std::snprintf(expected, sizeof(expected), "\"type\":\"%s\"", type);
  return std::strstr(payload, expected) != nullptr;
}
bool readCardReference(const char *payload, uint32_t &value) {
  const char *field = std::strstr(payload, "\"card_reference\":");
  if (!field) return false;
  field += std::strlen("\"card_reference\":");
  char *end = nullptr;
  const unsigned long parsed = std::strtoul(field, &end, 10);
  if (end == field || parsed == 0 || parsed > 0xFFFFFFFFul) return false;
  value = static_cast<uint32_t>(parsed);
  return true;
}
void rejectCommand(const char *code) { emitEvent("error", code); }
void handleCommand(const char *payload) {
  // The frame is length-bounded and every action below is explicitly
  // allow-listed. Do not reject a valid command merely because the CH340
  // UART path has damaged the optional leading version field in JSON.
  if (std::strstr(payload, "\"type\":") == nullptr) { rejectCommand("bad_command"); return; }
  const uint32_t now = millis();
  if (commandIs(payload, "status_request")) { emitStatus("perso_ready"); return; }
  if (commandIs(payload, "cancel")) { bridgeOperation = BridgeOperation::Idle; resetCandidate(); emitStatus("cancelled"); return; }
  if (commandIs(payload, "session_lock")) {
    sessionUnlocked = false; bridgeOperation = BridgeOperation::Idle; resetCandidate();
    awaitingRemoval = true; std::memcpy(awaitingRemovalUid, masterUid, 4); awaitingRemovalAnnounced = false;
    emitStatus("session_locked"); return;
  }
  if (commandIs(payload, "card_test_start")) {
    ownerLookupMode = false; ownerLookupPresent = false; ownerLookupLastSeen = 0;
    cardTestMode = true; cardTestPresent = false; cardTestLastSeen = 0;
    emitStatus("card_test_ready"); return;
  }
  if (commandIs(payload, "card_test_stop")) {
    cardTestMode = false; cardTestPresent = false; cardTestLastSeen = 0;
    emitStatus("card_test_stopped"); return;
  }
  if (commandIs(payload, "owner_lookup_start")) {
    cardTestMode = false; cardTestPresent = false; cardTestLastSeen = 0;
    ownerLookupMode = true; ownerLookupPresent = false; ownerLookupLastSeen = 0;
    emitStatus("owner_lookup_ready"); return;
  }
  if (commandIs(payload, "owner_lookup_stop")) {
    ownerLookupMode = false; ownerLookupPresent = false; ownerLookupLastSeen = 0;
    emitStatus("owner_lookup_stopped"); return;
  }
  // Explicit diagnostic probe. Normal card detection is owned by the STM32
  // polling loop below, so desktop commands can never race an I2C read.
  if (commandIs(payload, "card_probe")) {
    if (!nfcReady) { rejectCommand("nfc_unavailable"); return; }
    serviceCardPresence(now); return;
  }
  if (commandIs(payload, "technical_scan")) {
    if (!candidatePresent) { rejectCommand("technical_scan_card_required"); return; }
    technicalScan(candidateUid); return;
  }
  if (commandIs(payload, "card_quality_test")) {
    if (!candidatePresent) { rejectCommand("card_quality_card_required"); return; }
    cardQualityTest(candidateUid); return;
  }
  if (commandIs(payload, "register_master_begin")) {
    if (masterSet) { rejectCommand("master_already_registered"); return; }
    bridgeOperation = BridgeOperation::MasterEnroll; operationSince = now; resetCandidate(); emitStatus("master_enroll_wait_card"); return;
  }
  if (commandIs(payload, "register_master_commit")) {
    if (bridgeOperation != BridgeOperation::MasterEnroll || !candidatePresent || now - candidateSince < 10000) { rejectCommand("master_hold_incomplete"); return; }
    saveMaster(candidateUid); sessionUnlocked = true; bridgeOperation = BridgeOperation::Idle; std::memcpy(awaitingRemovalUid, candidateUid, 4); awaitingRemoval = true; awaitingRemovalAnnounced = false; emitEvent("result", "master_registered"); return;
  }
  if (commandIs(payload, "reset_master_begin")) {
    if (!masterSet) { rejectCommand("master_not_registered"); return; }
    bridgeOperation = BridgeOperation::MasterReset; operationSince = now; emitStatus("master_reset_hold"); return;
  }
  if (commandIs(payload, "reset_master_commit")) {
    if (bridgeOperation != BridgeOperation::MasterReset || now - operationSince < 10000) { rejectCommand("reset_hold_incomplete"); return; }
    waterdispenser_esp32::updateStorage(kEepromMasterFlag, 0); masterSet = sessionUnlocked = false; bridgeOperation = BridgeOperation::Idle; emitEvent("result", "master_reset"); return;
  }
  if (commandIs(payload, "perso_arm")) {
    if (!sessionUnlocked) { rejectCommand("master_session_required"); return; }
    bridgeOperation = BridgeOperation::PersoArmed; resetCandidate(); emitStatus("perso_wait_card"); return;
  }
  if (commandIs(payload, "perso_commit")) {
    const bool migratable = candidateState == CardState::LegacyPersonalized;
    if (bridgeOperation != BridgeOperation::PersoReview || !candidatePresent || !candidateReady ||
        (candidateState != CardState::Blank && !migratable)) { rejectCommand("perso_not_ready"); return; }
    uint32_t cardReference = 0;
    if (!readCardReference(payload, cardReference)) { rejectCommand("card_reference_required"); return; }
    bridgeProgress("start");
    const bool ok = personalizeCard(candidateUid, cardReference, migratable);
    bridgeOperation = BridgeOperation::Idle; candidateReady = false; awaitingRemoval = true; awaitingRemovalAnnounced = false; std::memcpy(awaitingRemovalUid, candidateUid, 4);
    emitEvent("result", ok ? "perso_success" : "perso_failed"); return;
  }
  if (commandIs(payload, "perso_remove")) {
    if (!sessionUnlocked || bridgeOperation != BridgeOperation::PersoReview || !candidatePresent ||
        !candidateReady || candidateState != CardState::SecurePersonalized) {
      rejectCommand("perso_remove_not_ready"); return;
    }
    uint32_t cardReference = 0;
    const bool ok = removePersonalization(candidateUid, cardReference);
    bridgeOperation = BridgeOperation::Idle; candidateReady = false; awaitingRemoval = true;
    awaitingRemovalAnnounced = false; std::memcpy(awaitingRemovalUid, candidateUid, 4);
    emitRemovalResult(ok ? "perso_removed" : "perso_remove_failed", cardReference); return;
  }
  rejectCommand("command_not_allowed");
}
void serviceBridgeInput() {
  static bool compactCommitPending = false;
  static uint8_t compactCommitUsed = 0;
  static char compactCommitHex[9]{};
  while (bridgeSerial.available() > 0) {
    const uint8_t byte = static_cast<uint8_t>(bridgeSerial.read());
    // Compact fallback transport for the CH340 UART path. A leading '!' is a
    // parser reset delimiter; the following uppercase byte maps to exactly
    // one allow-listed desktop action. NFC/I2C code is not involved here.
    if (byte == '!') {
      rxSyncUsed = rxHeaderUsed = 0; rxUsed = rxExpected = 0;
      compactCommitPending = false; compactCommitUsed = 0;
      continue;
    }
    if (compactCommitPending) {
      const bool hexDigit = (byte >= '0' && byte <= '9') || (byte >= 'A' && byte <= 'F');
      if (hexDigit && compactCommitUsed < 8) {
        compactCommitHex[compactCommitUsed++] = static_cast<char>(byte);
        continue;
      }
      if (byte == '\n' && compactCommitUsed == 8) {
        compactCommitHex[8] = 0;
        const unsigned long reference = std::strtoul(compactCommitHex, nullptr, 16);
        char commitPayload[80]{};
        std::snprintf(commitPayload, sizeof(commitPayload),
          "{\"v\":1,\"type\":\"perso_commit\",\"card_reference\":%lu}", reference);
        compactCommitPending = false; compactCommitUsed = 0;
        handleCommand(commitPayload);
        continue;
      }
      compactCommitPending = false; compactCommitUsed = 0;
      rejectCommand("compact_commit_invalid");
      continue;
    }
    if (rxSyncUsed == 0) {
      const char *compact = nullptr;
      switch (byte) {
        case 'S': compact = "{\"v\":1,\"type\":\"status_request\"}"; break;
        case 'L': compact = "{\"v\":1,\"type\":\"session_lock\"}"; break;
        case 'X': compact = "{\"v\":1,\"type\":\"cancel\"}"; break;
        case 'T': compact = "{\"v\":1,\"type\":\"technical_scan\"}"; break;
        case 'Q': compact = "{\"v\":1,\"type\":\"card_quality_test\"}"; break;
        case 'C': compact = "{\"v\":1,\"type\":\"card_probe\"}"; break;
        case 'Y': compact = "{\"v\":1,\"type\":\"card_test_start\"}"; break;
        case 'Z': compact = "{\"v\":1,\"type\":\"card_test_stop\"}"; break;
        case 'U': compact = "{\"v\":1,\"type\":\"owner_lookup_start\"}"; break;
        case 'V': compact = "{\"v\":1,\"type\":\"owner_lookup_stop\"}"; break;
        case 'E': compact = "{\"v\":1,\"type\":\"register_master_begin\"}"; break;
        case 'R': compact = "{\"v\":1,\"type\":\"register_master_commit\"}"; break;
        case 'B': compact = "{\"v\":1,\"type\":\"reset_master_begin\"}"; break;
        case 'D': compact = "{\"v\":1,\"type\":\"reset_master_commit\"}"; break;
        case 'A': compact = "{\"v\":1,\"type\":\"perso_arm\"}"; break;
        case 'P': compactCommitPending = true; compactCommitUsed = 0; continue;
        case 'W': compact = "{\"v\":1,\"type\":\"perso_remove\"}"; break;
      }
      if (compact) { handleCommand(compact); continue; }
    }
    // Match the desktop bridge framing: A5 5A + 16-bit JSON length.
    if (rxSyncUsed == 0) { if (byte == 0xA5) rxSyncUsed = 1; continue; }
    if (rxSyncUsed == 1) { rxSyncUsed = byte == 0x5A ? 2 : (byte == 0xA5 ? 1 : 0); continue; }
    if (rxHeaderUsed == 0) {
      // Desktop uses a 16-bit big-endian length. On this CH340-to-STM32
      // path the leading NUL byte of short frames can be lost, so accept both
      // 00,len and the surviving one-byte len form. All bridge frames are
      // limited to 256 bytes either way.
      if (byte == 0) { rxHeaderUsed = 1; continue; }
      rxExpected = byte; rxUsed = 0; rxHeaderUsed = 2;
      continue;
    } else if (rxHeaderUsed == 1) {
      rxExpected = byte; rxUsed = 0; rxHeaderUsed = 2;
      continue;
    }
    if (rxExpected == 0 || rxExpected > 256) { rxSyncUsed = rxHeaderUsed = 0; rejectCommand("frame_length_invalid"); continue; }
    rxPayload[rxUsed++] = static_cast<char>(byte);
    if (rxUsed == rxExpected) { rxPayload[rxUsed] = 0; handleCommand(rxPayload); rxSyncUsed = rxHeaderUsed = 0; rxUsed = rxExpected = 0; }
  }
}

// The following Technical Debug functions use the existing PN532 object and
// existing I2C polling setup unchanged. They only authenticate/read; they do
// not write card data, keys, trailers, or change the NFC configuration.
bool authenticateDiagnosticSector(uint8_t uid[4], uint8_t block) {
  uint8_t key[6]{};
  if ((block / 4u) == (kWalletBlock / 4u)) std::memcpy(key, kCardKeyA, 6);
  else std::memset(key, 0xFF, 6);  // normal public factory Key A only
  return reselectCard(uid) && nfc.mifareclassic_AuthenticateBlock(uid, 4, block, 0, key);
}

CardState readOnlyWalletProbe(uint8_t uid[4]) {
  uint8_t systemKey[6]; std::memcpy(systemKey, kCardKeyA, 6);
  if (reselectCard(uid) && nfc.mifareclassic_AuthenticateBlock(uid, 4, kWalletBlock, 0, systemKey)) {
    uint8_t wallet[16]{};
    if (!nfc.mifareclassic_ReadDataBlock(kWalletBlock, wallet)) return CardState::Foreign;
    if (!isBlankBlock(wallet)) return classifyProtectedWallet(uid, wallet);
    uint8_t metadata[16]{};
    return classifyBlankWallet(metadata);
  }
  uint8_t factoryKey[6]; std::memset(factoryKey, 0xFF, 6);
  if (!reselectCard(uid) || !nfc.mifareclassic_AuthenticateBlock(uid, 4, kWalletBlock, 0, factoryKey)) return CardState::Foreign;
  uint8_t data[16]{};
  if (!nfc.mifareclassic_ReadDataBlock(kWalletBlock, data) || !isBlankBlock(data)) return CardState::Foreign;
  uint8_t metadata[16]{};
  return classifyBlankWallet(metadata);
}

void cardQualityTest(const uint8_t inputUid[4]) {
  constexpr uint8_t kAttempts = 10;
  uint8_t uid[4]{}; std::memcpy(uid, inputUid, 4);
  uint8_t success = 0;
  emitTechnicalStatus("quality_started");
  for (uint8_t attempt = 0; attempt < kAttempts; ++attempt) {
    if (!reselectCard(uid)) { emitCardQuality(success, attempt + 1); return; }
    ++success;
    delay(70);
  }
  emitCardQuality(success, kAttempts);
  if (success == kAttempts) emitWalletSlot(readOnlyWalletProbe(uid));
}

void technicalScan(const uint8_t inputUid[4]) {
  if (!sessionUnlocked) { rejectCommand("master_session_required"); return; }
  uint8_t uid[4]{}; std::memcpy(uid, inputUid, 4);
  uint8_t readable = 0, restricted = 0;
  emitTechnicalStatus("scan_started");
  for (uint8_t sector = 0; sector < 16; ++sector) {
    const uint8_t first = sector * 4u;
    const bool authenticated = authenticateDiagnosticSector(uid, first);
    for (uint8_t offset = 0; offset < 4; ++offset) {
      const uint8_t block = first + offset;
      if (offset == 3 || block == 0) continue; // masked locally; no serial dump
      uint8_t data[16]{};
      const bool readOk = authenticated && nfc.mifareclassic_ReadDataBlock(block, data);
      // The full map is intentionally scanned on the board but no longer
      // streamed as 64 large serial events. That burst could bury the final
      // scan result on the CH340 link and makes the operator UI appear to
      // restart without an explanation. Only safe aggregate counts travel to
      // the app; keys, raw blocks and trailers remain local to the board.
      if (readOk) ++readable; else ++restricted;
    }
  }
  emitTechnicalScanSummary(readable, restricted);
  emitTechnicalStatus("scan_complete");
}
void serviceCardPresence(uint32_t now) {
  uint8_t uid[7]{}; uint8_t uidLen = 0;
  const bool present = nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &uidLen) && uidLen == 4;
  if (cardTestMode) {
    if (!present) {
      if (cardTestPresent && cardTestLastSeen != 0 && now - cardTestLastSeen < kCardAbsentGraceMs) return;
      if (cardTestPresent) emitEvent("card_test", "removed");
      cardTestPresent = false; cardTestLastSeen = 0;
      return;
    }
    cardTestLastSeen = now;
    if (!cardTestPresent || std::memcmp(uid, cardTestUid, 4) != 0) {
      std::memcpy(cardTestUid, uid, 4); cardTestPresent = true;
      emitEvent("card_test", "detected");
    }
    return;
  }
  if (ownerLookupMode) {
    if (!present) {
      if (ownerLookupPresent && ownerLookupLastSeen != 0 && now - ownerLookupLastSeen < kCardAbsentGraceMs) return;
      if (ownerLookupPresent) emitOwnerLookup("removed");
      ownerLookupPresent = false; ownerLookupLastSeen = 0;
      return;
    }
    ownerLookupLastSeen = now;
    if (!ownerLookupPresent || std::memcmp(uid, ownerLookupUid, 4) != 0) {
      std::memcpy(ownerLookupUid, uid, 4); ownerLookupPresent = true;
      uint8_t selectedUid[4]{}; std::memcpy(selectedUid, uid, 4);
      uint8_t key[6]; std::memcpy(key, kCardKeyA, 6);
      uint8_t wallet[16]{}, metadataBlock[16]{};
      smartdispenser::compact_card::Metadata metadata{};
      if (reselectCard(selectedUid) &&
          nfc.mifareclassic_AuthenticateBlock(selectedUid, 4, kWalletBlock, 0, key) &&
          nfc.mifareclassic_ReadDataBlock(kWalletBlock, wallet) && isWalletV2(wallet) &&
          nfc.mifareclassic_ReadDataBlock(kMetadataBlock, metadataBlock)) {
        if (smartdispenser::compact_card::isBlank(metadataBlock)) emitOwnerLookup("legacy_card");
        else if (smartdispenser::compact_card::decodeAndVerify(selectedUid, wallet, metadataBlock, metadata))
          emitOwnerLookup("identified", metadata.cardReference);
        else emitOwnerLookup("unrecognized");
      } else {
        emitOwnerLookup("unrecognized");
      }
    }
    return;
  }
  if (!present) {
    // Abaikan kehilangan singkat agar kartu yang diam tidak terlihat
    // putus-nyambung di dashboard atau gagal memenuhi 3/10 detik stabil.
    if ((candidatePresent || awaitingRemoval) && lastCardSeen != 0 && now - lastCardSeen < kCardAbsentGraceMs) return;
    if (candidatePresent) emitEvent("card", "removed");
    resetCandidate(); awaitingRemoval = false; awaitingRemovalAnnounced = false; return;
  }
  lastCardSeen = now;
  if (awaitingRemoval && std::memcmp(uid, awaitingRemovalUid, 4) == 0) {
    // Jangan membanjiri serial dengan status yang sama pada setiap polling
    // PN532. Satu event cukup sampai kartu benar-benar diangkat.
    if (!awaitingRemovalAnnounced) { awaitingRemovalAnnounced = true; emitStatus("remove_card_before_next"); }
    return;
  }
  const bool isMaster = masterSet && std::memcmp(uid, masterUid, 4) == 0;
  if (isMaster && bridgeOperation == BridgeOperation::Idle) {
    if (!sessionUnlocked) { sessionUnlocked = true; emitEvent("master", "session_opened"); }
    return;
  }
  // A newly detected non-master card starts the same read-only Technical
  // Debug flow as ESP32. This does not alter the I2C setup or reader polling.
  if (bridgeOperation == BridgeOperation::Idle) {
    if (!candidatePresent || std::memcmp(uid, candidateUid, 4) != 0) {
      std::memcpy(candidateUid, uid, 4); candidatePresent = true; candidateReady = false;
      candidateState = CardState::None; candidateSince = now; ++cardSession;
      emitEvent("card", "detected");
    }
    return;
  }
  if (bridgeOperation != BridgeOperation::MasterEnroll && bridgeOperation != BridgeOperation::PersoArmed && bridgeOperation != BridgeOperation::PersoReview) return;
  if (!candidatePresent || std::memcmp(uid, candidateUid, 4) != 0) {
    std::memcpy(candidateUid, uid, 4); candidatePresent = true; candidateReady = false; candidateState = CardState::None; candidateSince = now; ++cardSession; emitEvent("card", "detected"); return;
  }
  if (bridgeOperation == BridgeOperation::MasterEnroll) {
    if (now - candidateSince >= 10000 && !candidateReady) { candidateReady = true; emitStatus("master_hold_ready"); }
    return;
  }
  if (bridgeOperation == BridgeOperation::PersoArmed && now - candidateSince >= 3000) {
    bridgeProgress("precheck"); candidateState = probeCard(candidateUid, 4); candidateReady = true; bridgeOperation = BridgeOperation::PersoReview;
    emitEvent("precheck", candidateState == CardState::Blank ? "blank" :
      candidateState == CardState::LegacyPersonalized ? "legacy_personalized" :
      candidateState == CardState::SecurePersonalized ? "already_personalized" : "foreign_or_invalid");
  }
}
void setup() {
  if (kLedPin >= 0) { pinMode(kLedPin, OUTPUT); digitalWrite(kLedPin, kLedActiveLow ? HIGH : LOW); }
  if (kIndicatorPb0Pin >= 0) { pinMode(kIndicatorPb0Pin, OUTPUT); digitalWrite(kIndicatorPb0Pin, HIGH); }
  if (kIndicatorPb1Pin >= 0 && kIndicatorPb1Pin != kIndicatorPb0Pin) { pinMode(kIndicatorPb1Pin, OUTPUT); digitalWrite(kIndicatorPb1Pin, HIGH); }
  if (!waterdispenser_esp32::beginStorage()) {
    while (true) delay(1000);
  }
  waterdispenser_esp32::beginBridge(bridgeSerial);
  waterdispenser_esp32::beginI2c();
  Wire.beginTransmission(kLcdI2cAddress); if (Wire.endTransmission() == 0) { lcd.begin(16, 2, Wire); lcdReady = lcd.isConnected(); lcd.setBacklight(255); }
  nfcReady = initializeNfc(); loadMaster();
  lcdShow("PERSO VIA PC", nfcReady ? "HUBUNGKAN APP" : "NFC TIDAK SIAP");
  emitStatus(nfcReady ? "boot_ready" : "nfc_unavailable");
}
void loop() {
  serviceBridgeInput();
  const uint32_t now = millis();
  if (!nfcReady && now - nfcLastInitAttempt >= 3000) {
    nfcReady = initializeNfc();
    if (nfcReady) {
      lcdShow("PERSO VIA PC", "NFC PULIH");
      emitStatus("nfc_recovered");
    }
  }
  // The PN532 I2C board has no IRQ connection. Keep one reader owner here,
  // polling at a fixed short interval; the desktop only consumes its events.
  // This is the proven Perso-board path and avoids overlapping reads from COM3.
  if (nfcReady && now - lastNfcPoll >= kNfcPollIntervalMs) {
    lastNfcPoll = now;
    serviceCardPresence(now);
  }
}
