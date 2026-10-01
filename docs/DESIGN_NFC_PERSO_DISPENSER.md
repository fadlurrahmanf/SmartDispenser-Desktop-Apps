# Desain SmartDispenser A/B

## Revisi keputusan kartu — MIFARE Classic

Pengguna memberikan hasil scanner `MifareClassic, NfcA, NdefFormatable` dan
memutuskan tetap memakai kartu tersebut. UID empat byte bukan bukti kapasitas
atau keaslian chip. Target aktif berubah dari kandidat DESFire menjadi Classic;
bagian DESFire di bawah menjadi referensi historis, bukan persyaratan chip Classic.

Alur A/B, dua tipe kartu, saldo maksimum 100 L, cadangan/beku dan LCD tetap.
Enkripsi authenticated tetap dikerjakan firmware dengan secret di perangkat;
Classic memakai autentikasi sektornya sendiri, bukan AES authentication DESFire.
Tidak mengklaim ketahanan cloning/rollback setara DESFire: salinan lama beserta
MAC sah dapat lolos pada perangkat offline yang belum mengetahui revisi lebih baru.
Pemisahan kewenangan A/B melalui ACL Classic juga tidak mendapat jaminan keamanan
setara chip DESFire. Risiko ini wajib tercantum pada datasheet dan checklist.

Format Classic sudah diimplementasikan: dua bank pada sektor 1–5 dan 6–10,
masing-masing record 208 byte (marker 16, envelope GCM 179, padding 13). Envelope
memuat wallet kanonis 123 byte, header 40 byte, tag 16 byte. Master menggunakan
sektor 11, record 48 byte (header 32 dan AES-CMAC 16). Sektor 0 tidak ditulis.
Runtime memakai jendela 1K dengan SAK 08/18 dan UID empat byte; metadata ini bukan
bukti keaslian chip. Autentikasi semua sektor yang diperlukan tetap diverifikasi.
Key sektor 48-bit diturunkan secara terpisah; bukan kunci AES native pada Classic.
Recovery penulisan telah diuji simulator, masih memerlukan verifikasi kartu nyata.
Tidak memakai primitive commit/value-file DESFire sebagai bukti atomisitas Classic.
Kode DESFire dipertahankan terpisah; belum ada upload atau write kartu.

## Status dan batas implementasi

Desain disetujui melalui diskusi pengguna. Arahan lanjutan: selesaikan environment
software A/B dan uji host dahulu, baru ST-Link. Identifikasi chip tetap menjadi
gate pemilihan adapter/format kartu nyata, bukan penghalang implementasi aplikasi
independen. Firmware transaksi aman end-to-end belum selesai. Firmware
legacy `smartdispenser_lcd_arduino` v0x00020A05 tetap merupakan baseline lama,
bukan implementasi dompet, master permanen, KDF, atau authenticated encryption.

Profil baru `smartdispenser_card_identify` menyediakan probe metadata baca-saja
untuk B. Hasil metadata bukan bukti keaslian, keberhasilan autentikasi, atau
ketahanan transaksi. Belum ada bukti kartu fisik teridentifikasi dalam pekerjaan ini.

Urutan wajib: identifikasi kartu -> verifikasi kemampuan keamanan -> kunci format
memori/protokol/provisioning -> implementasi B -> implementasi A -> uji lintas alat.
Pekerjaan logika aplikasi, journal, dan primitive crypto dapat mendahului gate
hardware sesuai arahan terbaru; lihat `IMPLEMENTATION_STATUS_AB.md` untuk bukti
dan bagian yang masih belum terintegrasi. Jangan mengganti keamanan dengan UID
whitelist atau dompet plaintext.

## Sistem dan kartu

- Dua dispenser A1/A2 dengan flowmeter, solenoid, dan relay; satu alat perso B
  tanpa aktuator/flowmeter. Seluruhnya offline.
- Hanya dua tipe kartu: master (otorisasi B) dan pelanggan (pemakaian A,
  pengelolaan melalui B). Kunci induk sistem adalah data rahasia, bukan kartu ketiga.
- UID/ID tidak muncul di LCD. UID dipakai internal untuk identifikasi dan derivasi.
- Target aktif: MIFARE Classic sesuai keputusan pengguna. DESFire EV3 adalah
  kandidat historis, tidak dipakai sebagai klaim keamanan firmware Classic.
- Kartu tidak kompatibel ditolak untuk penggunaan dompet offline produksi.

## Keamanan dan derivasi kunci

Konsep input derivasi:

```text
K_card_role = KDF_AES_CMAC(
  secret_system,
  encode(UID_master, UID_customer, system_id, key_version, key_role)
)
```

Gunakan KDF standar AES-CMAC, encoding dengan batas panjang yang tidak ambigu,
serta pemisahan tujuan kunci. Algoritme konkret dan test vector harus dikunci
bersama protokol kartu; jangan menggunakan campuran karakter/hash UID tanpa secret.
Secret dibuat memakai sumber acak kriptografis saat provisioning. UID bersifat
publik; mengetahui semua UID tidak boleh memungkinkan perhitungan kunci.

Kunci pelanggan dipasang ke area kunci terlindungi chip, bukan file data biasa.
Secret sistem tidak disalin ke kartu pelanggan, LCD, log, atau repositori.
Data memakai authenticated encryption; nonce/counter mengikuti protokol terpilih
dan tidak digunakan ulang setelah reboot. Identitas sistem dan autentikasi wajib
diverifikasi sebelum saldo dipercaya. Marker/UID saja bukan bukti hasil perso.

UID master terdaftar dan material provisioning yang diperlukan disediakan ke A/B;
master tidak perlu ditempel ke A. Master sendiri memakai autentikasi kriptografis.
Keputusan pengguna terbaru: hanya satu master tetap pada B. Penggantian master
dan migrasi versi kunci tidak termasuk fitur yang diminta. Setelah pendaftaran
permanen, master kedua dan penggantian konfigurasi committed tetap ditolak.
Jika master hilang/rusak, operasi perubahan yang memerlukan master tidak dapat
dilakukan; tidak ada bypass atau reset otomatis. Prosedur pemulihan baru harus
dibahas tersendiri, bukan menghapus saldo atau konfigurasi diam-diam.

Pisahkan kewenangan B (issue/top-up/pencairan) dari A (debit/penyelesaian).
**Gate desain:** kemampuan A mengembalikan cadangan tidak boleh memberinya kredit
saldo tanpa batas. Buktikan dengan akses file/value/transaction pada chip aktual.
Jika chip hanya menyediakan kunci write umum, pemisahan tombol atau kunci software
tidak membuktikan pembatasan ini. Tinjau juga paparan secret pada perangkat lapangan.

Enkripsi/MAC tidak sendirinya mencegah rollback/copy/replay. Gabungkan autentikasi
chip, transaksi persisten, identitas operasi, dan penolakan penggunaan ulang.

## B: pendaftaran master

Jika belum memiliki master: kartu terdeteksi -> tahan P1+P3 10 detik terus-menerus
dengan kartu yang sama -> pasang autentikasi -> simpan identitas/status pendaftaran
ke EEPROM/nonvolatile -> readback/verifikasi -> sukses. Kartu terangkat/tombol
dilepas membatalkan hitungan. Tidak boleh menerima master kedua dari menu normal.

Pendaftaran melibatkan kartu dan perangkat sehingga tidak atomik lintas keduanya.
Sediakan jurnal tahap enrollment dan pemulihan idempotent sebelum mengklaim sukses;
reboot di antara perubahan kunci kartu dan penyimpanan master tidak boleh membuat
kartu hilang akses atau membuka enrollment master lain.

## B: operasi pelanggan

- Master membuka izin satu transaksi perubahan; habis ketika selesai/batal atau
  idle 60 detik. Bind izin ke kartu pelanggan selama wizard; kartu tertukar membatalkan.
- Kartu baru: deteksi -> P1 perso -> saldo awal 5/10/20 -> konfirmasi -> pilih
  aktif/nonaktif -> konfirmasi akhir -> tulis -> readback/verify -> hasil.
- Kartu lama: cek saldo, tambah 5/10/20, ubah aktif/nonaktif, pencairan saldo beku.
  Cek saldo tanpa master; perubahan harus dengan master.
- Aktif efektif = izin operator aktif DAN saldo tersedia >=1 L. Saldo nol tidak
  bisa dipakai; top-up menawarkan pengaktifan kembali dengan konfirmasi.
- Pencairan manual: tampilkan catatan, jumlah, saldo sebelum/sesudah, konfirmasi.
  Maksimum jumlah = saldo beku; sisa tidak dicairkan tetap beku.
- Catatan tidak lengkap: `PERLU PEMERIKSAAN`. Angka beku bukan bukti air belum keluar.
- Pada B, sebelum wizard pencairan ditampilkan peringatan `PERLU` / `PEMERIKSAAN`
  dua detik, lalu konfirmasi pencairan manual. Tidak mengubah kartu sebelum
  konfirmasi itu; jumlah dan saldo sebelum/sesudah dikonfirmasi lagi di akhir.
- Retry operasi yang sama tidak boleh menggandakan top-up/pencairan/perubahan.

## A: menu dan pengisian

Verifikasi kartu/status -> pesan dikenali -> saldo dan pilihan:

```text
  Saldo:20 L
P1:5 P2:10 P3:20
```

Pilihan melebihi saldo dikosongkan. Saldo 1..4 L: P1 mengambil seluruh saldo.
Pilihan -> P1 batal/P3 setuju -> pesan 2 detik -> P1 mulai. Nilai pilihan wajib
dicadangkan di kartu dan diverifikasi **sebelum** solenoid dibuka.

Flow PA0 dihitung melalui interrupt/debounce. Setiap 100 pulsa mencatat 1 L dari
cadangan dan memperbarui kartu. Progres memakai pulsa aktual; persentase kanan atas,
progress bar seluruh baris kedua, LED biru toggle tiap pulsa valid.

P2 stop. Target tercapai: tutup solenoid dan selesaikan saldo. Potongan normal
floor(pulsa/100): 523 pulsa dipotong 5 L. Sisa cadangan dikembalikan. Bedakan volume
hasil hitung dan jumlah potongan di laporan; konversi belum dikalibrasi.

Keputusan pengguna: setelah 3 detik tanpa pulsa, tampilkan permintaan P2 untuk stop,
solenoid tetap terbuka menunggu P2. Jika pulsa kembali, hitungan berjalan lagi dan
target tetap berlaku. Ini berbeda dari timeout auto-stop firmware legacy.

## Gangguan, saldo beku, lintas perangkat

Kartu hilang/komunikasi gagal: tutup solenoid, simpan hitungan terakhir, countdown
60 detik, P2 batal. Kartu sama kembali sebelum timeout: rekonsiliasi dulu lalu menu,
tanpa resume aliran otomatis. Batal/timeout membekukan cadangan yang belum selesai;
catatan tetap ada setelah kembali idle/reboot.

Saldo tersedia tetap dapat digunakan A1/A2. Cadangan lama yang tertinggal pada kartu
diperlakukan sebagai beku, bukan ditebak/dikembalikan otomatis. Hanya B dengan master
boleh mencairkan manual. Operasi pencairan harus menutup/mengurangi hak pengembalian
transaksi lama agar A asal tidak memberi refund lagi saat kartu kembali.

Simpan beberapa transaksi dengan identitas unik, asal, versi dan status penyelesaian;
jangan menimpa record lama dengan transaksi baru. Penuh -> tolak transaksi baru,
bukan hapus catatan unresolved. Pengguna menyetujui maksimum **empat catatan
cadangan/beku per kartu**. Pemilihan chip/format harus menyediakan kapasitas ini.

Batas saldo yang disetujui pengguna adalah **100 L**. Pembatasan diterapkan pada
total kuota belum terpakai (tersedia + cadangan/beku), sehingga pencadangan tidak
dapat dipakai untuk melewati batas top-up. Top-up yang melebihi batas ditolak utuh,
tidak dipotong diam-diam menjadi nominal lain. Pencairan hanya memindahkan saldo.

Laporan akhir: pemakaian, potongan, saldo tersedia, saldo beku (halaman terpisah bila
perlu); P3 selesai. Saat card write tidak dapat diverifikasi, label saldo belum final.

### Aturan rekonsiliasi yang wajib diterapkan

Status transaksi logis: RESERVED -> DISPENSING -> SETTLED, atau RESERVED/DISPENSING
-> FROZEN -> PARTIALLY_RELEASED/RELEASED. Nama ini kontrak perilaku, bukan format
byte kartu. `SETTLED` dan `RELEASED` bersifat final; retry tidak memberi kredit lagi.

- Cadangan berasal dari saldo tersedia, bukan saldo tambahan. Contoh reserve 5
  dari 20: tersedia 15, cadangan 5. Setelah debit terkonfirmasi 3: tersedia 15,
  cadangan 2. Penyelesaian normal mengembalikan 2 menjadi tersedia 17.
- Setiap checkpoint menulis nilai kumulatif pemakaian dan identitas operasi,
  bukan mengulang instruksi "kurangi 1" tanpa pemeriksaan hasil. ACK hilang harus
  diselesaikan dengan pembacaan status operasi sebelum retry.
- Jika kartu masih menyatakan cadangan 3 tetapi jurnal A menunjukkan pemakaian
  lebih besar, B tidak boleh menganggap 3 sebagai hak refund terverifikasi.
  Gunakan pemeriksaan operator sesuai kebijakan saldo beku.
- Dalam window 60 detik, hanya A asal dengan jurnal yang cocok dapat menyelesaikan
  sesi secara normal. Kartu berbeda tidak membuka relay dan tidak mengubah jurnal.
- Setelah sesi dibatalkan/timeout, A asal tidak lagi otomatis memberi refund dari
  jurnal lama. Catatan itu menjadi bukti untuk pemeriksaan, bukan hak kredit baru.
- A lain mengubah transaksi tertinggal menjadi FROZEN secara transaksional sebelum
  membuka transaksi baru. Saldo tersedia tetap sama; saldo beku tidak ditransfer
  ke tersedia. Jika penulisan/verifikasi gagal, transaksi baru tidak dimulai.
- Saat B mencairkan sebagian, saldo beku berkurang dan tersedia bertambah dalam
  satu transaksi kartu. Identitas asal tetap ada untuk mencegah penyelesaian ulang
  oleh A. Sisa hanya dapat dicairkan kembali melalui operasi B baru yang sah.
- A yang mendapati versi/status kartu lebih baru tidak menimpa kartu dengan jurnal
  lokal lama. Jika relasi versi/identitas tidak dapat dibuktikan, hentikan perubahan
  dan tampilkan perlu pemeriksaan, tanpa menghapus catatan.
- Konfirmasi sukses hanya setelah commit dan pembacaan terautentikasi menunjukkan
  operasi yang sama sudah diterapkan. Saldo sebelum/hasil hitung lokal saja bukan
  bukti berhasil ditulis ke kartu.

### Kasus penerimaan pembukuan

| Kasus | Hasil yang diharapkan |
|---|---|
| Saldo 20, pilih 5, selesai 500 pulsa | Tersedia 15; cadangan/beku transaksi nol |
| Saldo 20, pilih 5, stop normal 323 pulsa | Potong 3; tersedia 17 setelah verifikasi |
| Stop normal 99 pulsa dari pilihan 5 | Potong 0; seluruh cadangan kembali |
| Kartu hilang setelah 3 L sudah committed | Tersedia 15; sisa 2 menjadi beku setelah batal |
| Pemakaian akhir belum committed saat kartu hilang | Jangan klaim saldo final; pemeriksaan operator |
| ACK top-up/pencairan hilang setelah commit | Readback/retry tidak menambah saldo dua kali |
| B cairkan 1 dari beku 2 | Tersedia naik 1; beku tinggal 1; jurnal asal tidak memicu refund |
| Kartu kembali ke A asal setelah B mencairkan | Tidak ada kredit/debit ulang transaksi lama |
| Jurnal penuh dengan catatan belum selesai | Tolak sesi baru, pertahankan catatan dan saldo |

## Firmware, LCD, persistensi

Pisahkan profil A/B dan komponen security, wallet, journal, actuator, UI. B tidak
mendaftarkan interrupt flow atau mengaktifkan gate relay. A mempertahankan interlock,
reset relay 1/2 setelah jeda boot 1 detik dan durasi pulsa baseline. State gate bukan
bukti posisi kontak. Stop/target tidak boleh tertahan oleh transaksi NFC/LCD.

Pesan rata tengah, kata jelas, tanpa UID/ID; halaman >=1 detik; konfirmasi pilihan
2 detik. Release tombol wajib sebelum aksi berikut, stop segera tanpa lockout UI.
Saldo integer. Jurnal nonvolatile dengan pemeriksaan korupsi, identitas operasi,
commit/readback, kapasitas dan endurance yang diperhitungkan.

Power loss saat solenoid latching aktif dan persistensi pulsa terakhir memerlukan
pengujian hardware. Jangan menjanjikan hitungan presisi saat daya hilang atau
kontak menutup tanpa bukti karakteristik catu/aktuator.

## Acceptance dan urutan pengujian

1. Identifikasi beberapa sampel kartu; rekam metadata tanpa UID/key. Lanjut hanya
   setelah autentikasi, commit/anti-tear, akses dan kapasitas chip dibuktikan.
2. B: master reboot, pendaftaran terputus, kartu/master palsu, UID clone, wrong key,
   kartu tertukar, perubahan/status/readback, retry top-up/pencairan.
3. Security: data banyak kartu, tamper, replay/rollback snapshot, cloning, nonce
   reboot, pemisahan hak A/B, kunci tidak muncul di log/binary contoh repositori.
4. A: batas 99/100/199/523 pulsa; saldo 0/1/4/5/10/20; debounce, target, P2, no-flow
   3 detik, write latency, kartu hilang countdown 60 detik dan kartu berbeda.
5. Fault injection setiap tahap cadangan/debit/refund/enrollment/pencairan: kartu
   dicabut, reset/daya hilang, komunikasi corrupt, jurnal penuh, retry operasi sama.
6. A1-A2-B: saldo tersedia tetap dipakai, beberapa frozen records, pencairan manual,
   kembali ke A asal setelah pencairan, cegah debit/refund/pencairan ganda.
7. Bench low-voltage lalu kalibrasi volume. Build tidak sama dengan bukti lapangan.

## Rujukan

- NXP PN532 UM0701-02: https://www.nxp.com/docs/en/user-guide/141520.pdf
- NXP identifikasi DESFire/GetVersion: https://www.nxp.com/docs/en/application-note/AN11004.pdf
- NXP diversifikasi kunci: https://www.nxp.com/docs/en/application-note/AN10922.pdf
- NXP DESFire EV3: https://www.nxp.com/docs/en/data-sheet/MF3D_H_X3_SDS.pdf
