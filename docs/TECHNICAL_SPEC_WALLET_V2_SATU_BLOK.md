# SmartDispenser — Wallet NFC V2 Satu Blok, Jadwal, dan Kuota Harian

**Status:** spesifikasi firmware one-file yang berhasil dibuild pada 9 September 2026. Bukan bukti bahwa kartu, DS3231, relay, flowmeter, solenoid, maupun instalasi listrik telah diuji pada perangkat nyata.

**Firmware yang dicakup:** Perso, Topup, dan Dispenser.

Dokumen ini menjelaskan profil one-file dengan satu blok MIFARE Classic dan Key A tetap. Dokumen desain lama yang membahas arsitektur modular/terenkripsi tidak diubah oleh dokumen ini.

## 1. Arsitektur dan ketetapan

Sistem offline terdiri dari dua Dispenser A1/A2 dan satu perangkat operator B. Kartu pelanggan membawa saldo dan pemakaian hariannya, sehingga satu kartu yang telah digunakan di A1 tetap dibatasi saat dipakai di A2.

| Parameter | Nilai firmware | Status |
|---|---:|---|
| Tipe kartu | Master dan pelanggan | Diimplementasikan |
| Saldo maksimum | 100 L | Diimplementasikan |
| Kuota harian global | 30 L | Diimplementasikan pada Dispenser |
| Pilihan pengambilan | 10 L, 20 L, 30 L | Diimplementasikan |
| Sisa di bawah 10 L | P1 menawarkan seluruh sisa | Diimplementasikan |
| Kalibrasi awal | 100 pulsa = 1 L | Konfigurasi awal; belum dikalibrasi |
| Pagi | 06:00–09:59 | Diimplementasikan |
| Siang | 10:00–13:59 | Diimplementasikan |
| Sore | 14:00–17:59 | Diimplementasikan |
| Di luar jadwal | 18:00–05:59 | Ditolak |
| No-flow | 3 detik, P2 untuk stop | Diimplementasikan |
| Relay latching | pulsa 60 ms | Diimplementasikan; posisi kontak fisik belum dibuktikan |

Satu pelanggan diasumsikan mempunyai satu kartu. Kuota 30 L tidak disimpan pada kartu karena nilainya sama untuk semua pelanggan. Yang disimpan pada kartu adalah tanggal dan total liter yang sudah dipakai hari itu.

## 2. Koneksi hardware

| Perangkat | Koneksi | Catatan |
|---|---|---|
| LCD 16x2 PCF8574 | PB9=SDA, PB8=SCL, I2C 0x27 | Dipakai A dan B |
| PN532 | I2C yang sama; baseline 0x24 | Dipakai A dan B |
| DS3231 | I2C PB9/PB8, alamat 0x68 | Wajib pada setiap A, dengan baterai backup |
| Flowmeter | PA0, interrupt falling edge | Tegangan input wajib maksimum 3,3 V |
| Tombol | P1=PB3, P2=PB4, P3=PA11 | Aktif LOW |
| Relay 1 | PA2/PA3 | Dipakai untuk transaksi air |
| Relay 2 | PA4/PB2 | Dipulse reset pada boot, belum dipakai untuk transaksi air |

Jika DS3231 tidak merespons, oscillator-stop flag aktif, atau tanggal/jam tidak valid, Dispenser menampilkan RTC BELUM SIAP dan tidak membuka solenoid.

## 3. Wallet pelanggan V2

Wallet menggunakan **satu blok data MIFARE Classic: blok fisik 8**, yaitu blok data pertama sektor 2. Blok 9 dan 10 tidak dipakai wallet. Trailer sektor adalah blok 11.

| Byte | Parameter | Nilai/format | Fungsi | Penting 0–100 |
|---:|---|---|---|---:|
| 0 | Magic | 0xD7 | Penanda kartu pelanggan sistem ini | 100 |
| 1 | Version | 0x02 | Menandai Wallet V2 | 85 |
| 2 | Active | 0 atau 1 | Mengizinkan atau menolak kartu | 95 |
| 3 | Balance | 0..100 | Saldo tersedia, liter | 100 |
| 4 | Schedule | 0..3 | 0 belum diatur, 1 Pagi, 2 Siang, 3 Sore | 95 |
| 5 | Day high | byte tinggi | Hari kuota, big-endian | 100 |
| 6 | Day low | byte rendah | Hari kuota, big-endian | 100 |
| 7 | Used today | 0..30 | Liter yang sudah dicadangkan hari itu | 100 |
| 8 | Reserved | 0..30 | Nominal transaksi belum final; nol berarti tidak ada transaksi tertunda | 100 |
| 9 | CRC high | byte tinggi | CRC-16-CCITT byte 0–8 | 100 |
| 10 | CRC low | byte rendah | CRC-16-CCITT byte 0–8 | 100 |
| 11–15 | Reserved-zero | selalu 0x00 | Ruang format kosong yang juga divalidasi | 10 |

CRC menggunakan initial value 0xFFFF dan polinomial 0x1021. Hari adalah jumlah hari sejak 2026-01-01, dengan nilai nol pada tanggal tersebut. Firmware menerima tahun 2026 atau lebih baru.

Tidak ada UID, UID master, nama pelanggan, jam periode, jumlah kartu kelompok, riwayat transaksi, ID A1/A2, atau nilai kuota 30 L di blok kartu. UID dibaca langsung dari chip; jadwal jam dan kuota bersifat global pada firmware.

## 4. Kartu lama dan upgrade

Format lama ditandai byte pertama W dan hanya berisi revisi, saldo, serta status aktif. Dispenser menolak format ini dengan pesan KARTU LAMA / UPGRADE TOPUP.

Pada Topup, buka mode operator, tempel kartu lama, lalu tekan P1 ketika LCD menampilkan P1=UPGRADE. Saldo dan status dipertahankan; data baru diinisialisasi sebagai berikut:

- jadwal belum diatur;
- pemakaian hari ini nol;
- tidak ada cadangan transaksi.

Kartu wajib diberi jadwal sebelum dapat dipakai di Dispenser.

## 5. Perso B

Perso dipakai untuk kartu baru.

1. Jika belum ada master B, tempel master dan tahan P1+P3 selama 10 detik.
2. Setelah boot Perso, tempel master untuk membuka sesi operator.
3. Tempel kartu baru dan pertahankan posisi sampai pemeriksaan kestabilan selesai.
4. Perso mengganti trailer sektor 2 ke Key A/B firmware.
5. Perso menulis Wallet V2: saldo 0 L, aktif, jadwal belum diatur.
6. Perso membaca ulang semua 16 byte. Pesan berhasil hanya muncul jika isi cocok.

Kartu yang baru diperso harus dilanjutkan ke Topup untuk pengisian saldo dan pemilihan jadwal.

## 6. Topup B

Perso dan Topup adalah dua firmware berbeda untuk perangkat B yang sama. Master perlu didaftarkan pada mode B yang digunakan bila EEPROM belum berisi master.

| Aksi | Kontrol |
|---|---|
| Buka mode operator | Tempel master |
| Tambah saldo | Tekan-lalu-lepas P1/P2/P3: +5/+10/+20 L |
| Kurangi saldo | Tahan lebih dari 2 detik lalu lepas P1/P2/P3: -5/-10/-20 L |
| Ubah aktif/nonaktif | Tahan P1+P2; harus dilepas sebelum aksi berikutnya |
| Atur/ubah jadwal | Tahan P1+P3 2 detik pada kartu pelanggan |
| Pilih jadwal | P1=Pagi, P2=Siang, P3=Sore |
| Upgrade kartu lama | Saat pesan kartu lama, tekan P1 |

Saat memilih jadwal, LCD menampilkan penghitung Pagi/Siang/Sore dengan format P:x S:y R:z. Penghitung disimpan di EEPROM B dan baru diperbarui setelah write kartu diverifikasi.

**Batas penghitung:** setelah EEPROM B kosong atau firmware baru pertama dipasang, penghitung mulai dari nol. Firmware tidak dapat membangun inventaris otomatis dari kartu yang belum ditempel pada Topup. Angka ini hanya alat bantu pembagian antrean, bukan bukti jumlah pelanggan lengkap.

Jika Reserved tidak nol, Topup menampilkan TRANSAKSI TUNDA. Menu pencairan/refund cadangan **belum diimplementasikan**; kartu tersebut tidak boleh diubah sembarangan.

## 7. Dispenser A

### Pendaftaran master dan DS3231

EEPROM A1/A2 terpisah dari B. Kartu master yang sama harus didaftarkan satu kali pada setiap A.

1. Jika A belum memiliki master, tempel master dan tahan P1+P3 selama 10 detik.
2. Tempel master terdaftar. LCD menampilkan MASTER / P1=SET JAM.
3. Tekan P1 untuk masuk menu jam.
4. P1 menaikkan nilai; P2 berpindah Tahun, Bulan, Tanggal, Jam, Menit; P3 menyimpan ke DS3231.
5. Gagal simpan menampilkan RTC GAGAL TULIS.

### Validasi sebelum solenoid dibuka

Dispenser menolak transaksi apabila:

- CRC/magic/version tidak valid: PERLU PEMERIKSAAN;
- kartu format lama;
- kartu nonaktif atau saldo nol;
- Reserved tidak nol;
- DS3231 tidak siap;
- periode kartu tidak sama dengan waktu sekarang;
- Used today sudah 30 L.

Rumus izin pengambilan:

    sisa_hak = 30 - used_today
    izin_pengambilan = minimum(balance, sisa_hak)

Pada tanggal baru, Used today diperlakukan sebagai nol bila Reserved nol. Nilai baru itu disimpan bersamaan dengan write cadangan transaksi yang berikutnya.

### Reservasi dan flow

Saat pelanggan menekan pilihan, Dispenser langsung melakukan satu write kartu:

    balance    = balance - pilihan
    used_today = used_today + pilihan
    reserved   = pilihan

Kartu dibaca ulang. Jika verifikasi gagal, solenoid tidak dibuka dan LCD menampilkan GAGAL CADANGKAN / AIR TIDAK MULAI.

Target adalah 10/20/30 L = 1000/2000/3000 pulsa. Pulsa PA0 dihitung melalui interrupt dengan debounce 2 ms. Selama flow berjalan tidak ada write NFC setiap 100 pulsa. LED biru PB0 mengikuti pulsa valid.

Bila target tepat tercapai, Relay 1 ditutup lalu Dispenser menulis Reserved=0. Bila P2 ditekan, kartu terangkat, NFC gagal, atau finalisasi gagal, relay ditutup dan nilai Reserved tetap beku.

Karena hanya ada write sebelum start dan write sesudah target selesai, firmware tidak dapat mengetahui volume aktual bila transaksi putus di tengah jalan. Tidak ada pengembalian saldo otomatis.

## 8. Keselamatan dan keamanan

- Semua build ini memakai Key A MIFARE Classic yang sama. Ini fungsional, bukan anti-clone.
- CRC bukan MAC dan tidak melindungi kartu dari perubahan sengaja oleh pihak yang mengetahui format.
- UID master dibandingkan dari EEPROM; ini bukan autentikasi kriptografis.
- Satu blok tidak memiliki salinan pemulihan. Putus listrik saat write dapat membuat kartu rusak; Dispenser menolak kartu CRC salah.
- Build sukses bukan bukti relay menutup secara fisik, flowmeter akurat, PA0 aman pada 3,3 V, atau perangkat siap tersambung ke PLN.

## 9. Build yang diverifikasi

Perintah build:

    pio run -e smartdispenser_perso
    pio run -e smartdispenser_topup
    pio run -e smartdispenser_dispenser

Ketiga environment berhasil build. Belum ada upload ST-Link atau uji perangkat keras dalam pekerjaan ini.

## 10. Checklist uji perangkat keras

| Uji | Hasil yang diharapkan |
|---|---|
| DS3231 tidak ada | RTC BELUM SIAP; air tidak mulai |
| Set waktu master | Waktu tersimpan dan batas periode sesuai |
| Kartu Pagi 06:00 | Diterima bila aktif, saldo ada, tanpa cadangan |
| Kartu Pagi 10:00 | Ditolak sebagai luar jadwal |
| Ambil 20 L di A1 | Used today menjadi 20 L |
| Kartu sama di A2 | Maksimal hanya 10 L lagi pada hari sama |
| Hari berikutnya | Hak harian kembali 30 L |
| Saldo/sisa kuota 5 L | P1 menawarkan 5 L |
| Target 10/20/30 L | Relay menutup pada 1000/2000/3000 pulsa |
| Tidak ada flow 3 detik | P2 UNTUK STOP tanpa penutupan otomatis |
| P2/kartu dicabut | Relay menutup dan Reserved tetap ada |
| Putus daya saat write | Kartu CRC salah ditolak untuk pemeriksaan |
| Ubah jadwal Topup | Penghitung kelompok berubah setelah write sukses |

## 11. Pekerjaan lanjutan

- Menu operator terkontrol untuk pemeriksaan/pencairan cadangan beku.
- Rekonsiliasi penghitung jadwal Topup.
- Enkripsi, MAC, kunci per kartu, dan mitigasi clone/rollback.
- Jurnal dua blok yang tahan putus listrik.
- Uji nyata PN532, DS3231, LCD, flowmeter, relay, solenoid, dan kalibrasi pulsa/liter.
