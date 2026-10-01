#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace smartdispenser { namespace compact_card {

constexpr uint8_t kWalletBlock = 8;
constexpr uint8_t kJournalBlock = 10;
constexpr uint8_t kTrailerBlock = 11;
constexpr uint8_t kWalletMagic = 0xD7;
constexpr uint8_t kWalletVersion = 2;
constexpr uint8_t kScheduleNone = 0;
constexpr uint8_t kSchedulePagi = 1;
constexpr uint8_t kScheduleSiang = 2;
constexpr uint8_t kScheduleSore = 3;
constexpr uint8_t kMaximumBalanceLitres = 100;
constexpr uint8_t kDailyQuotaLitres = 30;

struct Wallet {
  uint8_t available = 0;
  bool permitted = false;
  uint8_t schedule = kScheduleNone;
  uint16_t day = 0;
  uint8_t usedToday = 0;
  uint8_t reserved = 0;
};

inline uint16_t walletCrc16Ccitt(const uint8_t *data, size_t length) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < length; ++i) {
    crc ^= static_cast<uint16_t>(data[i]) << 8;
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc & 0x8000)
        ? static_cast<uint16_t>((crc << 1) ^ 0x1021)
        : static_cast<uint16_t>(crc << 1);
    }
  }
  return crc;
}

inline void encodeWallet(const Wallet &wallet, uint8_t block[16]) {
  std::memset(block, 0, 16);
  block[0] = kWalletMagic;
  block[1] = kWalletVersion;
  block[2] = wallet.permitted ? 1 : 0;
  block[3] = wallet.available;
  block[4] = wallet.schedule;
  block[5] = static_cast<uint8_t>(wallet.day >> 8);
  block[6] = static_cast<uint8_t>(wallet.day);
  block[7] = wallet.usedToday;
  block[8] = wallet.reserved;
  const uint16_t crc = walletCrc16Ccitt(block, 9);
  block[9] = static_cast<uint8_t>(crc >> 8);
  block[10] = static_cast<uint8_t>(crc);
}

inline bool decodeWallet(const uint8_t block[16], Wallet &wallet) {
  if (!block || block[0] != kWalletMagic || block[1] != kWalletVersion ||
      block[2] > 1 || block[3] > kMaximumBalanceLitres ||
      block[4] > kScheduleSore || block[7] > kDailyQuotaLitres ||
      block[8] > kDailyQuotaLitres) return false;
  for (uint8_t i = 11; i < 16; ++i) if (block[i] != 0) return false;
  const uint16_t saved = static_cast<uint16_t>((block[9] << 8) | block[10]);
  if (walletCrc16Ccitt(block, 9) != saved) return false;
  wallet.permitted = block[2] != 0;
  wallet.available = block[3];
  wallet.schedule = block[4];
  wallet.day = static_cast<uint16_t>((block[5] << 8) | block[6]);
  wallet.usedToday = block[7];
  wallet.reserved = block[8];
  return true;
}

inline bool walletEqual(const Wallet &left, const Wallet &right) {
  return left.available == right.available &&
         left.permitted == right.permitted &&
         left.schedule == right.schedule &&
         left.day == right.day &&
         left.usedToday == right.usedToday &&
         left.reserved == right.reserved;
}

} }  // namespace smartdispenser::compact_card
