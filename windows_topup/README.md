# SmartDispenser Top-up Windows

## Unduh installer Windows

[Unduh SmartDispenserTopupSetup.exe](https://github.com/fadlurrahmanf/SmartDispenser-Desktop-Apps/releases/download/v1.0.1/SmartDispenserTopupSetup.exe)

Jalankan setup sebagai Administrator dan ikuti wizard instalasi. Paket Release
menyertakan prerequisite untuk pemasangan pada komputer Windows baru.

Aplikasi desktop Windows berbahasa Indonesia untuk operator top-up. Aplikasi
tidak mengakses perintah PN532 mentah, kunci kartu, APDU, atau data blok NFC.
Reader USB hanya bridge domain-terbatas.

## Jalankan dan uji

```powershell
py -3.12 app_perso_style.py
py -3.12 -m unittest discover -s tests -v
py -3.12 tools\smoke_startup.py
```

Mode awal adalah simulasi sehingga tidak membuka COM atau perangkat. Audit
lokal JSONL menyimpan token kartu hash/potong, bukan UID. `build.ps1` hanya
menggunakan PyInstaller bila sudah tersedia; script tidak menginstal dependensi.
Build default memakai antarmuka bergaya Perso dengan startup otomatis untuk
memeriksa Database dan mencari Board Topup. Artefak terbaru berada di
`release\SmartDispenserTopup.exe`; artefak lama di `dist*` tetap dipertahankan.

Build/tes tidak membuktikan USB, PN532, autentikasi, atau penulisan kartu nyata.
Lihat [kontrak USB](docs/USB_READER_CONTRACT.md). Firmware menyediakan bridge
domain-terbatas; Test Card memakai mode presence-only terisolasi seperti Perso,
sedangkan operasi Wallet tetap khusus Topup dan fail-closed.
