# Desain Firmware Personalization SmartDispenser

## 1. Status dokumen

Dokumen ini menjelaskan desain firmware **Personalization** STM32 berdasarkan pemeriksaan source aktual pada 14 September 2026.

Sumber utama:

- `firmware/smartdispenser_firmware/src/onefile/Perso.cpp`
- `firmware/smartdispenser_firmware/src/onefile/CompactCardSecurity.h`
- `firmware/smartdispenser_firmware/platformio.ini`
- `firmware/smartdispenser_firmware/boards/smartdispenser_stm32l071rbt6_arduino.json`

Dokumen ini adalah dokumentasi desain dari source. Ia tidak, dengan sendirinya, membuktikan kondisi wiring, kualitas RF, isi kartu tertentu, keamanan produksi, atau hasil uji lapangan.

**Goal dokumen:** `design.md` harus selalu mengikuti 100% perilaku semantik firmware Perso yang sedang berlaku. Setiap perubahan pada source Perso, helper format kartu, environment build Perso, atau definisi board membuat dokumen berstatus perlu sinkronisasi sampai fingerprint, inventaris fungsi, protokol, state, timing, layout data, serta batas keamanannya diperiksa dan diperbarui kembali.

## 2. Tujuan firmware

Firmware Personalization berjalan pada Board STM32 yang bertugas:

1. mengendalikan NFC Reader PN532 melalui I2C;
2. menyimpan identitas kartu master di EEPROM;
3. membuka atau mengunci sesi Personalization;
4. mendeteksi kartu master maupun non-master;
5. menjalankan Test Card read-only;
6. menjalankan identifikasi pemilik kartu secara read-only;
7. memeriksa seluruh sektor kartu secara read-only;
8. menguji kestabilan pembacaan kartu;
9. memeriksa kelayakan Wallet Data dan Card Identity;
10. menulis kartu baru atau memigrasikan kartu Wallet V2 lama;
11. membaca ulang dan memverifikasi hasil penulisan; dan
12. berkomunikasi dengan aplikasi desktop melalui bridge UART yang dibatasi.

Firmware ini bukan firmware Topup dan bukan firmware Dispenser. Ketiganya merupakan image terpisah walaupun format kartu compact dipakai bersama.

## 3. Batas tanggung jawab

### 3.1 Tanggung jawab Board

Board menjadi pemilik tunggal operasi NFC. Autentikasi MIFARE Classic, pembacaan blok, penulisan blok, verifikasi CRC, dan verifikasi Security Verification dijalankan lokal di firmware.

### 3.2 Tanggung jawab aplikasi desktop

Aplikasi desktop:

- mengatur alur operator;
- mengirim perintah yang diizinkan;
- menerima status aman yang sudah diparsing;
- mengalokasikan Card Number;
- menghubungkan Card Number dengan data pelanggan dalam Database; dan
- menyimpan Activity Logs serta hasil proses.

Aplikasi tidak menerima Key A, Key B, secret MAC, APDU, atau UID mentah.

### 3.3 Batas Database

Firmware tidak berkomunikasi langsung dengan Database. Pencatatan pemilik kartu dilakukan aplikasi setelah Board melaporkan hasil Personalization berhasil.

## 4. Target hardware dan toolchain

| Elemen | Konfigurasi source |
|---|---|
| MCU | STM32L071RBT6, Cortex-M0+ |
| Flash | 128 KiB |
| RAM | 20 KiB |
| Clock konfigurasi board | 2.097152 MHz |
| Framework | Arduino STM32 |
| Build system | PlatformIO `ststm32@20.0.0` |
| Environment | `smartdispenser_perso` |
| Upload/debug | ST-Link |
| NFC interface | I2C polling |
| UART bridge | 115200 baud |

Perintah build:

```powershell
cd D:\IoT\SmartDispenser\firmware\smartdispenser_firmware
platformio run -e smartdispenser_perso
```

Perintah upload berikut hanya boleh dijalankan setelah ada otorisasi eksplisit:

```powershell
platformio run -e smartdispenser_perso -t upload
```

Build berhasil bukan bukti bahwa firmware sudah di-upload. Upload baru dinyatakan terverifikasi apabila uploader melaporkan `Verified OK`.

## 5. Pin dan antarmuka Board

| Fungsi | Pin/alamat | Arah dan perilaku |
|---|---:|---|
| LED bawaan | PC13 | Output, active-low; saat setup ditulis HIGH/inaktif |
| I2C SDA | PB9 | I2C NFC Reader dan LCD |
| I2C SCL | PB8 | I2C NFC Reader dan LCD |
| LCD | `0x27` | LCD 16x2 melalui I2C |
| UART RX | PA10 | Menerima perintah bridge |
| UART TX | PA9 | Mengirim event bridge |
| Tombol P1 | PB3 | Dideklarasikan, belum dipakai alur runtime saat ini |
| Tombol P2 | PB4 | Dideklarasikan, belum dipakai alur runtime saat ini |
| Tombol P3 | PA11 | Dideklarasikan, belum dipakai alur runtime saat ini |
| Indikator biru | PB0 | Output; source menulis HIGH saat setup dan tidak mengubahnya lagi. Arti listrik aktif/inaktif harus dicocokkan dengan skematik |
| Indikator merah | PB1 | Output; source menulis HIGH saat setup dan tidak mengubahnya lagi. Arti listrik aktif/inaktif harus dicocokkan dengan skematik |

Firmware tidak mengaktifkan relay atau solenoid dalam alur Personalization ini.

## 6. Inisialisasi sistem

Urutan `setup()` adalah:

1. mengatur LED bawaan dan dua indikator sebagai output dalam kondisi inaktif;
2. membuka bridge UART 115200 baud;
3. memilih PB9/PB8 sebagai SDA/SCL;
4. memulai I2C pada 100 kHz;
5. memeriksa LCD pada alamat `0x27` dan mengaktifkan backlight bila tersedia;
6. menginisialisasi NFC Reader;
7. membaca status dan UID master dari EEPROM;
8. menampilkan status ringkas pada LCD; dan
9. mengirim event `boot_ready` atau `nfc_unavailable`.

Konfigurasi build menetapkan timing I2C standard-mode dan timeout transfer 100 ms. Source mencatat bahwa nilai timing bergantung pada clock aktual; perubahan clock mewajibkan perhitungan ulang timing I2C.

## 7. Desain NFC Reader

### 7.1 Inisialisasi PN532

`initializeNfc()` menjalankan:

1. `nfc.begin()`;
2. pembacaan versi firmware PN532;
3. SAM command untuk mode I2C polling tanpa IRQ;
4. `setPassiveActivationRetries(0x19)`.

Jika inisialisasi gagal, loop mencoba ulang setiap 3 detik. Ketika pulih, Board mengirim `nfc_recovered`.

### 7.2 Pemilik tunggal polling

Hanya loop STM32 yang memanggil pembacaan NFC. Aplikasi desktop tidak menjalankan pembacaan I2C kedua. Prinsip ini menghindari dua operasi NFC yang tumpang tindih.

Polling presence dijalankan setiap 100 ms. Kehilangan pembacaan sesaat ditahan oleh grace period 500 ms sebelum kartu dinyatakan benar-benar dilepas.

### 7.3 Syarat kartu

Alur saat ini menerima UID sepanjang 4 byte. Kartu dengan UID bukan 4 byte tidak dianggap sebagai kandidat valid oleh `serviceCardPresence()`.

Sebelum mencoba autentikasi baru, `reselectCard()` melakukan pemilihan kartu ulang. Ini mengakomodasi kartu tertentu yang hanya stabil untuk satu autentikasi per siklus seleksi.

## 8. Penyimpanan kartu master

EEPROM menggunakan layout berikut:

| Alamat | Isi |
|---:|---|
| 0 | `0xA5` bila master terdaftar |
| 1..4 | UID master 4 byte |

`masterSet` dan `masterUid` dimuat saat boot. Status sesi tidak disimpan ke EEPROM: `sessionUnlocked` selalu kembali `false` setelah boot/reset.

### 8.1 Pendaftaran master

1. Aplikasi mengirim `register_master_begin`.
2. Board masuk `MasterEnroll` dan menunggu kartu.
3. Kartu harus tetap menjadi kandidat selama minimal 10 detik.
4. Board mengirim `master_hold_ready`.
5. `register_master_commit` menyimpan UID ke EEPROM.
6. Sesi langsung aktif dan Board meminta kartu diangkat sebelum kartu berikutnya.

### 8.2 Membuka sesi

Ketika Board berada dalam operasi `Idle`, tap kartu dengan UID yang sama seperti master akan mengubah `sessionUnlocked` menjadi `true` dan menghasilkan `master/session_opened`.

### 8.3 Mengunci sesi

`session_lock`:

- menonaktifkan sesi;
- mengembalikan operasi ke `Idle`;
- menghapus kandidat aktif; dan
- menghasilkan `status/session_locked`.

### 8.4 Reset master

`reset_master_begin` memulai timer. Setelah 10 detik, `reset_master_commit` menghapus flag master di EEPROM dan mengunci sesi.

Catatan desain: pemeriksaan source menunjukkan commit reset master bergantung pada state dan waktu, bukan verifikasi kartu master yang sedang hadir pada saat commit. Penguatan otorisasi reset master masih perlu dibahas sebelum penggunaan produksi.

## 9. Model state runtime

### 9.1 State operasi utama

```text
Idle
 ├─ register_master_begin ──> MasterEnroll
 ├─ reset_master_begin ─────> MasterReset
 └─ perso_arm ──────────────> PersoArmed

MasterEnroll ── register_master_commit valid ──> Idle
MasterReset  ── reset_master_commit valid ─────> Idle
PersoArmed   ── kartu stabil + probe ──────────> PersoReview
PersoReview  ── perso_commit / cancel ─────────> Idle
```

### 9.2 State klasifikasi kartu

| State | Arti |
|---|---|
| `None` | Belum diklasifikasikan |
| `Blank` | Wallet Data dan Card Identity kosong serta kredensial dapat diotorisasi |
| `LegacyPersonalized` | Wallet V2 valid, Card Identity masih kosong |
| `SecurePersonalized` | Wallet V2 dan compact Card Identity valid |
| `Foreign` | Autentikasi, format, pembacaan, atau Security Verification tidak valid |

### 9.3 Mode khusus

`cardTestMode` dan `ownerLookupMode` terpisah dari state kandidat Personalization. Mengaktifkan salah satunya mematikan mode khusus lainnya.

## 10. Layout MIFARE Classic 1K

Kartu MIFARE Classic 1K terdiri dari 16 sektor. Setiap sektor memiliki tiga blok data dan satu sector trailer.

Firmware memakai lokasi tetap:

| Sector | Physical block | Nama operator | Fungsi |
|---:|---:|---|---|
| 2 | 8 | Wallet Data | Wallet V2 |
| 2 | 9 | Card Identity | Card Number, counter, tag |
| 2 | 10 | Reserved | Tidak digunakan saat ini |
| 2 | 11 | Sector Trailer | Key A, access bits, Key B |

Pemilihan lokasi tetap membuat Topup dan Dispenser mengetahui lokasi data tanpa pencarian dinamis.

## 11. Format Wallet Data — Block 8

| Byte | Panjang | Isi | Validasi saat ini |
|---:|---:|---|---|
| 0 | 1 | Magic | Harus `0xD7` |
| 1 | 1 | Versi wallet | Harus `2` |
| 2 | 1 | Flag aktif | `0` atau `1` |
| 3 | 1 | Saldo | Maksimum `100` |
| 4 | 1 | Jadwal | Maksimum `3`; `0` berarti belum diatur |
| 5..6 | 2 | Field hari/kuota | Dicakup CRC; semantics lanjutan mengikuti consumer wallet |
| 7 | 1 | Pemakaian harian | Maksimum `30` |
| 8 | 1 | Cadangan/transaksi | Maksimum `30` |
| 9..10 | 2 | CRC16-CCITT | CRC byte 0..8, big-endian |
| 11..15 | 5 | Reserved | Harus nol |

Pada kartu baru, firmware membuat wallet dengan status aktif, saldo `0`, jadwal `0`, field lain nol, kemudian menghitung CRC16-CCITT dengan initial value `0xFFFF` dan polynomial `0x1021`.

## 12. Format Card Identity — Block 9

| Byte | Panjang | Isi | Encoding |
|---:|---:|---|---|
| 0..3 | 4 | Card Number reference | Unsigned 32-bit big-endian; nol tidak valid |
| 4..7 | 4 | Transaction counter | Unsigned 32-bit big-endian; awal `0` |
| 8..15 | 8 | Security Verification tag | Delapan byte pertama AES-CMAC |

Database menampilkan Card Number sebagai `CARD-XXXXXXXX`, sedangkan kartu menyimpan angka biner 32-bit-nya.

## 13. Security Verification

Security Verification menggunakan AES-CMAC, tetapi data Wallet V2 dan Card Identity **tidak dienkripsi**.

Input tag berukuran 32 byte:

```text
byte  0..3  : domain marker "SDC1"
byte  4..7  : UID kartu 4 byte
byte  8..23 : Wallet Data 16 byte
byte 24..31 : Card Number + transaction counter
```

Kunci CMAC kerja diturunkan dari secret lokal dengan label domain terpisah. Hanya delapan byte pertama tag disimpan pada kartu. Perbandingan tag dilakukan dengan akumulasi perbedaan byte agar tidak berhenti pada byte pertama yang berbeda.

Secret MAC berada pada header privat yang di-ignore dari repositori dan tidak dikirim ke aplikasi. Dokumen ini sengaja tidak memuat nilai secret atau Key A/Key B.

## 14. Pemeriksaan dan klasifikasi kartu

### 14.1 Jalur kartu proyek

Firmware lebih dahulu mencoba kredensial proyek pada Sector 2:

1. autentikasi Wallet Data;
2. membaca Block 8;
3. bila Wallet Data tidak kosong, validasi format Wallet V2;
4. membaca Card Identity;
5. Card Identity kosong menghasilkan `LegacyPersonalized`;
6. Card Identity valid dan tag cocok menghasilkan `SecurePersonalized`; dan
7. format/tag gagal menghasilkan `Foreign`.

### 14.2 Jalur kartu baru

Jika kredensial proyek gagal, firmware mencoba empat kandidat kredensial pabrik publik yang di-allow-list. Tidak ada brute force seluruh kombinasi key.

Jika salah satu kandidat berhasil, Wallet Data dan Card Identity harus benar-benar kosong (`00` seluruhnya atau `FF` seluruhnya). Hanya kondisi tersebut yang menghasilkan `Blank`.

### 14.3 Keputusan operasional

| Hasil | Personalization baru | Migrasi | Overwrite otomatis |
|---|---:|---:|---:|
| `Blank` | Ya, setelah konfirmasi | Tidak perlu | Tidak |
| `LegacyPersonalized` | Tidak | Ya, setelah konfirmasi | Tidak |
| `SecurePersonalized` | Ditolak | Tidak | Tidak |
| `Foreign` | Ditolak | Tidak | Tidak |

## 15. Test Card — read-only

Test Card hanya membuktikan bahwa NFC Reader dapat mendeteksi presence kartu. Ia tidak:

- membuka sesi master;
- memulai Card Precheck;
- membaca seluruh sektor;
- menulis kartu; atau
- mengirim UID ke aplikasi.

Event yang dihasilkan:

- `status/card_test_ready`;
- `card_test/detected`;
- `card_test/removed`; dan
- `status/card_test_stopped`.

Test Card menerima kartu master maupun non-master. Grace period 500 ms mencegah satu polling miss langsung dianggap removal.

## 16. Identify Card Owner — read-only

Mode ini membaca kartu proyek untuk memperoleh Card Number secara aman:

1. mendeteksi kartu;
2. autentikasi Sector 2 dengan kredensial proyek;
3. membaca dan memvalidasi Wallet Data;
4. membaca Card Identity;
5. memverifikasi Security Verification; dan
6. mengirim hanya Card Number ke aplikasi.

Kode hasil:

| Event | Arti |
|---|---|
| `owner_lookup/identified` | Kartu valid; event memuat `card_reference` |
| `owner_lookup/legacy_card` | Wallet V2 valid tetapi Card Identity kosong |
| `owner_lookup/unrecognized` | Autentikasi, format, atau tag gagal |
| `owner_lookup/removed` | Kartu telah dilepas |

Firmware tidak mengirim data pelanggan. Aplikasi menggunakan Card Number untuk mencari pemilik pada Database.

Catatan boundary: command owner lookup pada firmware tidak memeriksa `sessionUnlocked`; pembatasan session saat ini juga diterapkan pada navigasi aplikasi. Jika ancaman mencakup client UART selain aplikasi resmi, gate session sebaiknya ditambahkan pula pada firmware.

## 17. Card Inspection — read-only

`technical_scan` hanya boleh dijalankan ketika sesi master aktif dan kandidat kartu tersedia.

Prosesnya:

1. memindai 16 sektor secara berurutan;
2. untuk Sector 2 memakai kredensial proyek;
3. untuk sektor lain hanya mencoba factory Key A `FF...FF`;
4. melewati manufacturer block 0 dan seluruh sector trailer;
5. menghitung blok data yang readable dan restricted; dan
6. mengirim ringkasan agregat, bukan dump isi blok.

Jumlah maksimum blok data yang dihitung adalah 47: 64 total blok dikurangi 16 trailer dan manufacturer block 0.

Hasil utama:

- `technical/scan_started`;
- `technical/scan_summary` dengan `readable` dan `restricted`; dan
- `technical/scan_complete`.

Status restricted tidak membuktikan sebuah sektor kosong atau berisi; status hanya menunjukkan bahwa autentikasi/read yang dicoba tidak diizinkan.

## 18. Card Quality Test

Pengujian kualitas melakukan maksimal 10 kali `reselectCard()` dengan jeda 70 ms.

- Setiap seleksi berhasil menambah `success`.
- Kegagalan menghentikan tes dan mengirim jumlah keberhasilan aktual.
- Hanya hasil `10/10` yang melanjutkan pemeriksaan Wallet Data dan Card Identity.

Hasil ini adalah proxy kestabilan komunikasi pada posisi kartu saat itu, bukan pengukuran RF strength, antena, atau coverage seluruh permukaan reader.

## 19. Card Precheck dan Personalization

### 19.1 Card Precheck

Card Precheck bersifat read-only. Setelah `perso_arm`, kartu harus terdeteksi dan stabil selama 3 detik sebelum `probeCard()` dijalankan.

Hasil bridge:

- `precheck/blank`;
- `precheck/legacy_personalized`;
- `precheck/already_personalized`; atau
- `precheck/foreign_or_invalid`.

Tidak ada penulisan sebelum aplikasi mengirim `perso_commit` dengan Card Number non-zero dan state berada di `PersoReview`.

### 19.2 Personalisasi kartu baru

Setelah konfirmasi operator:

1. autentikasi sector trailer memakai kandidat kredensial pabrik yang berhasil;
2. menulis Key A, access bytes `FF 07 80 00`, dan Key B proyek ke Block 11;
3. membuat Wallet V2 aktif dengan saldo 0;
4. menulis Wallet Data ke Block 8;
5. membuat Card Identity dengan counter 0 dan Security Verification;
6. menulis Card Identity ke Block 9;
7. membaca ulang Wallet Data;
8. membaca ulang Card Identity;
9. membandingkan byte hasil read-back;
10. memverifikasi format dan tag; dan
11. memastikan Card Number dan counter sesuai.

### 19.3 Migrasi kartu legacy

Untuk `LegacyPersonalized`:

1. Wallet Data lama dibaca dan harus valid;
2. Wallet Data dipertahankan, tidak ditimpa;
3. Card Identity baru dibuat dan ditulis ke Block 9; dan
4. Block 8 dan Block 9 diverifikasi ulang.

### 19.4 Retry penulisan

Setiap penulisan memakai maksimal tiga percobaan. Di antara retry, kartu dipilih ulang dan diautentikasi ulang. Kegagalan akhir menghasilkan `perso_failed`.

### 19.5 Selesai dan removal gate

Setelah hasil berhasil atau gagal:

- operasi kembali ke `Idle`;
- kandidat tidak langsung dipakai ulang;
- UID kandidat ditempatkan pada `awaitingRemovalUid`; dan
- kartu yang sama harus benar-benar diangkat sebelum proses berikutnya.

Selama kartu sama masih hadir, Board hanya sekali mengirim `remove_card_before_next`. Ini mencegah hasil selesai langsung kembali ke langkah pertama.

## 20. Bridge UART

### 20.1 Transport normal

Request aplikasi memakai:

```text
A5 5A | length uint16 big-endian | JSON UTF-8
```

Payload dibatasi maksimal 256 byte. Response Board memakai:

```text
length uint16 big-endian | JSON UTF-8
```

Response dibatasi maksimal 250 byte.

Event umum memuat beberapa field berikut sesuai tipe event:

- `v=1`;
- `profile="smartdispenser_perso"`;
- `transport="stm32_char"`;
- `type`;
- `code`;
- `nfc_ready`;
- `master_registered`;
- `session_open`;
- `operation`; dan
- `card_session`.

Handshake `perso_ready` juga memuat `card_format="compact_v1"`. Aplikasi memakai kombinasi profile dan format ini untuk menolak firmware yang tidak sesuai.

### 20.2 Compact fallback

CH340/STM32 juga menerima delimiter `!` diikuti kode satu byte:

| Kode | Perintah |
|---|---|
| `S` | status request |
| `L` | session lock |
| `X` | cancel |
| `T` | technical scan |
| `Q` | card quality test |
| `C` | card probe |
| `Y` / `Z` | start/stop Test Card |
| `U` / `V` | start/stop owner lookup |
| `E` / `R` | begin/commit register master |
| `B` / `D` | begin/commit reset master |
| `A` | arm Personalization |
| `PXXXXXXXX\n` | commit Personalization dengan Card Number uint32 dalam 8 digit hex |

Delimiter `!` mereset parser request. Compact commit dibatasi tepat delapan digit hex dan newline.

## 21. Kontrak command

| Command | Prasyarat utama | Hasil utama |
|---|---|---|
| `status_request` | Tidak ada | `perso_ready` |
| `cancel` | Tidak ada | operasi Idle, kandidat dibersihkan |
| `session_lock` | Tidak ada | sesi terkunci |
| `card_test_start/stop` | Tidak ada | mode Test Card aktif/nonaktif |
| `owner_lookup_start/stop` | Tidak ada di firmware | mode owner lookup aktif/nonaktif |
| `card_probe` | NFC ready | satu service presence |
| `technical_scan` | kandidat hadir, session aktif di fungsi scan | ringkasan scan |
| `card_quality_test` | kandidat hadir | hasil kualitas |
| `register_master_begin` | master belum ada | menunggu kartu master |
| `register_master_commit` | kartu hadir dan 10 detik terpenuhi | master tersimpan |
| `reset_master_begin` | master sudah terdaftar | mulai hold reset |
| `reset_master_commit` | 10 detik terpenuhi | master dihapus |
| `perso_arm` | session aktif | menunggu kartu pelanggan |
| `perso_commit` | state review, kandidat ready, kartu blank/legacy, Card Number valid | tulis dan verifikasi |

## 22. Error protocol

| Error | Kondisi |
|---|---|
| `bad_command` | Tidak ada field type |
| `command_not_allowed` | Command tidak ada pada allow-list |
| `frame_length_invalid` | Panjang frame nol atau lebih dari batas |
| `compact_commit_invalid` | Compact commit tidak tepat 8 hex + newline |
| `nfc_unavailable` | NFC Reader belum ready |
| `master_already_registered` | Mencoba daftar master ketika master sudah ada |
| `master_not_registered` | Mencoba reset ketika master belum ada |
| `master_hold_incomplete` | Hold/kehadiran kartu master belum memenuhi syarat |
| `reset_hold_incomplete` | Hold reset belum 10 detik |
| `master_session_required` | Operasi membutuhkan session aktif |
| `technical_scan_card_required` | Belum ada kandidat kartu untuk scan |
| `card_quality_card_required` | Belum ada kandidat kartu untuk quality test |
| `card_reference_required` | Card Number nol, hilang, atau di luar uint32 |
| `perso_not_ready` | State/kartu tidak memenuhi syarat commit |

## 23. LCD dan indikator

LCD menampilkan dua baris, masing-masing dipusatkan dan dipotong maksimal 16 karakter. Karakter kanan bawah menunjukkan:

- `O`: session Personalization aktif;
- `-`: session belum aktif.

Pada source saat ini, LCD terutama digunakan saat boot dan pemulihan NFC. Tombol fisik P1/P2/P3 serta indikator PB0/PB1 belum menjadi bagian state machine Personalization.

## 24. Keamanan dan privasi

### 24.1 Kontrol yang sudah ada

- allow-list command;
- ukuran frame terbatas;
- Key A/Key B dan secret MAC tidak dikirim ke desktop;
- raw protected blocks tidak dikirim pada scan normal;
- Card Precheck read-only;
- write memerlukan state review dan konfirmasi aplikasi;
- read-back verification setelah penulisan;
- Card Number nol ditolak;
- owner lookup hanya mengirim Card Number setelah tag valid; dan
- buffer kunci/tag sementara pada helper Security Verification dihapus setelah digunakan.

### 24.2 Keterbatasan penting

- MIFARE Classic tidak menyediakan keamanan modern terhadap cloning dan key recovery.
- Key A/Key B saat ini tetap/sama untuk seluruh kartu dan perangkat yang kompatibel, bukan diversified per kartu.
- Master hanya dikenali dari UID 4 byte sehingga UID dapat dikloning.
- Wallet Data dan Card Identity tidak dienkripsi.
- Tag hanya 64-bit hasil truncation dari AES-CMAC.
- Secret yang dikompilasi ke firmware dapat diekstrak oleh adversary dengan akses perangkat dan kemampuan yang memadai.
- Access bytes yang ditulis adalah konfigurasi transport `FF 07 80 00`; keberadaan key bukan bukti desain akses paling ketat.
- Owner lookup belum digate session pada lapisan firmware.
- Penulisan Block 11, Block 8, dan Block 9 tidak bersifat transaksi atomik. Kehilangan daya dapat meninggalkan kartu dalam state parsial.
- Counter ditulis awal `0`, tetapi strategi anti-replay dan update counter end-to-end belum dibuktikan di dokumen ini.
- `reselectCard()` mengganti buffer UID dengan UID yang baru terbaca tanpa membandingkannya terhadap UID kandidat sebelumnya. Pergantian kartu pada saat rangkaian operasi belum memiliki binding anti-swap yang eksplisit.
- Test Card dan owner lookup mempunyai prioritas polling atas state operasi utama. Command start/stop mode khusus tidak dengan sendirinya mereset `bridgeOperation`; aplikasi harus menjaga transisi mode agar state lama tidak tertinggal.
- `cancel` dan `session_lock` tidak secara langsung mematikan Test Card atau owner lookup di firmware. Aplikasi saat ini mengirim command stop sebagai bagian cleanup.
- Card Quality Test dan scan 16 sektor berjalan sinkron/blocking; loop bridge normal tidak diproses sampai fungsi selesai.

Firmware ini tidak boleh dianggap siap menyimpan nilai nyata atau siap produksi hanya berdasarkan keberhasilan build dan demo dasar.

## 25. Recovery dan kondisi parsial

| Titik gagal | Kemungkinan kondisi kartu | Penanganan saat ini |
|---|---|---|
| Sebelum trailer ditulis | Kartu tetap factory/asal | Dapat dicoba ulang bila masih lolos Card Precheck |
| Setelah trailer, sebelum Wallet Data | Sector 2 memakai key proyek tetapi Wallet Data kosong | Probe dapat mengklasifikasikan blank/foreign bergantung keterbacaan Block 9 |
| Setelah Wallet Data, sebelum Card Identity | Menjadi Wallet V2 legacy | Dapat masuk jalur migrasi |
| Setelah Card Identity, sebelum response sukses | Kartu mungkin sudah valid tetapi Database belum mencatat | Wajib rekonsiliasi; jangan overwrite buta |
| Database gagal setelah `perso_success` | Kartu valid tanpa ownership record | Aplikasi harus melaporkan Database Sync Required |

Strategi recovery otomatis, journal transaksi kartu, dan rekonsiliasi operator masih perlu dirancang lebih lanjut.

## 26. Hal yang masih perlu dibahas

1. per-card key diversification;
2. penggantian MIFARE Classic dengan media yang mendukung kriptografi modern;
3. autentikasi master yang tidak hanya bergantung pada UID;
4. session gate pada seluruh command read sensitif di firmware;
5. mekanisme lost/revoked/replacement card;
6. blacklist atau sinkronisasi status ke Dispenser offline;
7. transaksi atomik atau recovery marker lintas Block 8/9/trailer;
8. lifecycle dan rotasi secret;
9. proteksi debug/programming interface;
10. anti-replay counter end-to-end;
11. pengujian kartu 4-byte UID versus tipe kartu lain;
12. uji coverage/antenna dengan alat RF yang sesuai;
13. versioning dan migrasi format setelah `compact_v1`; dan
14. acceptance test produksi yang memisahkan Board, NFC Reader, Database, dan aplikasi.

## 27. Verifikasi yang direkomendasikan

### 27.1 Static/build

- build `smartdispenser_perso` tanpa warning/error;
- catat penggunaan Flash/RAM;
- pastikan `.private` tidak masuk artefak publik;
- verifikasi Topup dan Dispenser tidak berubah bila scope hanya Perso.

### 27.2 Bench low-voltage

- boot dengan NFC Reader terhubung dan terputus;
- recovery NFC setiap 3 detik;
- register/open/lock/reset master;
- Test Card untuk master dan non-master;
- owner lookup untuk compact, legacy, foreign, dan removal;
- scan 16 sektor dan ringkasan maksimum 47 blok;
- quality test 10/10 dan gagal parsial;
- kartu baru, migrasi legacy, kartu already personalized, dan foreign;
- removal gate setelah success/failure;
- putus daya pada tiap tahap write untuk menguji recovery.

### 27.3 Integrasi aplikasi

- handshake profile dan `compact_v1`;
- ACK/retry Test Card;
- state session locked/active;
- Database ownership hanya setelah hasil sukses;
- parsed serial tidak memuat UID, keys, secret, atau raw block;
- kondisi `Database Sync Required`; dan
- pemetaan Card Number ke pelanggan yang benar.

### 27.4 Bukti yang harus dipisahkan

Laporan pengujian harus membedakan:

- source inspected;
- build passed;
- upload `Verified OK`;
- Board/NFC Reader live;
- kartu terbaca;
- kartu tertulis dan read-back verified;
- ownership tersimpan di Database; dan
- pengujian lapangan/keamanan yang belum dilakukan.

## 28. Baseline dan fingerprint source

Dokumen ini disinkronkan terhadap snapshot berikut. Perubahan satu byte pada salah satu file akan menghasilkan hash berbeda dan mewajibkan review ulang `design.md`.

| File | Baris | Byte | SHA-256 |
|---|---:|---:|---|
| `src/onefile/Perso.cpp` | 818 | 43042 | `3747C5710797BEDD0BA7896C28E0B1F0508C1AA1FC7F3E0F634F7F6E0514B373` |
| `src/onefile/CompactCardSecurity.h` | 131 | 4246 | `C9C42830C4F6BF126699804FB6B604F236C0F557107AA6E4322C6133376D84F2` |
| `platformio.ini` | 67 | 2397 | `7C396E22D13B31C612B90DF4507D6201B7C4B241076FE5A7D9B046A858C630CB` |
| `boards/smartdispenser_stm32l071rbt6_arduino.json` | 34 | 1036 | `37FDC74542867D49A9F2D2046E4684DCC4960DEA7CE95511F5B5DD1210D44F81` |

Path pada tabel relatif terhadap `firmware/smartdispenser_firmware`, kecuali dua file konfigurasi yang memang berada langsung di folder tersebut.

Definisi 100% pada dokumen ini adalah **cakupan semantik seluruh top-level function, state global, command/event, layout kartu, timing, konfigurasi build, dan boundary keamanan pada snapshot tersebut**. Dokumen ini bukan salinan line-by-line source dan tidak menggantikan source sebagai artefak eksekusi.

## 29. Konfigurasi build lengkap

### 29.1 Konfigurasi bersama

| Parameter | Nilai source |
|---|---|
| Platform | `ststm32@20.0.0` |
| Board | `smartdispenser_stm32l071rbt6_arduino` |
| Framework | `arduino` |
| Upload protocol | `stlink` |
| Debug tool | `stlink` |
| I2C timing | `I2C_TIMING_SM=0x00100607` |
| I2C HAL timeout | `I2C_TIMEOUT_TICK=100` ms |
| Include path | `src/onefile`, `.private` |
| Compiler checks | `-Wall -Wextra -Werror -fstack-usage` |
| PN532 interface | `NFC_INTERFACE_I2C=1` |
| Stack reserve | linker symbol `__ab_stack_reserve__=8192` |
| Internal pull-up define | `SMARTDISPENSER_ENABLE_INTERNAL_I2C_PULLUPS=1` |

`default_envs` adalah `smartdispenser_dispenser`, bukan Perso. Karena itu build Perso harus selalu menyebut `-e smartdispenser_perso` secara eksplisit.

### 29.2 Dependencies

| Library | Versi/pin |
|---|---|
| LiquidCrystal_PCF8574 | `2.3.0` |
| Seeed Studio PN532 | commit `2c47f5c836af53158c4e29685551612181fd8f9b` |
| rweather Crypto | `0.4.0` |
| NDEF | di-ignore |

### 29.3 Definisi board

Board JSON menetapkan:

- CPU `cortex-m0plus`;
- MCU `stm32l071rbt6` dan product line `STM32L071xx`;
- `F_CPU=2097152L`;
- linker script `STM32L071RBTX_FLASH.ld`;
- Arduino variant `GENERIC_L071RBTX`;
- maksimum RAM 20480 byte;
- maksimum Flash 131072 byte; dan
- adapter yang didukung: ST-Link, CMSIS-DAP, J-Link, dan Black Magic, dengan ST-Link sebagai default.

## 30. Inventaris state global

| Kelompok | State | Peran aktual |
|---|---|---|
| Master | `masterSet`, `masterUid[4]` | Master persisten yang dimuat dari EEPROM |
| Session | `sessionUnlocked` | Gate runtime; selalu false setelah boot |
| Peripheral | `lcdReady`, `nfcReady`, `nfcLastInitAttempt` | Status LCD/NFC dan timer recovery |
| Operasi | `bridgeOperation` | `Idle`, `MasterEnroll`, `MasterReset`, `PersoArmed`, atau `PersoReview` |
| Kandidat | `candidateUid`, `candidatePresent`, `candidateReady`, `candidateState`, `candidateSince` | Kartu yang sedang diproses |
| Operasi waktu | `operationSince` | Timer reset master; diset pula saat enroll tetapi validasi enroll memakai `candidateSince` |
| Sesi kartu | `cardSession` | Counter deteksi kandidat; tidak bertambah pada Test Card/owner lookup |
| Removal gate | `awaitingRemoval`, `awaitingRemovalAnnounced`, `awaitingRemovalUid` | Mencegah kartu yang sama langsung dianggap proses baru |
| Test Card | `cardTestMode`, `cardTestPresent`, `cardTestUid`, `cardTestLastSeen` | Presence test terisolasi |
| Owner lookup | `ownerLookupMode`, `ownerLookupPresent`, `ownerLookupUid`, `ownerLookupLastSeen` | Validasi Card Number read-only |
| Polling | `lastNfcPoll`, `lastCardSeen` | Interval polling dan grace removal |
| Parser frame | `rxSyncUsed`, `rxHeaderUsed`, `rxExpected`, `rxUsed`, `rxPayload[257]` | State parser request UART |
| Parser compact commit | `compactCommitPending`, `compactCommitUsed`, `compactCommitHex[9]` | State lokal statis di `serviceBridgeInput()` |

`rxHeader[2]` dideklarasikan tetapi tidak dibaca atau ditulis oleh parser aktif pada snapshot ini.

## 31. Prioritas eksekusi presence

Setiap polling, `serviceCardPresence()` mengikuti prioritas berikut:

```text
readPassiveTargetID + UID length == 4
          |
          v
cardTestMode aktif? ------ ya --> tangani detected/removal Test Card, lalu return
          |
         tidak
          v
ownerLookupMode aktif? --- ya --> baca/validasi Card Number, lalu return
          |
         tidak
          v
kartu tidak hadir? ------- ya --> grace 500 ms, emit removal, reset kandidat/gate
          |
         tidak
          v
awaitingRemoval UID sama?  ya --> emit remove_card_before_next sekali, return
          |
         tidak
          v
master + operasi Idle? --- ya --> aktifkan session bila masih locked, return
          |
         tidak
          v
Idle? -------------------- ya --> catat kandidat dan emit card/detected
          |
         tidak
          v
MasterEnroll / PersoArmed / PersoReview processing
```

Konsekuensi aktual:

- Test Card dan owner lookup dapat berjalan tanpa melewati branch master.
- Kartu master di mode khusus diperlakukan sesuai mode khusus, bukan membuka sesi.
- Kartu non-master pada `Idle` dapat menghasilkan event deteksi walaupun session locked; penulisan tetap memerlukan `perso_arm` dan session aktif.
- Kartu baru yang berbeda UID saat operasi aktif menggantikan `candidateUid` dan memulai `candidateSince` baru.

## 32. Detail factory-key probing

`authWithFactoryCandidate()` mencoba empat Key A pabrik publik secara berurutan, dengan reselect sebelum setiap percobaan:

1. `FFFFFFFFFFFF`;
2. `A0A1A2A3A4A5`;
3. `D3F7D3F7D3F7`; dan
4. `000000000000`.

Daftar ini bukan key guessing seluruh ruang 48-bit dan bukan kredensial rahasia proyek.

Perbedaan jalur yang perlu dipertahankan dalam diagnosis:

- `probeCard()` memakai seluruh empat kandidat tersebut.
- `personalizeCard()` memakai kandidat yang berhasil untuk autentikasi Block 11 sebelum mengganti trailer.
- `readOnlyWalletProbe()` hanya memakai project Key A lalu fallback `FFFFFFFFFFFF`; tiga kandidat publik lainnya tidak dicoba pada jalur quality/slot summary.
- `technicalScan()` memakai project Key A untuk Sector 2 dan hanya `FFFFFFFFFFFF` untuk sektor lain.
- Jika pembacaan Block 8 gagal setelah project Key A berhasil, `probeCard()` mencoba project Key B sebagai diagnosis. Walaupun read via Key B berhasil, jalur tersebut tetap berakhir `Foreign`; data hasil Key B tidak diteruskan ke klasifikasi accepted.

## 33. Detail implementasi AES-CMAC

`CompactCardSecurity.h` mengimplementasikan CMAC secara lokal:

1. `AES128::setKey()` memasang key 16 byte;
2. AES atas zero block menghasilkan nilai dasar subkey;
3. `doubleBlock()` melakukan left shift 128-bit dan XOR conditional `0x87`;
4. semua block sebelum block terakhir di-XOR dengan state lalu dienkripsi;
5. block terakhir lengkap memakai K1;
6. block kosong/tidak lengkap memakai padding `0x80` lalu K2;
7. hasil akhir dienkripsi menjadi tag 16 byte; dan
8. key, state, subkey, input turunan, dan buffer tag sementara dihapus dengan write volatile bila fungsi terkait selesai.

Kunci kerja tidak langsung memakai secret. `loadMacKey()` menghitung CMAC secret terhadap label domain 16 byte, kemudian `makeTag()` menghitung CMAC kedua atas input 32 byte. Hanya 8 byte awal hasil kedua disimpan.

Helper lengkap:

| Helper | Fungsi |
|---|---|
| `wipe` | Menghapus buffer melalui pointer volatile |
| `putBe32` | Serialisasi uint32 big-endian |
| `getBe32` | Deserialisasi uint32 big-endian |
| `doubleBlock` | Pembentukan subkey CMAC |
| `cmac128` | Implementasi AES-CMAC 128-bit |
| `loadMacKey` | Derivasi key kerja dari secret privat |
| `makeTag` | Membentuk tag terikat UID, wallet, dan metadata |
| `encode` | Menulis prefix metadata dan tag; menolak Card Number nol |
| `decodeAndVerify` | Validasi tag dan decode metadata |
| `isBlank` | Menerima seluruh `00` atau seluruh `FF` sebagai blank |

Generator `tools/generate_compact_card_secret.py` membuat secret acak 16 byte memakai `secrets.token_bytes(16)`, menolak overwrite kecuali `--force`, dan menulis header ke `.private/compact_card_secret.h`. Rotasi dengan `--force` akan membuat kartu bertag secret lama gagal diverifikasi bila tidak ada strategi migrasi.

## 34. Schema event per emitter

Tidak semua event membawa field yang sama.

| Emitter | Field yang dikirim |
|---|---|
| `emitEvent` | `v`, `profile`, `transport`, `type`, `code`, `nfc_ready`, `master_registered`, `session_open`, `operation`, `card_session` |
| `emitStatus("perso_ready")` | field status penuh di atas + `card_format="compact_v1"` |
| `emitTechnicalStatus` | `v`, `profile`, `type="technical"`, `code`, `nfc_ready`, `session_open` |
| `emitTechnicalScanSummary` | `v`, `profile`, `type="technical"`, `code="scan_summary"`, `readable`, `restricted` |
| `emitCardQuality` | `v`, `profile`, `type="technical"`, `code="card_quality"`, `success`, `attempts`, `average_ms=0`, `source="auto"` |
| `emitWalletSlot` | `v`, `profile`, `type="technical"`, `code="wallet_slot"`, `state`, `sector=2`, `block=8` |
| `emitOwnerLookup` | `v`, `profile`, `type="owner_lookup"`, `code`, optional `card_reference`, `nfc_ready`, `session_open` |
| `emitTechnicalBlock` | `v`, `profile`, `type="technical"`, `code="scan_block"`, sector/block/kind/state/data |

`emitTechnicalBlock()` tersedia di source tetapi tidak dipanggil pada snapshot ini. Karena itu scan runtime hanya mengirim agregat, bukan data hex per block.

`sendJson()` memakai `strnlen(json, 250)`. Emitter dirancang memakai buffer yang cukup kecil; apabila string buatan baru melampaui 250 byte tanpa validasi tambahan, transport akan memotongnya.

## 35. Parser UART secara presisi

### 35.1 Reset delimiter

Setiap byte `!`:

- menghapus state sync/header/payload frame;
- membatalkan state compact commit; dan
- menunggu byte command berikutnya.

Byte tak dikenal ketika parser idle diabaikan sampai menemukan `!` command yang valid atau sync `A5 5A`.

### 35.2 Framed request

Setelah `A5 5A`, parser menerima dua bentuk header:

- `00 LEN` untuk payload pendek normal; atau
- langsung `LEN` bila byte nol high-length hilang pada jalur CH340.

Implementasi ini efektif ditujukan untuk request pendek. Walaupun variabel panjang bertipe 16-bit dan validasi menyebut maksimum 256, parser fallback tidak menyusun nilai high-byte non-zero menjadi uint16 penuh.

Parser baru memanggil `handleCommand()` setelah tepat `rxExpected` byte diterima. JSON tidak diparsing penuh; command dideteksi lewat substring persis `"type":"..."`, dan Card Number dicari lewat substring `"card_reference":` kemudian `strtoul` decimal.

### 35.3 Compact commit

Sesudah command `P`, parser hanya menerima tepat delapan karakter `0-9`/`A-F`, lalu newline. Lowercase hex ditolak. Nilai hex dikonversi ke unsigned long dan diteruskan sebagai decimal JSON internal ke `handleCommand()`.

### 35.4 Tidak ada integrity/authentication transport

Bridge tidak memiliki CRC frame, message authentication, encryption, sequence number, atau autentikasi client UART. Safety terutama berasal dari allow-list command, state machine, session gate pada operasi tertentu, dan batas panjang.

## 36. Perilaku logger aktual

Objek `logger` bertipe `SilentLogger`. Semua overload `print()` dan `println()` kosong. Akibatnya:

- `logPrefix()` tidak menghasilkan output;
- `logRawStatus()` membaca buffer status PN532 tetapi tidak mengirimnya ke UART;
- pesan diagnostic di `probeCard()` dan `writeWithRetry()` tidak terlihat pada serial; dan
- satu-satunya output UART operasional berasal dari event JSON melalui `bridgeSerial`.

Ini mencegah teks debug merusak framing response, tetapi mengurangi visibility kegagalan PN532 tingkat rendah.

## 37. Karakter blocking dan responsivitas

`loop()` memproses seluruh byte UART yang sudah tersedia sebelum masuk ke recovery/poll NFC. Operasi berikut bersifat sinkron:

- `cardQualityTest()`: hingga 10 reselect dengan `delay(70)`, sekitar 700 ms ditambah waktu transaksi NFC;
- `technicalScan()`: autentikasi 16 sektor dan hingga 47 pembacaan data;
- `probeCard()`: beberapa autentikasi/reselect/read; dan
- `personalizeCard()`: autentikasi, write retry, encode, dan read-back.

Selama fungsi tersebut berjalan, command UART lain tidak diproses oleh loop utama. Tidak ada scheduler/RTOS/task concurrency dalam file ini.

## 38. Matriks traceability fungsi Perso.cpp

| Fungsi | Bagian desain |
|---|---|
| `loadMaster`, `saveMaster` | 8 |
| `lcdShow` | 6, 23 |
| `logPrefix`, `logRawStatus` | 36 |
| `crc16Ccitt`, `makeWalletV2`, `verifyWalletV2`, `isWalletV2`, `isBlankBlock` | 11 |
| `reselectCard`, `authWithFactoryCandidate` | 7, 14, 32 |
| `classifyBlankWallet`, `classifyProtectedWallet`, `probeCard` | 9, 14, 32 |
| `writeWithRetry`, `personalizeCard` | 19, 25 |
| `configureSamForI2cReader`, `initializeNfc` | 6, 7 |
| `operationCode` | 9, 34 |
| `sendJson`, `emitEvent`, `bridgeProgress`, `emitStatus` | 20, 34 |
| `emitTechnicalStatus`, `emitTechnicalScanSummary`, `emitCardQuality`, `emitWalletSlot` | 17, 18, 34 |
| `emitOwnerLookup` | 16, 34 |
| `emitTechnicalBlock` | 17, 34; helper tidak dipanggil |
| `resetCandidate` | 9, 19, 30 |
| `commandIs`, `readCardReference`, `rejectCommand`, `handleCommand` | 21, 22, 35 |
| `serviceBridgeInput` | 20, 35 |
| `authenticateDiagnosticSector`, `technicalScan` | 17, 32 |
| `readOnlyWalletProbe`, `cardQualityTest` | 18, 32 |
| `serviceCardPresence` | 7, 9, 15, 16, 19, 31 |
| `setup`, `loop` | 6, 7, 37 |

Seluruh top-level function pada `Perso.cpp` tercakup pada matriks ini.

## 39. Invariant dan edge case runtime

1. Hanya UID length 4 yang dianggap present; jenis UID lain tampak seperti tidak ada kartu.
2. `sessionUnlocked` tidak persisten dan selalu false pada boot.
3. Master hanya membuka session ketika `bridgeOperation == Idle` dan mode khusus tidak aktif.
4. `perso_arm` menghapus kandidat lama sebelum menunggu kartu baru.
5. Precheck otomatis di firmware baru berjalan setelah kandidat yang sama tersimpan selama 3000 ms pada `PersoArmed`.
6. Removal baru dianggap final setelah miss melebihi 500 ms.
7. Setelah hasil Personalization, same-card re-detection ditahan sampai removal.
8. `card_session` hanya mengidentifikasi urutan kandidat runtime, bukan identitas kartu permanen.
9. `average_ms` pada event quality selalu `0`; firmware belum menghitung latency aktual.
10. Kartu blank menerima pola seluruh nol atau seluruh `FF` pada masing-masing blok.
11. Card Number harus `1..0xFFFFFFFF`; nol invalid.
12. Counter awal selalu nol pada Perso.
13. Kartu compact valid diikat oleh tag terhadap UID, Wallet Data, Card Number, dan counter.
14. Mengubah salah satu field tersebut tanpa secret yang sesuai membuat verifikasi gagal.
15. Tag valid tidak membuat Wallet Data terenkripsi atau menyembunyikan nilainya.
16. LCD tidak wajib hadir agar firmware melanjutkan boot.
17. NFC Reader wajib ready untuk polling; bridge UART tetap berjalan ketika NFC gagal dan recovery dicoba berkala.
18. Tombol fisik yang dideklarasikan tidak diinisialisasi atau dibaca pada snapshot ini.
19. PB0/PB1 hanya diinisialisasi HIGH dan tidak menjadi indikator progress runtime.
20. Helper scan raw-block tidak dipakai, sehingga data kartu tidak di-stream oleh Technical Scan saat ini.

## 40. Prosedur menjaga sinkronisasi 100%

Setiap perubahan firmware Perso harus diikuti urutan dokumentasi berikut:

1. hitung ulang SHA-256 dan jumlah baris/byte empat file baseline;
2. diff `Perso.cpp`, `CompactCardSecurity.h`, environment Perso pada `platformio.ini`, dan board JSON;
3. perbarui bagian desain yang terdampak;
4. pastikan setiap top-level function masih tercakup di matriks traceability;
5. ekstrak ulang seluruh command, event, error, progress, dan compact command;
6. periksa ulang byte layout Block 8, Block 9, dan trailer;
7. periksa ulang seluruh timing dan retry;
8. pastikan key/secret tidak bocor ke dokumentasi;
9. jalankan pemeriksaan Markdown dan link/path; dan
10. laporkan dokumentasi, build, upload, dan hardware sebagai evidence terpisah.

Jika fingerprint source berbeda dari Bagian 28, status dokumen harus dianggap **perlu sinkronisasi**, bukan otomatis 100% sesuai.

## 41. Katalog protocol token lengkap

Bagian ini menjadi checklist literal terhadap seluruh command/status/progress/result/error yang dibentuk source saat ini.

### 41.1 Command masuk

```text
status_request
cancel
session_lock
card_test_start
card_test_stop
owner_lookup_start
owner_lookup_stop
card_probe
technical_scan
card_quality_test
register_master_begin
register_master_commit
reset_master_begin
reset_master_commit
perso_arm
perso_commit
```

### 41.2 Status keluar

```text
boot_ready
nfc_unavailable
nfc_recovered
perso_ready
cancelled
session_locked
card_test_ready
card_test_stopped
owner_lookup_ready
owner_lookup_stopped
master_enroll_wait_card
master_hold_ready
master_reset_hold
perso_wait_card
remove_card_before_next
```

Nilai field `operation` yang ikut dikirim pada status/event:

```text
idle
master_enroll
master_reset
perso_armed
perso_review
```

### 41.3 Event presence/master

```text
card/detected
card/removed
card_test/detected
card_test/removed
master/session_opened
owner_lookup/identified
owner_lookup/legacy_card
owner_lookup/unrecognized
owner_lookup/removed
```

### 41.4 Technical status dan data

```text
technical/scan_started
technical/scan_summary
technical/scan_complete
technical/quality_started
technical/card_quality
technical/wallet_slot
```

Nilai field `kind` pada `technical/scan_block`:

```text
data
manufacturer_masked
trailer_protected
```

`manufacturer_masked` digunakan khusus Block 0. `trailer_protected` digunakan untuk setiap sector trailer. Keduanya tidak membawa byte mentah kartu ke aplikasi.

Nilai `wallet_slot.state`:

```text
ready
legacy_ready
already_used
unavailable
```

Helper yang tidak dipanggil dapat membentuk `technical/scan_block`, tetapi token tersebut tidak muncul pada alur runtime snapshot ini.

### 41.5 Precheck result

```text
precheck/blank
precheck/legacy_personalized
precheck/already_personalized
precheck/foreign_or_invalid
```

### 41.6 Personalization progress dan result

```text
progress/start
progress/precheck
progress/write_protection
progress/write_wallet
progress/preserve_wallet
progress/write_metadata
progress/verify_wallet
result/master_registered
result/master_reset
result/perso_success
result/perso_failed
```

`progress/precheck` dipancarkan oleh firmware ketika probe otomatis setelah kartu stabil dimulai. Technical scan dan quality test merupakan command/event terpisah yang diorkestrasi aplikasi.

### 41.7 Error keluar

```text
bad_command
command_not_allowed
frame_length_invalid
compact_commit_invalid
nfc_unavailable
master_already_registered
master_not_registered
master_hold_incomplete
reset_hold_incomplete
master_session_required
technical_scan_card_required
card_quality_card_required
card_reference_required
perso_not_ready
```

## 42. Katalog konstanta dan objek hardware

| Identifier source | Nilai/peran terdokumentasi |
|---|---|
| `kLedPin` | PC13 |
| `kLedActiveLow` | `true` |
| `kI2cSdaPin` | PB9 |
| `kI2cSclPin` | PB8 |
| `kLcdI2cAddress` | `0x27` |
| `kButtonP1Pin` | PB3, belum digunakan |
| `kButtonP2Pin` | PB4, belum digunakan |
| `kButtonP3Pin` | PA11, belum digunakan |
| `kIndicatorPb0Pin` | PB0, komentar source: biru |
| `kIndicatorPb1Pin` | PB1, komentar source: merah |
| `kCardKeyA`, `kCardKeyB` | Array tetap 6 byte yang dikompilasi; nilai sengaja tidak diduplikasi di dokumen |
| `kFactoryKeyCandidateCount` | 4 |
| `kEepromMasterFlag` | alamat 0 |
| `kEepromMasterUid` | alamat awal 1 |
| `kWalletBlock` | 8 |
| `kMetadataBlock` | 9, berasal dari helper compact |
| `kTrailerBlock` | 11 |
| `kWalletMagic` | `0xD7` |
| `kWalletVersion` | 2 |
| `kNfcPollIntervalMs` | 100 ms |
| `kCardAbsentGraceMs` | 500 ms |
| `kMetadataAuthenticatedBytes` | 8 byte prefix metadata |
| `kMetadataTagBytes` | 8 byte tag tersimpan |

Objek runtime hardware:

| Objek | Konstruksi/peran |
|---|---|
| `logger` | `SilentLogger`; tidak mengeluarkan data |
| `bridgeSerial` | `Uart(PA10, PA9)` atau RX PA10/TX PA9 |
| `lcd` | `LiquidCrystal_PCF8574(0x27)` |
| `pn532i2c` | `PN532_I2C(Wire)` |
| `nfc` | `PN532(pn532i2c)` |

Nilai Key A/Key B proyek tidak disalin ke dokumentasi untuk mencegah penyebaran credential. Fakta desain yang harus tetap terbaca adalah bahwa keduanya fixed, sama untuk seluruh kartu/perangkat kompatibel, disimpan dalam firmware, dan belum diversified per kartu.
