# Identifikasi kartu — gate implementasi dompet

Profil `smartdispenser_card_identify` khusus board B dan bench low-voltage.
Semua gate ditahan LOW; tidak ada pulsa relay/interrupt flow. Ini tidak mereset
kontak relay latching, sehingga jangan dianggap mode reset kontak untuk board A.
Tidak ada command write, autentikasi memakai kunci tebakan, formatting, enrollment,
atau perubahan saldo. LCD tidak menampilkan UID. Library/alamat I2C baseline dipakai.

Build dari `firmware/smartdispenser_firmware`:

```powershell
& 'C:\Users\MSI\.platformio\penv\Scripts\pio.exe' run -e smartdispenser_card_identify
```

Setelah board B dan koneksinya dipastikan, firmware ini dapat di-upload menggunakan
environment yang sama dengan `-t upload`. Jangan memilih target ketika beberapa
ST-Link terhubung tanpa identifikasi probe. Log UART PA9/PA10 adalah 115200 baud.

Reader melakukan InListPassiveTarget Type A, melaporkan ATQA, SAK, panjang UID
(bukan UID), kemudian GetVersion ISO-DEP bila didukung. Hanya metadata hardware/
software yang dicetak; UID/batch produksi tidak dicetak. LCD hasil ditahan >=2 detik.
No-card/transport-error dibedakan. Scan terbatas Type A; gagal baca tidak membuktikan
kartu kosong/rusak atau keluarga chip tertentu.

Contoh kategori log (bukan hasil kartu pengguna):

```text
TYPE_A ATQA=... SAK=... UID_LENGTH=...
HW=... (7 byte)
SW=... (7 byte)
VERSION complete; NOT_AUTHENTICATED; eligibility_requires_review
```

Metadata kompatibel bukan bukti chip asli/aman. Review vendor/type/version/storage
berdasarkan datasheet, kemudian uji autentikasi dan transaksi pada kartu sampel
sebelum mengunci format. Jangan memberi label DESFire hanya berdasarkan SAK 0x20.

Verifikasi source/build pada pekerjaan ini:

| Environment | Hasil | Flash | RAM |
|---|---|---:|---:|
| smartdispenser_card_identify | Build berhasil (channel PN532 bersama) | 29.400 byte | 2.164 byte |
| smartdispenser_lcd_arduino (legacy) | Build berhasil | 35.660 byte | 2.320 byte |

Build tidak membuktikan protokol berhasil pada kartu fisik. Belum upload, belum
uji baca kartu, belum autentikasi atau fault-injection. Profil legacy tetap default.

Catatan historis: pada enumerasi awal tidak ada port serial atau ST-Link terdeteksi;
ini bukan hasil enumerasi terbaru. Belum membaca kartu nyata. Untuk uji fisik dibutuhkan
board B low-voltage, programmer yang teridentifikasi, akses log UART, dan satu kartu
pelanggan sampel. Sesuai arahan terbaru, pengembangan software A/B diteruskan lebih
dahulu tanpa upload. Validasi kemampuan kartu tetap wajib sebelum menyatakan
fitur keamanan/transaksi bekerja pada perangkat.
