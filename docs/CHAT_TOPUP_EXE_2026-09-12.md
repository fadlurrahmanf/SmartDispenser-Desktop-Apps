# Catatan Percakapan — SmartDispenser Topup EXE

Tanggal: 12 September 2026

## Keputusan utama

- Istilah perangkat yang digunakan: **alat Perso**, **alat Topup**, dan **alat Dispenser**.
- Lingkup aplikasi Windows ini hanya **Topup**. Alat Perso dan alat Dispenser tidak diubah.
- Aplikasi Topup menggantikan kontrol tombol/LCD operator; alat Topup menangani NFC, write kartu, readback, dan bridge COM.
- Database lokal menggunakan MySQL dari XAMPP pada `127.0.0.1`.
- Saldo resmi tetap berada pada kartu. Database menyimpan pelanggan, transaksi, audit, konfigurasi, dan backup.
- UID mentah, Key kartu, APDU, blok kartu, serta secret NFC tidak boleh ditampilkan atau disimpan aplikasi/database.
- Menu saldo: tambah/kurangi 10 L, 20 L, 30 L; batas saldo 0–100 L.
- Kartu Master didaftarkan sekali dengan kartu tetap tertempel 10 detik; setiap sesi EXE memerlukan tap Master kembali.
- Setiap mutasi harus memakai ID transaksi, write kartu, lalu readback final yang cocok sebelum dicatat sukses.
- Backup MySQL berjalan harian saat aplikasi aktif dan dapat dijalankan manual; hanya 30 backup terakhir disimpan.

## Desain UI yang disetujui

- Judul: **SmartDispenser Topup**.
- Gaya: dashboard desktop gelap modern, mengacu pada area dashboard dari gambar referensi; bukan panel editor widget.
- Teknologi UI: CustomTkinter.
- Sidebar empat halaman: Dashboard, Kartu & Topup, Riwayat, Pengaturan.
- Dashboard menampilkan status MySQL, alat Topup/COM, sesi Master, ringkasan kartu, aksi, dan audit terakhir.
- Kartu & Topup memuat data pelanggan/kartu, mutasi saldo, status aktif, jadwal, upgrade Wallet V2, dan pencairan cadangan.
- Riwayat mendukung pencarian nama, nomor HP, token kartu aman, atau tanggal.
- Pengaturan memuat konfigurasi MySQL, COM, dan backup.

## Prosedur penggunaan

### Setup pertama

1. Nyalakan MySQL XAMPP.
2. Jalankan EXE Topup.
3. Buka Pengaturan lalu Konfigurasi MySQL.
4. Isi host `127.0.0.1`, port `3306`, kredensial admin MySQL, dan PIN operator minimal enam digit.
5. Aplikasi membuat database `smartdispenser_topup`, akun aplikasi terbatas, skema, serta akun operator admin.

### Sambungkan alat Topup

1. Sambungkan USB alat Topup.
2. Tekan Pilih COM dan masukkan nomor COM, misalnya `COM3`.
3. EXE memeriksa bridge COM alat Topup.

### Daftar dan buka sesi Master

1. Jika Master belum ada, tempel kartu Master lalu tekan Daftar Master.
2. Kartu harus tetap tertempel selama 10 detik.
3. Untuk sesi normal: Login PIN, tempel kartu Master, lalu tekan Tap Master.
4. Sesi terkunci lagi jika EXE, COM, atau alat Topup restart/putus.

### Kartu pelanggan dan Topup

1. Tempel kartu pelanggan dan tekan Baca Kartu.
2. Untuk kartu baru, masukkan nama dan nomor HP.
3. Bila perlu, Upgrade Wallet V2.
4. Pilih tambah/kurangi saldo 10/20/30 L, status aktif/nonaktif, jadwal Pagi/Siang/Sore, atau Cairkan Cadangan.
5. Setujui dialog konfirmasi.
6. Aplikasi hanya mencatat transaksi berhasil setelah write dan readback final cocok.

### Riwayat dan backup

- Riwayat dapat dicari dengan nama, HP, token aman, atau tanggal `YYYY-MM-DD`.
- Backup manual ada di Pengaturan. Backup otomatis dicoba sekali per hari ketika aplikasi aktif.

## Status implementasi pada saat catatan dibuat

- EXE `SmartDispenserTopup.exe` telah berhasil dibangun dengan CustomTkinter.
- UI dashboard, mode simulasi, domain MySQL, dan bridge COM telah tersedia pada source.
- Unit test domain dan smoke test pembukaan EXE lulus.
- Integrasi MySQL XAMPP nyata, COM, firmware bridge yang di-upload, dan kartu NFC nyata masih memerlukan pengujian fisik.
