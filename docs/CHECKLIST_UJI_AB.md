# Checklist uji perangkat SmartDispenser A/B

Status: daftar penerimaan untuk pengguna, **belum hasil uji**. Firmware end-to-end
masih dikerjakan; tersedianya checklist ini tidak menyatakan binary siap digunakan.
Rujukan perilaku: `DESIGN_NFC_PERSO_DISPENSER.md`. Tidak ada UID atau secret yang
perlu dicantumkan dalam laporan pengguna.

## Pembagian kerja dan persiapan

Codex menyelesaikan firmware A/B, pemeriksaan kode, build dan daftar penyimpangan
design. Pengguna menjalankan pengujian perangkat setelah paket firmware diserahkan.
Upload/ST-Link bukan bagian dari pekerjaan implementasi saat ini.

- Catat versi/hash firmware, board A1/A2/B, tipe kartu, catu uji dan tanggal.
- Gunakan kartu uji dan saldo uji; jangan memakai kartu operasional untuk fault injection.
- Mulai dengan bench tegangan rendah terisolasi. Jangan menghubungkan ST-Link,
  UART/USB atau alat ukur ber-ground ketika board terhubung PLN tanpa tinjauan
  isolasi dan prosedur oleh personel kompeten. Checklist ini bukan izin uji AC220.
- Siapkan cara memutus catu aktuator bila kontrol gagal. Uji no-flow memang
  mempertahankan solenoid terbuka sampai P2, sesuai keputusan design.
- PA0 maksimum 3,3 V. Gunakan sumber pulsa terukur; frekuensi/rentang sensor dan
  debounce harus dicatat, bukan diasumsikan mampu menerima sembarang pulsa.
- Untuk setiap baris, isi hasil LULUS/GAGAL/BELUM DIUJI dan lampirkan bukti jika
  perlu. Jangan menyalin kunci rahasia, dump provisioning atau UID ke laporan.

## Boot, tombol dan tampilan

| ID | Langkah | Hasil yang diharapkan |
|---|---|---|
| IO-01 | Boot A; amati gate kedua relay dengan alat ukur sesuai bench | Gate awal tidak aktif; urutan pulsa RST dimulai setelah jeda boot 1 detik, kedua relay di-reset; SET/RST tidak aktif bersamaan |
| IO-02 | Periksa kontak kedua relay saat uji reset | Posisi kontak sesuai NC yang dimaksud pengguna; state software saja tidak menjadi bukti |
| IO-03 | Boot/operasikan B | Tidak ada pulsa aktuator atau alur flowmeter |
| IO-04 | Tekan U6, U8, U9 | Berturut-turut P1, P2, P3 |
| IO-05 | Tahan tombol, cancel lalu tetap tahan/tekan cepat | Tidak menyeleksi/menyetujui halaman berikutnya tanpa pelepasan tombol; jeda antarmuka diterapkan |
| IO-06 | Telusuri semua halaman | Tidak ada UID/ID; teks rata tengah; pesan minimal 1 detik; label tidak terpotong; persentase progres tetap kanan atas |

## Master dan pengelolaan B

| ID | Langkah | Hasil yang diharapkan |
|---|---|---|
| B-01 | B belum punya master: kartu tetap tertempel, tahan P1+P3 10 detik | Satu master terdaftar dan terverifikasi; masih dikenali setelah reboot |
| B-02 | Lepas tombol/angkat/ganti kartu sebelum 10 detik | Hitungan batal; kartu lain tidak meneruskan hitungan sebelumnya |
| B-03 | Setelah master terdaftar, coba daftarkan kartu lain | Tidak mengganti atau menambah master melalui menu biasa |
| B-04 | Baca kartu lama tanpa master; coba ubah saldo/status | Cek saldo boleh; perubahan ditolak |
| B-05 | Autentikasi master, lalu satu operasi perubahan | Izin habis setelah selesai/batal; tidak berlaku untuk operasi kedua |
| B-06 | Autentikasi master, diamkan 60 detik | Izin perubahan kedaluwarsa |
| B-07 | Perso kartu baru masing-masing 5/10/20, status aktif/nonaktif | Setiap langkah memiliki konfirmasi/cancel; write hanya setelah persetujuan akhir; hasil dibaca ulang sebelum sukses |
| B-08 | Batalkan pada tiap tahap perso/top-up/status | Tidak ada perubahan saldo yang tidak disetujui |
| B-09 | Isi saldo hingga batas 100 L; coba tambah melebihi batas | Batas total kuota belum terpakai (tersedia + cadangan/beku) tidak dilampaui |
| B-10 | Isi ulang kartu saldo nol | Ada pilihan pengaktifan kembali; hasil status sesuai konfirmasi |
| B-11 | Cairkan sebagian/seluruh saldo beku dengan master | Jumlah dibatasi saldo beku; tampil saldo sebelum/sesudah; konfirmasi wajib |
| B-12 | Catatan transaksi tidak lengkap | Tampil PERLU PEMERIKSAAN; tidak otomatis menganggap saldo beku sebagai air yang belum keluar |

## Dispenser A

| ID | Langkah | Hasil yang diharapkan |
|---|---|---|
| A-01 | Tempel kartu tidak sah/nonaktif | Tidak dapat memulai pengisian; indikator/pesan penolakan sesuai design |
| A-02 | Uji saldo 0/1/4/5/10/20 | 0 tidak bisa dipakai; 1–4 diambil seluruhnya melalui P1; pilihan 5/10/20 hanya muncul bila cukup |
| A-03 | Pilih, cancel/setuju, lalu mulai | P1 batal/P3 setuju; pesan pilihan 2 detik; P1 memulai; belum ada aliran sebelum start |
| A-04 | Gagalkan write pencadangan sebelum start | Solenoid tidak dibuka |
| A-05 | Pilih 5/10/20 dan kirim 500/1000/2000 pulsa | Relay berhenti pada target; pulsa/progres sesuai; LED biru mengikuti pulsa valid |
| A-06 | Tekan P2 saat aliran berjalan | Aliran berhenti dan laporan akhir tersedia; stop tidak menunggu durasi halaman LCD |
| A-07 | Tidak ada pulsa selama 3 detik, juga setelah sebelumnya ada pulsa | Permintaan P2 untuk stop muncul; solenoid tetap terbuka sampai P2 sesuai design |
| A-08 | Stop pada 99/100/199/523 pulsa | Potongan masing-masing 0/1/1/5 L; sisa cadangan kembali pada penghentian normal |
| A-09 | Target tercapai atau dihentikan | Laporan pemakaian, potongan, saldo tersedia/beku dapat dibaca; P3 menutup laporan |
| A-10 | Saldo tersedia menjadi nol | Tidak menawarkan pengisian baru; status efektif nonaktif |

## Kartu terangkat, restart dan lintas perangkat

| ID | Langkah | Hasil yang diharapkan |
|---|---|---|
| R-01 | Angkat kartu/gagalkan komunikasi ketika mengisi | Solenoid ditutup; countdown 60 detik dan P2 batal; catatan terakhir disimpan |
| R-02 | Kartu yang sama kembali sebelum timeout | Transaksi lama diselesaikan dulu; kembali ke menu; tidak melanjutkan aliran otomatis |
| R-03 | Kartu berbeda ditempel ketika menunggu | Tidak menyelesaikan transaksi lama memakai kartu baru |
| R-04 | Timeout/P2 batal tanpa kartu | Sisa yang belum dapat diselesaikan menjadi kasus beku/pending untuk rekonsiliasi; tidak ditebak sebagai saldo refund pasti |
| R-05 | Bawa kartu ke A2 lalu ke B | Saldo tersedia tetap dapat dipakai sesuai rekonsiliasi; pencairan beku hanya melalui B dan master |
| R-06 | Cairkan di B, lalu kembali ke A asal dengan jurnal lama | Tidak ada refund/pencairan kedua |
| R-07 | Buat empat record cadangan/beku, lalu coba transaksi tambahan | Ditolak bila semua slot penuh; record lama tidak dihapus diam-diam |
| R-08 | Penuhi jurnal lokal dengan kasus belum selesai | Transaksi baru ditolak; catatan belum selesai tetap tersimpan |
| R-09 | Putus catu pada enrollment, reserve, checkpoint, settle, freeze, top-up dan release | Setelah restart tidak ada aliran otomatis, master ganda, saldo bertambah ganda atau transaksi hilang diam-diam |
| R-10 | Write/commit terjadi tetapi balasan ke perangkat hilang; ulangi operasi yang sama | Rekonsiliasi/readback menentukan hasil; retry tidak menggandakan transaksi |

## Keamanan dan pengukuran tambahan

Pengujian berikut memerlukan alat uji NFC/fault injection yang sesuai; gunakan
kartu milik sendiri dan jangan menonaktifkan proteksi firmware untuk meluluskannya.

| ID | Pengujian | Hasil yang diharapkan |
|---|---|---|
| S-01 | Kartu/master palsu, termasuk UID sama tetapi tanpa key yang benar | Autentikasi gagal; tidak ada akses saldo atau izin operator |
| S-02 | Kunci salah, data/ciphertext/tag/status diubah | Ditolak; hasil yang belum sah tidak digunakan |
| S-03 | Salin data ke UID berbeda, replay transaksi API, lalu uji salinan penuh UID+sektor dan rollback dua bank | UID berbeda dan retry API ditolak/tidak menggandakan saldo. Salinan penuh serta rollback offline pada Classic adalah batas keamanan yang diketahui, bukan klaim terlindungi; catat hasil tanpa mengklaim lulus anti-cloning |
| S-04 | Coba top-up/perubahan izin melalui API A; evaluasi terpisah board A yang dikompromikan | Firmware A menolak API operator dan tidak membawa kunci issuer/master. Classic tidak menyediakan pembatasan debit-only untuk data GCM; board A yang dikompromikan masih berisiko memalsukan saldo. Jangan menilai sebagai proteksi chip setara DESFire |
| S-05 | Baca data beberapa kartu pelanggan | Tidak ada kunci sistem/master tersimpan sebagai data biasa; verifikasi keamanan tidak hanya berdasarkan tampilan data acak |
| M-01 | Ukur pulsa gate SET/RST dan latensi stop target/P2/kartu hilang | Catat angka aktual, overshoot, dan kondisi pengujian; cocokkan dengan batas penerimaan yang ditetapkan |
| M-02 | Uji bounce/noise dan rentang frekuensi sumber pulsa | Tidak menghitung bounce sebagai pulsa baru; tidak kehilangan pulsa valid dalam rentang yang disetujui |
| M-03 | Kalibrasi terhadap volume ukur | 100 pulsa/L masih konfigurasi awal; akurasi liter baru dinyatakan dari hasil kalibrasi |
| M-04 | Uji durasi panjang/penulisan berulang | Catat kestabilan, waktu NFC/EEPROM dan pemulihan error; tidak menyimpulkan endurance hanya dari beberapa kali uji |
| UI-LED-01 | Kartu tidak dikenal, lalu tetap ditempel lebih dari 3 detik | Merah menyala selama pesan 3 detik; kembali utama, menunggu kartu dilepas sebelum deteksi baru |
| UI-LED-02 | Pelanggan dikenali, menu, konfirmasi dan mulai; kemudian pulsa valid | Biru menyala sebelum dispensing; saat dispensing hanya pulsa valid yang men-toggle biru, refresh LCD tidak menimpanya |
| UI-CARD-01 | Cabut/tukar kartu pada pesan dikenali, menu A/B, dan akhir jeda pilihan 2 detik | Menu dibatalkan, izin perubahan B dicabut; tidak maju ke Start atau mengubah saldo kartu pengganti |
| M-STOP-01 | Tahan P2 ketika transaksi NFC sedang berjalan | Jalur timer meminta RST setelah debounce, tidak menunggu selesainya NFC; ukur waktu aktual, jangan memakai 30 sampel sebagai bukti latensi kontak |

## Format laporan pengguna

Untuk setiap kegagalan, catat: ID uji, versi firmware, perangkat, langkah terakhir,
saldo awal/pilihan, pulsa aktual, teks LCD, keadaan relay, hasil yang diharapkan,
hasil aktual, dan bukti foto/video/log yang tidak mengandung secret atau UID.
Status yang belum diuji tetap ditulis BELUM DIUJI dalam technical datasheet.
