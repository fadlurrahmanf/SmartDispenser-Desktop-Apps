# To Be Discussed — Card Identity, Lifecycle, and Security

## Status

**Format compact sudah diimplementasikan pada source kandidat dan lulus build,
tetapi belum di-upload atau dibuktikan pada kartu fisik.**

Dokumen ini mencatat topik desain untuk pembahasan berikutnya. Isinya bukan
bukti bahwa firmware Perso, Topup, Dispenser, format kartu, atau aplikasi
desktop sudah menerapkan fitur-fitur tersebut.

## Baseline fungsional saat ini

- Wallet V2 tetap menggunakan Sector 2, Block 8.
- Block 9 kandidat berisi `card_reference` uint32, transaction counter uint32,
  dan tag AES-CMAC 64-bit.
- Block 10 tetap kosong.
- Sector trailer berada pada Block 11.
- Data wallet memiliki CRC untuk mendeteksi kerusakan data yang tidak sengaja.
- CRC bukan autentikasi kriptografis dan tidak mencegah pemalsuan.
- Database mengalokasikan `card_reference` melalui AUTO_INCREMENT uint32 sebelum
  penulisan dan menyimpan bentuk operator `CARD-XXXXXXXX` setelah verifikasi.
- Data pribadi seperti NIK, nomor KK, nama, telepon, dan alamat hanya disimpan
  di database dan tidak boleh ditulis ke kartu.

## Topik keamanan yang perlu diputuskan

### 1. Identitas kartu anonim — source kandidat tersedia

- Format yang dipilih adalah integer uint32 unik dari database, bukan nilai acak.
- Jangan membentuk `card_reference` dari NIK, nomor KK, nomor telepon,
  nama pelanggan, atau data pribadi lainnya.
- Lokasi yang dipilih adalah Block 9; Block 8 tetap untuk wallet dan Block 10
  sengaja dibiarkan kosong.

### 2. Autentikasi data aplikasi — source kandidat tersedia

- Kandidat memakai AES-CMAC dengan secret 128-bit yang tidak dikirim ke desktop,
  database, log, atau kartu.
- MAC mencakup domain format, UID 4 byte, seluruh Block 8, `card_reference`, dan
  transaction counter.
- Tentukan apakah wallet juga dicakup MAC. Jika ya, Topup dan Dispenser harus
  menghitung ulang MAC setiap kali saldo atau status transaksi berubah.
- Tag yang dipilih 64-bit agar seluruh metadata muat dalam Block 9.

### 3. Replay dan cloning

- MAC saja tidak mencegah penyalinan ulang data valid yang lama.
- Kaji transaction counter, monotonic state, dan mekanisme sinkronisasi untuk
  mendeteksi rollback/replay.
- Kaji batas perlindungan UID binding karena UID MIFARE Classic tertentu dapat
  ditiru atau diemulasikan.

### 4. Key management

- Ganti Key A/Key B template dengan nilai acak setelah desain migrasi disetujui.
- Hindari satu key global untuk seluruh kartu; kaji key diversification per
  kartu dari master secret.
- Secret tidak boleh disimpan di Git, log, UI, database pelanggan, atau frame
  serial aplikasi desktop.
- Tentukan provisioning, backup, recovery, rotasi, pencabutan, serta
  perlindungan secret di firmware/perangkat.
- Perubahan key harus kompatibel dan terkoordinasi pada Perso, Topup, dan
  Dispenser agar kartu tidak kehilangan akses.

### 5. Lifecycle kartu

- Status yang perlu dibahas: `LOST`, `DAMAGED`, `REPLACED`, `REVOKED`, dan
  `INSPECTION_REQUIRED`.
- Tentukan bagaimana Dispenser menolak kartu hilang/dicabut ketika bekerja
  offline.
- Kaji blacklist lokal, sinkronisasi revocation list, atau validasi online.
- Riwayat kartu lama harus dipertahankan dan tidak dihapus dari database.

### 6. Pilihan teknologi kartu

- Dokumentasikan risiko bawaan Crypto1/MIFARE Classic.
- Untuk kebutuhan keamanan produksi yang lebih tinggi, evaluasi migrasi ke
  kartu dengan kriptografi modern, misalnya keluarga MIFARE DESFire.

## Gate sebelum upload dan penggunaan fisik

Implementasi baru hanya dilakukan setelah seluruh poin berikut disepakati:

1. Format byte kartu dan versioning.
2. Kompatibilitas Perso, Topup, dan Dispenser.
3. Strategi migrasi kartu yang sudah dipersonalisasi.
4. Penyimpanan dan rotasi secret.
5. Mekanisme anti-replay dan penanganan kartu hilang.
6. Uji recovery apabila penulisan terputus di tengah proses.
7. Test vector kriptografi dan uji interoperabilitas ketiga firmware.

## Batas keamanan yang masih To Be Discussed

- Key A/Key B MIFARE Classic masih template dan belum didiversifikasi per kartu.
- MAC tidak mengenkripsi saldo atau metadata; kerahasiaan/authenticated
  encryption masih belum diimplementasikan.
- Penulisan Block 8 lalu Block 9 belum atomik terhadap kehilangan daya/kartu.
- Counter pada kartu belum dibandingkan dengan counter tepercaya di server atau
  perangkat, sehingga perlindungan rollback/replay belum lengkap.
- Blacklist, kartu hilang, revocation, replacement, dan sinkronisasi dispenser
  offline belum diimplementasikan.
- Source/build bukan bukti interoperabilitas Perso, Topup, dan Dispenser pada
  kartu fisik; bukti tersebut memerlukan upload dan bench test terkontrol.
