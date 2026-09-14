# Topup MySQL XAMPP

1. Instal XAMPP dan jalankan **MySQL** pada `127.0.0.1:3306`.
2. Instal dependensi: `py -3.12 -m pip install -r requirements.txt`.
3. Pastikan `topup.provisioning.json` berada di folder yang sama dengan aplikasi.
4. Jalankan aplikasi. Pada penggunaan pertama Database dan operator dibuat
   otomatis dari file konfigurasi tersebut, tanpa dialog input.
5. Aplikasi membuat database `smartdispenser_topup` serta akun MySQL terbatas untuk EXE.

Startup normal berjalan otomatis dengan urutan: verifikasi Database, temukan
Topup Board, autentikasi PIN operator, baca master card, lalu buka dashboard.

EXE menolak perubahan kartu bila MySQL mati. Kartu dan saldo tetap dikelola alat Topup; database menyimpan pelanggan serta audit.
