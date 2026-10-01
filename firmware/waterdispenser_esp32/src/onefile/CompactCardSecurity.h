#pragma once

#include <AES.h>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <compact_card_secret.h>

namespace smartdispenser { namespace compact_card {

constexpr uint8_t kMetadataBlock = 9;
constexpr size_t kMetadataAuthenticatedBytes = 8;
constexpr size_t kMetadataTagBytes = 8;

struct Metadata {
  uint32_t cardReference = 0;
  uint32_t transactionCounter = 0;
};

inline void wipe(void *value, size_t size) {
  volatile uint8_t *bytes = static_cast<volatile uint8_t *>(value);
  while (size--) *bytes++ = 0;
}

inline void putBe32(uint8_t *out, uint32_t value) {
  out[0] = static_cast<uint8_t>(value >> 24);
  out[1] = static_cast<uint8_t>(value >> 16);
  out[2] = static_cast<uint8_t>(value >> 8);
  out[3] = static_cast<uint8_t>(value);
}

inline uint32_t getBe32(const uint8_t *in) {
  return (static_cast<uint32_t>(in[0]) << 24) |
         (static_cast<uint32_t>(in[1]) << 16) |
         (static_cast<uint32_t>(in[2]) << 8) |
         static_cast<uint32_t>(in[3]);
}

inline void doubleBlock(uint8_t block[16]) {
  const uint8_t high = block[0] >> 7;
  for (uint8_t i = 0; i < 15; ++i)
    block[i] = static_cast<uint8_t>((block[i] << 1) | (block[i + 1] >> 7));
  block[15] = static_cast<uint8_t>((block[15] << 1) ^ (0x87u & (0u - high)));
}

inline bool cmac128(const uint8_t key[16], const uint8_t *message, size_t size, uint8_t output[16]) {
  if (!key || !output || (!message && size)) return false;
  AES128 aes;
  if (!aes.setKey(key, 16)) return false;
  uint8_t subkey[16]{}, state[16]{}, block[16]{};
  aes.encryptBlock(subkey, subkey);
  doubleBlock(subkey);
  size_t remaining = size;
  while (remaining > 16) {
    for (uint8_t i = 0; i < 16; ++i) state[i] ^= message[i];
    aes.encryptBlock(state, state);
    message += 16;
    remaining -= 16;
  }
  if (remaining) std::memcpy(block, message, remaining);
  if (size == 0 || remaining < 16) {
    doubleBlock(subkey);
    block[remaining] = 0x80;
  }
  for (uint8_t i = 0; i < 16; ++i) state[i] ^= block[i] ^ subkey[i];
  aes.encryptBlock(output, state);
  wipe(subkey, sizeof(subkey));
  wipe(state, sizeof(state));
  wipe(block, sizeof(block));
  aes.clear();
  return true;
}

inline bool loadMacKey(uint8_t key[16]) {
  static const uint8_t label[16] = {
    'S','D','-','C','O','M','P','A','C','T','-','M','A','C','1',0
  };
  return cmac128(smartdispenser::compact_card_private::kMacSecret, label, sizeof(label), key);
}

inline bool makeTag(const uint8_t uid[4], const uint8_t wallet[16],
                    const uint8_t metadataPrefix[8], uint8_t tag[16]) {
  uint8_t input[32] = {'S','D','C','1'};
  std::memcpy(input + 4, uid, 4);
  std::memcpy(input + 8, wallet, 16);
  std::memcpy(input + 24, metadataPrefix, 8);
  uint8_t key[16]{};
  const bool ok = loadMacKey(key) && cmac128(key, input, sizeof(input), tag);
  wipe(key, sizeof(key));
  wipe(input, sizeof(input));
  return ok;
}

inline bool encode(const uint8_t uid[4], const uint8_t wallet[16], const Metadata &metadata,
                   uint8_t block[16]) {
  if (!uid || !wallet || !block || metadata.cardReference == 0) return false;
  putBe32(block, metadata.cardReference);
  putBe32(block + 4, metadata.transactionCounter);
  uint8_t tag[16]{};
  if (!makeTag(uid, wallet, block, tag)) return false;
  std::memcpy(block + 8, tag, kMetadataTagBytes);
  wipe(tag, sizeof(tag));
  return true;
}

inline bool decodeAndVerify(const uint8_t uid[4], const uint8_t wallet[16],
                            const uint8_t block[16], Metadata &metadata) {
  if (!uid || !wallet || !block) return false;
  const uint32_t reference = getBe32(block);
  if (reference == 0) return false;
  uint8_t expected[16]{};
  if (!makeTag(uid, wallet, block, expected)) return false;
  uint8_t difference = 0;
  for (uint8_t i = 0; i < kMetadataTagBytes; ++i) difference |= expected[i] ^ block[8 + i];
  wipe(expected, sizeof(expected));
  if (difference != 0) return false;
  metadata.cardReference = reference;
  metadata.transactionCounter = getBe32(block + 4);
  return true;
}

inline bool isBlank(const uint8_t block[16]) {
  bool zero = true, erased = true;
  for (uint8_t i = 0; i < 16; ++i) {
    zero &= block[i] == 0;
    erased &= block[i] == 0xFF;
  }
  return zero || erased;
}

}}
