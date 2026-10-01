# Uji LCD I2C 16x2

Firmware bench-test STM32L071RBT6 ini menulis dua baris berikut ke LCD:

```text
SmartDispenser
LCD I2C OK
```

## Wiring yang dipakai

Source EasyEDA `Schematic/WiringDispenser.zip` menunjukkan koneksi `J1`
`1602LCD` sebagai berikut:

| LCD | STM32L071MOD |
| --- | --- |
| GND | GND |
| VCC | VCC 3,3 V |
| SDA | PB9 / I2C1_SDA |
| SCL | PB8 / I2C1_SCL |

PN532 juga berada pada bus ini. Scan bench pada 2026-09-02 menemukan ACK pada
`0x26`, sehingga firmware ini memakai alamat tersebut. Uji LCD memakai I2C
software pada PB8/PB9, sama seperti scanner yang menghasilkan ACK. ACK membuktikan ada
perangkat I2C di alamat itu; fungsi tampilan tetap perlu dikonfirmasi secara
visual.

## Batas uji

Pemetaan bit backpack LCD tidak tercantum dalam source skematik. Firmware
mengasumsikan backpack PCF8574 umum: P0=RS, P2=EN,
P3=backlight, P4..P7=D4..D7. Bila LCD tidak menampilkan teks tetapi LED PC13
berkedip pola dua kali, laporkan hasilnya atau foto backpack LCD agar alamat
dan mapping dapat disesuaikan.

Firmware ini tidak mengakses relay, solenoid, flowmeter, atau jalur PLN.
Gunakan hanya dengan board pada catu tegangan rendah yang aman selama uji SWD.
