# AGENTS.md

Aturan ini berlaku untuk seluruh repositori `SmartDispenser`.

## Prinsip kerja

- Gunakan Bahasa Indonesia untuk dokumentasi proyek, laporan, dan komunikasi
  teknis, kecuali format eksternal mensyaratkan bahasa lain.
- Bedakan dengan jelas: fakta dari artefak, hasil pengukuran, asumsi, usulan,
  dan hal yang belum terverifikasi.
- Jangan menebak perilaku dari nama file, label net, atau nama komponen. Buka
  dan periksa sumber yang relevan.
- Pertahankan PDF dan foto asli. Jangan menimpa, mengompres ulang, atau
  mengganti nama artefak biner tanpa permintaan eksplisit.
- Jika source desain asli (EasyEDA/KiCad), BOM, Gerber, atau firmware tersedia,
  jadikan source tersebut bukti utama dan perbarui baseline dengan referensi
  yang dapat ditelusuri.

## Batas keselamatan hardware

- Anggap area `LINE`, `NETRAL`, catu AC-ke-DC, kontak relay, dan wiring
  solenoid sebagai berbahaya sampai rating dan isolasinya dibuktikan.
- Tanpa otorisasi eksplisit, jangan melakukan energisasi PLN, flashing,
  upload, reset perangkat, aktuasi relay/solenoid, perubahan wiring, atau
  pengujian yang menggerakkan hardware.
- Jangan menghubungkan debugger, programmer, UART, USB, osiloskop, atau alat
  ukur yang dibumikan saat board terhubung ke PLN kecuali isolasi dan prosedur
  uji sudah ditinjau oleh personel yang kompeten.
- Keberhasilan build atau pemeriksaan source bukan bukti perangkat telah
  di-flash, rail tegangan benar, relay bekerja, flow terkalibrasi, radio
  tersambung, atau sistem aman digunakan.

## Firmware

- Belum ada toolchain yang ditetapkan. Jangan memilih STM32CubeIDE, CMake,
  PlatformIO, Arduino, RTOS, atau framework lain hanya berdasarkan MCU.
- Sebelum membuat firmware, konfirmasi minimal: varian board/modul, part number
  MCU aktual, sumber clock, pin map final, level tegangan, fungsi relay,
  interface PN532, karakteristik flow sensor, radio yang benar, dan target
  toolchain.
- Saat firmware hadir, simpan konfigurasi reproducible dan dokumentasikan
  perintah build/test. Jangan memasukkan secret, credential, atau identifier
  produksi ke repositori.
- Semua output relay harus memiliki kondisi boot/reset yang fail-safe. Aktuasi
  harus eksplisit, dibatasi waktu bila sesuai, dan tidak boleh terjadi hanya
  karena komunikasi hilang atau data input tidak valid.
- Untuk relay latching, interlock SET/RST wajib eksplisit dan state software
  tidak boleh dianggap sebagai bukti posisi kontak fisik setelah reset atau
  power-cycle.
- Jangan menghubungkan flow sensor 5 V ke PA0 sebelum jenis output sensor dan
  batas tegangan input MCU dibuktikan kompatibel.

## Verifikasi perubahan

- Untuk perubahan dokumentasi hardware, cocokkan terhadap semua skematik,
  source desain, BOM, dan foto yang relevan; catat konflik antar-sumber.
- Untuk perubahan firmware, jalankan build dan test yang tersedia. Laporkan
  secara terpisah hasil static/build, simulasi, bench low-voltage, dan uji live.
- Jangan menyatakan kesiapan produksi, keselamatan listrik, akurasi metrologi,
  atau kepatuhan regulasi tanpa bukti pengujian yang sesuai.

## Tata letak repositori

- Simpan artefak referensi asli di `Schematic/` dan `Photo/`.
- Simpan dokumentasi turunan di `docs/`.
- Jangan commit output build, cache IDE, log lokal, dump, atau credential.
- Hindari perubahan massal pada file yang tidak terkait dengan tugas aktif.
