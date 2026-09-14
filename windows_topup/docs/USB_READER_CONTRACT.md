# Kontrak bridge USB Topup v1

Status: **diimplementasikan** oleh
`firmware/smartdispenser_firmware/src/onefile/Topup.cpp` dan
`windows_topup/topup_core.py`.

Board memakai USB Serial 115200 baud. Aplikasi membuka COM dengan DTR dan RTS
LOW, lalu memakai command compact untuk operasi tanpa parameter serta baris
`REQ` untuk mutasi bernilai. Respons selalu satu baris:

```text
RES <id> OK <key=value ...>
RES <id> ERR <reason>
```

Perintah domain yang tersedia: handshake, lock/unlock sesi master, pendaftaran
master 10 detik, Test Card, pembacaan Wallet, penyesuaian saldo, status aktif,
jadwal, dan pelepasan saldo reserved. Desktop tidak dapat mengirim APDU,
perintah PN532 mentah, UID, key, atau isi blok kartu.

## Test Card yang mengikuti Perso

`TEST_START`, `TEST_STATUS`, dan `TEST_STOP` mengaktifkan jalur presence-only
khusus di firmware. Saat aktif:

- polling PN532 hanya dimiliki loop firmware;
- kartu master maupun pelanggan diterima;
- Wallet Data tidak dibaca atau ditulis;
- tap master tidak membuka sesi operator;
- hasil dibatasi pada status hadir/tidak hadir dan jumlah deteksi;
- kehilangan satu polling ditoleransi selama 500 ms;
- aplikasi mencoba handshake awal maksimal empat kali jika ACK UART hilang.

## Batas keamanan

Mutasi ditolak bila sesi master belum aktif. Firmware melakukan autentikasi,
penulisan, dan read-back Wallet di Board; desktop hanya menerima hasil domain.
UID, Key A/Key B, MAC secret, APDU, dan blok mentah tidak boleh muncul pada
serial, UI, EXE, atau log.

Build source bukan bukti bahwa firmware sudah di-upload atau perilaku kartu
fisik sudah teruji.
