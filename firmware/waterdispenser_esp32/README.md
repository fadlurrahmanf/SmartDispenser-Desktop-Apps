# SmartDispenser ESP32-C3 firmware

Environment PlatformIO terpisah untuk desain `WaterDispenserESP32`.
Firmware STM32 lama tidak diubah.

## Environment

- `esp32_dispenser`: dispenser, SSR RLY1/RLY2 selalu OFF saat boot.
- `esp32_topup`: bridge Topup lewat UART dan PN532 I2C.
- `esp32_perso`: bridge Personalization lewat UART dan PN532 I2C.

Bangun salah satu image:

```powershell
platformio run -e esp32_dispenser
platformio run -e esp32_topup
platformio run -e esp32_perso
```

Tidak ada perintah upload pada dokumen ini. Upload/energisasi perangkat tetap
memerlukan otorisasi dan uji low-voltage terpisah.

## Pin yang berasal dari skematik

| Fungsi | ESP32-C3 |
|---|---:|
| PN532/LCD/RTC SDA | GPIO4 |
| PN532/LCD/RTC SCL | GPIO5 |
| SSR RLY1 | GPIO10 |
| SSR RLY2 | GPIO18 |
| Flow pulse | GPIO3 |
| UART bridge RX/TX | GPIO20 / GPIO21 |
| Tombol P1 / SW1 | GPIO6 (aktif LOW, sisi lain GND) |
| Tombol P2 / SW2 | GPIO7 (aktif LOW, sisi lain GND) |
| Tombol P3 / SW3 | GPIO19 (aktif LOW, sisi lain GND) |

Net tombol diverifikasi dari source skematik EasyEDA asli: SW1→IO6,
SW2→IO7, dan SW3→IO19. GPIO6/GPIO7 bukan LED dan tidak boleh didorong sebagai
output. Source tersebut belum membuktikan net LED/indikator terpisah; indikator
kosmetik karenanya dinonaktifkan sampai jalurnya ditelusuri secara fisik.

## Secret kartu

`CompactCardSecurity.h` membutuhkan `compact_card_secret.h`. File privat ini
memuat secret MAC serta Key A/Key B kartu, dan berada pada
`firmware/smartdispenser_firmware/.private/` untuk dipakai bersama profil
STM32 dan ESP32. File tersebut tidak boleh masuk ke Git, log, atau paket
distribusi. Untuk kartu yang sudah berjalan, pulihkan file privat dari backup
aman; jangan menjalankan generator karena akan menghasilkan kredensial baru
yang tidak cocok dengan kartu lama.
