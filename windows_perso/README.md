# SmartDispenser Personalization Console

Folder ini adalah satu-satunya aplikasi desktop Perso aktif/default untuk
SmartDispenser. Antarmuka operator menggunakan HTML/WebView2 dengan backend
Python yang mengelola Database, serial bridge, customer, Card Precheck,
Personalization, dan Activity Logs.

## Batas sistem

- Board tetap memegang NFC Reader, autentikasi, kunci, dan mutasi kartu.
- Aplikasi tidak menampilkan atau menyimpan UID, Key A, Key B, secret MAC,
  maupun isi block terlindungi.
- Test Card dan Identify Card Owner bersifat read-only.
- Personalization menulis kartu hanya setelah Database reservation berhasil,
  konfirmasi operator, dan Card Precheck selesai.

## Jalankan source

```powershell
py -3 functional_web_app.py
```

## Verifikasi

```powershell
py -3 -m py_compile app.py functional_web_app.py perso_core.py
py -3 -m unittest discover -s tests -v
py -3 tools\smoke_customer_input.py
py -3 tools\smoke_functional_html.py
py -3 tools\smoke_operator_views.py
```

## Build default

```powershell
.\build.ps1
```

Hasil default berada di `release\SmartDispenserPerso.exe`. Build tidak
melakukan upload, flash, reset, atau pengoperasian hardware.

## Installer untuk komputer baru

Folder source atau EXE saja belum menjamin aplikasi dapat dipakai pada Windows
yang benar-benar bersih. Gunakan installer dari:

```text
installer\output\SmartDispenserPersoSetup.exe
```

Petunjuk build dan cakupan prerequisite ada di `installer\README.md`.
