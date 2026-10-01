# Protokol bench NFC low-voltage

## Tujuan dan batas scope

Dokumen ini adalah prosedur pengumpulan bukti untuk baseline diagnostik
`smartdispenser_firmware`. Scope hanya LCD, NFC, LED PC13, dan UART. Firmware tidak
mengaktifkan relay, solenoid, atau flowmeter. Protokol ini belum merupakan
persetujuan pengujian dispenser maupun kelistrikan AC.

Jalankan hanya setelah ada otorisasi eksplisit untuk upload dan uji unit.
Sebelum menghubungkan ST-Link, UART, atau alat ukur, pastikan board **tidak
terhubung ke PLN**, tidak ada tegangan pada `LINE`/`NETRAL`, dan beban relay /
solenoid tidak dapat terenergisasi. Bila ada keraguan tentang isolasi catu,
hentikan uji dan minta pemeriksaan personel yang kompeten.

## Image bench

Environment `smartdispenser_nfc_bench` menambahkan satu perubahan diagnostik:
`SMARTDISPENSER_VERBOSE_NFC=1`. Setiap scan mencetak hasil dan `duration_ms`.
Semua output relay masih dipaksa LOW dan tidak ada fungsi aktuasi dalam source.
Image ini bukan artefak release dan tidak termasuk hash release pada audit.

Build tanpa upload:

```powershell
Set-Location D:\IoT\SmartDispenser\firmware\smartdispenser_firmware
pio run -e smartdispenser_nfc_bench
```

Upload hanya dilakukan setelah otorisasi eksplisit pada sesi uji yang sama:

```powershell
pio run -e smartdispenser_nfc_bench -t upload
```

Serial: `115200 8-N-1`, UART `PA9 TX` ke adapter RX dan `GND` bersama, level
logika 3,3 V. Jangan membuka port yang sama pada PuTTY dan alat pencatat lain
secara bersamaan.

Setelah image bench berjalan dan PuTTY ditutup, pencatat berikut membuat log
bertimestamp host. Perintah ini baru membuka COM saat dijalankan:

```powershell
.\scripts\capture_nfc_bench.ps1 -PortName COM6 -DurationSeconds 300 -OutputPath .\out\nfc_hold.log
.\scripts\analyze_nfc_bench_log.ps1 -Path .\out\nfc_hold.log
```

Penganalisis menghitung jumlah, min/p50/p95/p99/max untuk `duration_ms` per
hasil scan serta interval host antar scan. Ia hanya menganalisis file log;
tidak mengakses serial atau perangkat.

## Bukti yang dicatat

Simpan log serial mentah, foto koneksi low-voltage, versi firmware dari baris
`BOOT`, nama profile, serta daftar kartu yang diuji. Catat juga apakah NFC
reader/LCD mendapat daya dari rail yang sama dengan MCU.

| Kasus | Langkah | Bukti minimum | Kriteria saat ini |
| --- | --- | --- | --- |
| Boot | Nyalakan tanpa kartu | `BOOT`, `LCD READY`, `NFC READY` | Tidak ada `NFC FAULT` saat inisialisasi |
| No card | Diamkan tanpa kartu 60 s | Baris `NFC SCAN result=no_card` dan `duration_ms` | Rekam min/median/p95/p99; target angka produksi belum disetujui |
| Hold | Tempel satu kartu 5 menit | UID tetap, count naik maksimal 1 Hz | Tidak ada `CARD REMOVED` atau fault palsu |
| Re-present | Kartu sama: tempel–lepas–tempel 100 kali | `CARD PRESENT`, `CARD REMOVED`, lalu present lagi | Tidak macet; tiga respons no-card valid menandai lepas |
| Switching | Ganti langsung antara sedikitnya dua kartu Type A yang dikenal | `CARD CHANGED` dengan UID benar | UID berikutnya mengganti state pada scan valid berikutnya |
| Unsupported | Uji tiap jenis kartu di luar daftar dukungan | Log mentah | Tidak hang; hasil dicatat sebagai no-card/fault/UID, bukan diasumsikan kompatibel |
| Long run | NFC aktif minimal 72 jam | Log, jumlah fault/recovery, reset cause | Target availability/MTBF harus disetujui sebelum klaim produksi |

Untuk latency, jangan menyimpulkan interval dari satu baris. `duration_ms` adalah
durasi transaksi firmware; interval antar baris serial juga mencakup minimum
jeda polling 200 ms, RF reset, dan kemungkinan blok HAL I2C. Sertakan timestamp
host untuk setiap baris agar p50/p95/p99 dapat dihitung setelah log lengkap.

## Fault dan reset

Fault-injection I2C, brownout, serta scope pada gate relay hanya dilakukan jika
fixture dan prosedur keselamatannya sudah disetujui. Bukti yang diperlukan
sebelum production signoff tetap mencakup reset/brownout tanpa pulse gate,
recovery NFC/I2C, pengukuran pull-up/rise-time, dan validasi watchdog.

Tidak ada hasil bench yang boleh dipakai sebagai bukti posisi kontak relay,
aliran cairan, volume, keamanan AC, atau otorisasi kartu.
