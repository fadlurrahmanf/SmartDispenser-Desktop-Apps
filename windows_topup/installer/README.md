# Installer SmartDispenser Topup

`SmartDispenserTopupSetup.exe` ditujukan untuk Windows 10/11 x64 dan memasang:

- aplikasi desktop SmartDispenser Topup;
- Microsoft Edge WebView2 Runtime x64;
- driver USB-Serial CH340;
- MariaDB lokal bila belum ada service MySQL/MariaDB;
- Database `smartdispenser_topup`, skema, dan akun aplikasi terbatas;
- konfigurasi aplikasi yang dilindungi Windows DPAPI;
- shortcut Start Menu dan Desktop.

Setup hanya dinyatakan berhasil setelah akun aplikasi dapat membuka schema
Topup dan data operator terverifikasi. Jika password `root` salah atau Database
tidak siap, setup berhenti dengan pesan perbaikan dan tidak menjalankan
aplikasi menggunakan konfigurasi lama.

Setup meminta password administrator Database. Password itu hanya dipakai selama
provisioning dan tidak disimpan oleh aplikasi. Password akun aplikasi dibuat acak,
sedangkan PIN operator Topup ditetapkan ke `202610`; keduanya disimpan terenkripsi
untuk user Windows yang menjalankan installer.

Jika XAMPP masih memakai akun `root` tanpa password, kosongkan kedua kolom
password pada wizard. Untuk Database baru, buat password minimal 10 karakter.

## Build

```powershell
.\build_installer.ps1
```

Gunakan `-RefreshPrerequisites` hanya bila paket prasyarat perlu diunduh ulang.
Hasil build berada di `output\SmartDispenserTopupSetup.exe` bersama checksum SHA-256.

Build installer tidak meng-upload firmware, membuka COM, atau mengoperasikan kartu.
