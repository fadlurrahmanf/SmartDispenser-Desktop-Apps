# Prompt setup manual SmartDispenser

## Sumber file resmi
Gunakan repository GitHub berikut sebagai sumber file, bukan file dari chat:

```text
https://github.com/fadlurrahmanf/SmartDispenser-Desktop-Apps
```

Perintah mengambil source:

```powershell
git clone https://github.com/fadlurrahmanf/SmartDispenser-Desktop-Apps.git C:\SmartDispenser\SmartDispenser
```

Jika Git belum terpasang, buka halaman repository tersebut, pilih **Code → Download ZIP**, ekstrak menjadi `C:\SmartDispenser\SmartDispenser`, lalu lanjutkan prompt di bawah. Repository ini privat; login GitHub diperlukan.

## PC Perso
Salin folder `SmartDispenser` ke `C:\SmartDispenser\SmartDispenser`, buka PowerShell **Run as Administrator**, lalu jalankan:

```powershell
cd C:\SmartDispenser\SmartDispenser
py -3.12 -m pip install -r .\windows_perso\requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\manual_setup_perso.ps1
cd .\windows_perso
py -3.12 .\functional_web_app.py
```

## PC Topup
Salin folder yang sama ke `C:\SmartDispenser\SmartDispenser`, buka PowerShell **Run as Administrator**, lalu jalankan:

```powershell
cd C:\SmartDispenser\SmartDispenser
py -3.12 -m pip install -r .\windows_topup\requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\manual_setup_topup.ps1
cd .\windows_topup
py -3.12 .\app_perso_style.py
```

Saat script meminta password, masukkan password root MariaDB yang dibuat pada komputer tersebut. Jika root tanpa password, tekan Enter. PIN operator Topup default `202610`.

Home baru tampil setelah Database, board, dan master card berhasil diverifikasi.
