# SmartDispenser A/B — Technical Datasheet (Draft)

Status: implementasi firmware dan simulasi host; belum diuji pada perangkat.
Bukan datasheet produk teruji/siap produksi.
Rincian dan gate: [Desain NFC A/B](DESIGN_NFC_PERSO_DISPENSER.md).

| Parameter | Spesifikasi target | Status |
|---|---|---|
| Arsitektur | Dua dispenser A1/A2, satu alat perso B, offline | Disepakati |
| Kartu | Master dan pelanggan | Diimplementasikan; simulator diuji |
| Chip kartu | MIFARE Classic berdasarkan hasil scanner pengguna | Dipilih pengguna; kapasitas/keaslian belum diverifikasi |
| Batas keamanan Classic | Enkripsi + MAC firmware tidak menjamin penolakan salinan saldo lama lintas perangkat offline; tidak mengklaim anti-cloning setara DESFire | Batas desain revisi; belum uji perangkat |
| Kewenangan saldo Classic | Top-up hanya B dibatasi firmware; blok saldo dapat ditulis dengan key A/B. Tidak menjamin pembatasan ini jika perangkat A atau secret dikuasai penyerang | Batas desain revisi |
| Pembaca | PN532 I2C 0x24 | Konfigurasi firmware baseline |
| LCD | 16x2 I2C 0x27, pesan center, tanpa UID/ID | UI dompet tersedia; visual perangkat belum diuji |
| Tombol | P1 U6/PB3, P2 U8/PB4, P3 U9/PA11 | Konfigurasi baseline |
| Pilihan | 5/10/20 L dibatasi saldo, 1..4 L seluruh sisa | Diimplementasikan dan diuji host |
| Perhitungan | 100 pulsa/L; tagihan floor(pulsa/100) | Asumsi konfigurasi, belum kalibrasi |
| Input flow | PA0; pengguna menyatakan maksimum 3.3 V | Belum pengukuran independen |
| Saldo | Cadangan sebelum start, pencatatan tiap 100 pulsa | Logika dan adapter Classic diuji simulator; timing fisik belum |
| Saldo maksimum | 100 L total kuota belum terpakai | Disetujui pengguna |
| Catatan cadangan/beku | Maksimum 4 per kartu; penuh menolak sesi baru | Disetujui pengguna |
| Kartu hilang | Solenoid stop, countdown 60 detik/P2 batal | Diimplementasikan, diuji host; latensi fisik belum |
| No-flow 3 detik | Pesan P2 stop; solenoid tetap terbuka menunggu P2 | Diimplementasikan sesuai keputusan pengguna, diuji host |
| Saldo beku | Saldo tersedia tetap dapat dipakai; pencairan manual hanya B + master | Diimplementasikan, diuji host; warning pemeriksaan sebelum pencairan |
| Proteksi data | Authenticated encryption, kunci unik per kartu terikat UID master/pelanggan | Modul KDF/AEAD diuji terpisah; kartu belum |
| Pendaftaran master | P1+P3 10 detik; satu master permanen dan otorisasi satu transaksi | Diimplementasikan, simulator diuji; kartu fisik belum |
| Master tetap | Satu master pada B; tanpa penggantian atau migrasi, sesuai keputusan pengguna terbaru | Master kedua ditolak; kehilangan master menghalangi operasi perubahan pada B |
| Waktu layar | Minimal 1 detik, pilihan 2 detik; stop tidak menunggu UI | Diimplementasikan; timing LCD dan latensi kontak perlu pengukuran |

Saldo beku tidak membuktikan jumlah air yang belum keluar. Pencairan manual adalah
penyesuaian operator jika catatan terputus; bukan rekonsiliasi otomatis terverifikasi.
Cadangan/refund/retry wajib diuji agar tidak menggandakan kredit. Relay latching
dan kehilangan daya memerlukan validasi penutupan fisik. Tidak ada klaim akurasi
volume, kesiapan instalasi PLN, atau anti-cloning produksi sebelum uji selesai.

Firmware identifikasi tersedia sebagai tahap awal; tidak menulis kartu, mengubah
kunci, mengoperasikan relay, atau menjalankan transaksi pelanggan. Environment
aplikasi A/B terpisah sudah build dengan adapter Classic dan provisioning
terintegrasi. Board tanpa konfigurasi valid tetap menolak transaksi. Profil A mempulse RST saat boot, sehingga
tidak setara dengan firmware identifikasi baca-saja.
