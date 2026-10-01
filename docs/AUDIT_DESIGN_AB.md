# Audit kesesuaian design A/B

Status: belum memenuhi syarat selesai penuh. Matriks ini bukan sertifikasi
perangkat atau pengganti checklist pengujian pengguna.

| Persyaratan | Bukti implementasi / pemeriksaan | Status |
|---|---|---|
| Profil A/B, B tanpa dispensing | `ab_main.cpp`, environment normal dan servis terpisah | Implementasi; bench belum |
| Classic, dua tipe kartu, UID tidak di LCD | `ab_classic_cards`, `ab_classic_master`, `Application::frame` | Implementasi; keaslian/capacity kartu fisik belum |
| KDF terikat master + pelanggan + secret, AEAD | `ab_crypto`, `ab_device_keys`, `ab_card_format`, fixture crypto host | Implementasi/simulasi; bukan AES native Classic |
| Nonce persisten dan penolakan konfigurasi invalid | `ab_nonce`, `ab_configuration_store`, `ab_security_boot`, tes provisioning | Implementasi/simulasi; EEPROM fisik belum |
| Master tunggal, enrollment 10s, registry persisten | `Application::enroll`, `ClassicMaster`, tes enrollment/retry | Implementasi/simulasi; tombol/RF fisik belum |
| Satu izin perubahan B, timeout/cancel, perso/status/top-up | `ab_application`, `ClassicCards`, tes B termasuk expiry browsing/edit, cancel, one-shot, batas 100 L | Implementasi dan model teruji untuk skenario tersebut; keseluruhan kombinasi menu masih diaudit |
| Pencairan manual bounded, peringatan pemeriksaan | `InspectFrozen`, `Action::Release`, tes pencairan parsial | Implementasi/simulasi; tidak membuktikan air belum keluar |
| Saldo 100 L total, pilihan 5/10/20 dan 1–4, reserve sebelum valve | `ab_wallet`, `Application::start`, tes saldo/recovery | Implementasi/simulasi |
| Pulsa/checkpoint/target/stop, no-flow tetap terbuka sesuai keputusan | `ab_main`, `Application::tick`, tes 99/100/199/523/no-flow | Implementasi; latensi kontak/debounce/frekuensi harus diukur |
| Hilang kartu, countdown, freeze, lintas A/B, jurnal penuh | `ab_application`, journal, model lintas peran | Implementasi/simulasi; audit fault fisik belum |
| LCD center, laporan, progress, LED | `frame`, `draw`, `ab_indicators`, ISR flow | Implementasi; visual/latensi fisik belum |
| Provisioning tiga alat dan metadata master ke A | bundle/package/service scripts, `ab_master_report` | Alat tersedia; UART dan penempatan credential fisik belum diuji |
| Satu master tetap, tanpa penggantian/migrasi | Pengguna membatalkan kebutuhan migrasi; registry dan konfigurasi committed menolak penggantian | Tidak lagi menjadi pekerjaan migrasi; penolakan master kedua tetap wajib diuji |
| Datasheet membedakan spesifikasi dan bukti uji | `TECHNICAL_DATASHEET_NFC_AB.md` | Draft diperbarui; klaim hardware tetap belum diuji |

## Batas yang sudah disepakati, bukan fitur yang terbukti

MIFARE Classic dipilih pengguna. Anti-cloning/rollback offline dan pemisahan
debit-only tingkat chip yang semula menjadi kandidat DESFire tidak dapat diklaim
setara pada Classic. Kunci write data Classic pada A memungkinkan risiko
pemalsuan saldo jika board A/secret dikompromikan. MAC sah pada snapshot lama
bukan bukti snapshot itu paling baru. Risiko ini tidak ditutup dengan tes retry
API yang lulus.

## Pekerjaan yang masih menjadi tanggung jawab implementasi

1. Pertahankan master tunggal tetap sesuai keputusan terbaru pengguna;
   tidak ada migrasi, erase, atau enrollment ulang tersembunyi.
2. Lengkapi audit kombinasi menu, kegagalan komunikasi, penolakan write dan
   service workflow; periksa artefak paket serta batas stack/latensi software.
3. Pertahankan status kandidat sampai semua butir software selesai. Pengujian
   fisik diserahkan kepada pengguna sesuai arahan, dengan checklist terpisah.

## Larangan klaim selesai

Audit stack menemukan frame fungsi transaksi Classic hingga 1.088 byte, lebih
besar dari reservasi minimum legacy 1 KiB. Profil A/B kini menetapkan reservasi
8 KiB melalui simbol linker; profil legacy tetap memakai baseline. Simbol ELF
A/B diverifikasi `_Min_Stack_Size=0x2000`. STM32duino `_sbrk` yang dipakai membatasi
heap berdasarkan simbol ini. Ini bukan pengukuran seluruh call chain/interrupt
atau high-water; pengukuran runtime dan endurance masih ada di checklist.

Paket `candidate_classic_01` mendahului perbaikan laporan LCD dan reservasi stack
ini. Jangan menganggap paket tersebut sebagai artefak source terbaru; paket
final harus dibangun ulang dan diverifikasi dengan manifest baru.

Jumlah assertion, build berhasil, dan keberadaan firmware.bin tidak membuktikan
seluruh design terpenuhi. Tidak ada upload, pengisian credential produksi, hasil
kalibrasi, atau uji perangkat baru yang boleh disimpulkan dari matriks ini.
