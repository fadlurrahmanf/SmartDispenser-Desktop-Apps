# SmartDispenser

Repositori ini menyimpan baseline perangkat SmartDispenser berdasarkan skematik,
source EasyEDA, foto, dan firmware diagnostik yang tersedia. BOM, Gerber,
kontrak aplikasi produksi, serta bukti uji keselamatan dan endurance belum ada.

## Isi repositori

- `Schematic/BoardDispenser.pdf` - skematik board dispenser, rev. 1.0,
  tanggal 2026-08-21.
- `Schematic/STM32.pdf` - skematik modul STM32/radio, rev. 1.0,
  tanggal 2020-10-25.
- `Schematic/WiringSTM32.zip` - source EasyEDA modul STM32/radio yang
  mengonfirmasi jalur SWD pada modul.
- `Schematic/WiringDispenser.zip` - source EasyEDA board dispenser yang
  mengonfirmasi koneksi LCD I2C ke PB8/PB9.
- `Photo/` - foto board, reader RFID, posisi reader, solenoid/flowmeter,
  dan contoh catu daya.
- `docs/HARDWARE_BASELINE.md` - ringkasan fakta, batas bukti, risiko, dan
  pertanyaan terbuka dari artefak awal.
- `docs/FIRMWARE_READINESS.md` - audit gap firmware dan evidence gate menuju
  produksi.
- `docs/ARTIFACTS.sha256` - checksum SHA-256 untuk menjaga keterlacakan sembilan
  artefak awal.
- `AGENTS.md` - aturan kerja untuk perubahan selanjutnya.

## Baseline yang terverifikasi dari skematik

- Modul pengendali menggunakan keluarga STM32L071.
- Board dispenser menampilkan PN532 dan LCD1602 melalui I2C, input flow pada
  PA0, tiga tombol, UART, dua kanal relay latching, catu +5 V, dan regulator
  3,3 V.
- Skematik modul MCU menampilkan STM32L071RBT6, antarmuka SWD, UART, I2C, SPI,
  dan radio RFM69CW.

Detail pin, perbedaan antar-artefak, dan hal yang belum terbukti dicatat di
[`docs/HARDWARE_BASELINE.md`](docs/HARDWARE_BASELINE.md).

Integritas file sumber dapat diperiksa dengan manifest
[`docs/ARTIFACTS.sha256`](docs/ARTIFACTS.sha256).

## Status firmware

- `firmware/blink_pc13/` adalah uji LED PC13 aktif-LOW yang telah dibangun dan
  diverifikasi melalui ST-Link pada 2026-09-02.
- `firmware/lcd_i2c_16x2/` adalah uji LCD I2C 16x2 pada PB8/PB9. Alamat dan
  mapping backpack LCD masih asumsi yang dijelaskan pada README firmware; uji
  visual di unit tetap diperlukan.
- `firmware/smartdispenser_firmware/` adalah baseline diagnostik LCD dan NFC berbasis
  library umum dengan transport I2C bounded, state fault/retry, card-presence
  policy, kontrak pin terpusat, primitive debounce/pulse hardware-free,
  56 native regression tests, reset-cause log, verifier reproducible, dan dua
  profil pull-up. Kedua profil clean-build sukses pada 2026-09-02, tetapi
  revisi terbaru belum di-flash atau diuji ulang pada hardware.

Status keseluruhan tetap **belum siap produksi**. Build yang sukses tidak
membuktikan fail-safe relay, kompatibilitas flow 5 V, kestabilan RF/I2C,
otorisasi, recovery power-loss, atau keselamatan AC.

## Keselamatan

Skematik board memuat jalur `LINE`/`NETRAL`, catu AC-ke-DC, dan keluaran relay.
Jangan memberi tegangan PLN, mengaktifkan relay/solenoid, atau menghubungkan
programmer/USB ke board yang sedang terhubung ke PLN sebelum desain daya,
isolasi, proteksi, rating komponen, wiring, serta prosedur uji ditinjau dan
disetujui secara eksplisit.
