# Blink PC13

Program ini adalah smoke test SWD untuk modul `STM32L071RBT6` yang sedang
terpasang. Program hanya mengakses clock GPIOC dan pin PC13.

`LED1` pada skematik modul terhubung dari VCC ke PC13 melalui resistor, sehingga
LED aktif saat PC13 LOW. Blink dibuat dengan delay software menggunakan clock
reset internal; tidak menginisialisasi HSE/LSE, radio, UART, I2C, flow sensor,
PN532, maupun output relay.

## Koneksi yang diperlukan

- ST-Link SWCLK ke PA14/SWCLK.
- ST-Link SWDIO ke PA13/SWDIO.
- GND bersama.
- Target diberi 3,3 V yang stabil.
- NRST ke reset target untuk recovery bila koneksi SWD normal gagal.

Wiring yang disediakan di `Schematic/WiringSTM32.zip` mengonfirmasi MCU
`STM32L071RBT6`, PA13 sebagai SWDIO, PA14 sebagai SWCLK, dan header program
enam pin. Archive tersebut tidak digunakan sebagai source firmware.

## Perintah

Jalankan dari folder ini setelah Windows mengenali ST-Link tanpa error driver:

```powershell
& 'C:\Users\MSI\.platformio\penv\Scripts\pio.exe' run
& 'C:\Users\MSI\.platformio\penv\Scripts\pio.exe' run -t upload
```

Jangan menghubungkan board ke PLN, solenoid, atau beban relay selama smoke test.

## Hasil saat ini

Pada 2026-09-02, build CMSIS berhasil: 356 B flash dan 28 B RAM. Setelah driver
ST-Link terpasang, OpenOCD berhasil menghentikan target STM32L0, menulis image,
menjalankan verifikasi dengan hasil `Verified OK`, lalu mereset target. Ini
membuktikan image blink telah ter-flash dan diverifikasi melalui SWD.

Kedipan LED tetap perlu dikonfirmasi secara visual pada board. Program
mengubah PC13 antara LOW (LED menyala) dan HIGH (LED mati) secara berulang tanpa
mengakses relay atau periferal lain.
