# Perso ESP32 — PN532 I2C

Firmware ini adalah alat Perso kartu baru untuk aplikasi desktop
`SmartDispenserPerso.exe`. Port USB ESP32 memakai 115200 baud dan hanya
menerima protokol bridge aplikasi yang dibatasi; UID, key, dan block mentah
tidak dikirim ke PC.

## Wiring PN532 (ESP32 DevKit klasik)

| PN532 I2C | ESP32 |
|---|---|
| VCC | 3V3 |
| GND | GND |
| SDA | GPIO21 |
| SCL | GPIO22 |

PN532 harus diposisikan pada mode **I2C**. Jangan memberi VCC PN532 5 V bila
modul menarik SDA/SCL ke 5 V; GPIO ESP32 hanya 3,3 V.

## Build dan upload

```powershell
cd D:\IoT\SmartDispenser\firmware\perso_esp32
C:\Users\MSI\.platformio\penv\Scripts\pio.exe run -e perso_esp32
C:\Users\MSI\.platformio\penv\Scripts\pio.exe run -e perso_esp32 -t upload --upload-port COM3
```

Untuk melihat data protokol dari boot melalui monitor:

```powershell
C:\Users\MSI\.platformio\penv\Scripts\pio.exe device monitor -p COM3 -b 115200
```

Tutup monitor sebelum menjalankan EXE karena keduanya tidak dapat memakai COM3
bersamaan.
