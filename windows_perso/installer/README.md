# Installer SmartDispenser Perso

`SmartDispenserPersoSetup.exe` ditujukan untuk Windows 10/11 x64 dan memasang:

- aplikasi desktop SmartDispenser Perso;
- Microsoft Edge WebView2 Runtime x64 melalui installer offline resmi Microsoft;
- driver USB-Serial CH340 yang sesuai dengan reader Perso saat ini;
- MariaDB lokal pada PC yang belum memiliki service MySQL/MariaDB;
- Database `Perso_database` dan akun aplikasi dengan password acak;
- shortcut Start Menu dan Desktop.

WebView2 dan paket driver CH340 diverifikasi setelah pemasangan. Ketika Board
CH340 dihubungkan, Windows akan membuat COM Port secara otomatis; aplikasi
kemudian mencari seluruh COM non-Bluetooth sampai menemukan respons Board Perso.

Setup hanya dinyatakan berhasil setelah akun aplikasi dapat membuka
`Perso_database`. Jika password `root` salah atau Database tidak siap, setup
berhenti dengan pesan perbaikan dan tidak menjalankan aplikasi menggunakan
konfigurasi lama.

Installer meminta password administrator Database. Password akun aplikasi dibuat
secara acak ketika instalasi dan disimpan terenkripsi dengan DPAPI scope mesin di
`%ProgramData%`, sehingga tetap dapat dibaca saat aplikasi dijalankan oleh akun
operator Windows yang berbeda dari akun UAC. Credential dari komputer build
tidak pernah dimasukkan ke installer.

Jika XAMPP masih memakai akun `root` tanpa password, kosongkan kedua kolom
password pada wizard. Untuk Database baru, buat password minimal 10 karakter.

## Build

Jalankan PowerShell sebagai user biasa dari folder ini:

```powershell
.\build_installer.ps1 -RefreshPrerequisites
```

Hasil:

```text
output\SmartDispenserPersoSetup.exe
```

Build hanya membuat paket desktop. Proses ini tidak meng-upload firmware,
mereset board, atau mengoperasikan kartu.
