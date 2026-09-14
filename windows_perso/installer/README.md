# Installer SmartDispenser Perso

`SmartDispenserPersoSetup.exe` ditujukan untuk Windows 10/11 x64 dan memasang:

- aplikasi desktop SmartDispenser Perso;
- Microsoft Edge WebView2 Runtime x64 melalui installer offline resmi Microsoft;
- driver USB-Serial CH340 yang sesuai dengan reader Perso saat ini;
- MariaDB lokal pada PC yang belum memiliki service MySQL/MariaDB;
- Database `Perso_database` dan akun aplikasi dengan password acak;
- shortcut Start Menu dan Desktop.

Installer meminta password administrator Database. Password akun aplikasi dibuat
secara acak ketika instalasi dan disimpan sebagai environment variable milik user
Windows, sesuai kontrak aplikasi saat ini. Credential dari komputer build tidak
pernah dimasukkan ke installer.

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
