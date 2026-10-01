# Hardware Baseline

Baseline ini disusun dari skematik PDF, foto, dan source EasyEDA yang tersedia.
Dokumen ini bukan persetujuan desain, laporan uji, atau bukti kesiapan produksi.

## Sumber

| Sumber | Identitas yang terlihat | Cakupan |
| --- | --- | --- |
| `Schematic/BoardDispenser.pdf` | Rev. 1.0, 2026-08-21, `Drawn By: mamanbudiman` | Board utama dispenser |
| `Schematic/STM32.pdf` | Rev. 1.0, 2020-10-25, `Company: Deviota`, `Drawn By: MB` | Modul MCU dan radio |
| `Schematic/WiringSTM32.zip` | Archive EasyEDA dengan schematic dan PCB source modul radio | Konfirmasi source untuk STM32L071RBT6 dan header SWD |
| `Schematic/WiringDispenser.zip` | Archive EasyEDA dengan schematic dan PCB source board dispenser | Konfirmasi source untuk pin LCD I2C |
| `Photo/*.jpeg` | Foto tanpa data uji atau nameplate yang lengkap | Kondisi fisik sebagian komponen/assembly |

## Fakta dari skematik

### Board dispenser

- U1 diberi label `STM32L071MOD`.
- U2 diberi label `pn532` dan terhubung melalui `SCL`, `SDA`, `VCC`, dan
  `GND`.
- J1 adalah koneksi `1602LCD` dengan `GND`, `VCC`, `SDA`, dan `SCL`.
- Source EasyEDA `WiringDispenser.zip` mengonfirmasi J1 pin 3 (`SDA`) menuju
  `SDA_PB9` dan pin 4 (`SCL`) menuju `SCL_PB8` pada U1. Alamat I2C backpack
  LCD serta mapping expander tidak dicantumkan dalam source tersebut.
- Salah satu uji bench pada 2026-09-02 menerima ACK I2C di `0x26`; identitas
  perangkat pada ACK tersebut tidak dibuktikan. Pada pengujian berikutnya,
  firmware library yang menetapkan LCD `0x27` dilaporkan pengguna berhasil
  menampilkan teks. Hasil ini adalah observasi bench sebelumnya, bukan
  pengukuran ulang pada revisi firmware audit terakhir. Posisi strap backpack
  tetap perlu dicatat sebagai data assembly.
- P4 adalah koneksi `FLOW` dengan +5 V, GND, dan sinyal ke PA0. Sinyal memiliki
  pull-up 10 kohm ke VCC dan kapasitor 100 nF ke GND.
- Tiga input tombol menggunakan PA11, PB4, dan PB3, masing-masing dengan
  pull-up 10 kohm dan kapasitor 100 nF.
- Dua relay latching diberi label `HFE20-1/5-1HST-L2`. Jalur SET/RST digerakkan
  oleh 2N7002: PA2/PA3 untuk kanal 1 dan PA4/PB2 untuk kanal 2.
- Pada simbol relay, COM terhubung ke `LINE`, NO menuju `NET_OUT1`/`NET_OUT2`,
  NC tidak digunakan, dan `NETRAL` diteruskan langsung ke konektor keluaran.
- Bagian catu menampilkan input AC, modul AC-ke-DC menuju +5 V, lalu
  `AMS1117-3.3` menuju VCC 3,3 V.
- Terdapat konflik dokumentasi pada U5: pin simbol bernama `Line` menerima net
  `NETRAL`, sedangkan pin bernama `Net` menerima net `LINE`. Hal ini harus
  dikoreksi atau dijelaskan pada source desain walaupun input modul AC tertentu
  mungkin tidak berpolaritas.
- J2 diberi label `UART`.

### Modul MCU/radio

- U1 diberi label `STM32L071RBT6`.
- Tersedia sinyal SWD (`SWDIO`, `SWCLK`, `NRST`) pada header program.
- Source EasyEDA di `WiringSTM32.zip` menegaskan SWDIO pada PA13, SWCLK pada
  PA14, serta koneksi VCC/GND/NRST pada header program.
- Source modul tidak menunjukkan kristal HSE/LSE. Variant Arduino yang dipakai
  membiarkan clock reset MSI 2,097152 MHz; metadata board Arduino terbaru sudah
  diselaraskan ke nilai tersebut. Perubahan clock mendatang wajib diikuti
  perhitungan ulang timing I2C dan verifikasi UART/timer.
- Header memaparkan UART, I2C, ADC, dan GPIO; radio menggunakan jalur SPI1.
- U2 diberi label `RFM69CW` dengan DIO0-DIO5, SPI, reset, dan koneksi RF.
- Terdapat ketidakkonsistenan nama: komponen diberi label `RFM69CW`, tetapi
  net reset diberi nama `RFM95_RST`. Jenis radio final harus dikonfirmasi dari
  BOM, marking hardware, dan firmware.
- Source PCB menghubungkan pin simbol RFM69 `DIO5` ke PC4 melalui net bernama
  `DIO4`; net terpisah `DIO5` pada PA8 hanya memiliki endpoint MCU. Firmware
  radio harus mengikuti endpoint fisik yang telah diverifikasi, bukan nama net.
- Label UART2 pada J3 juga tidak cocok dengan alternate function: `ADC2` menuju
  PA2/USART2_TX, `UART2_TX` menuju PA3/USART2_RX, dan `UART2_RX` menuju
  PA4/USART2_CK. UART diagnostik USART1 pada J2 (PA9/PA10) konsisten.

## Observasi dari foto

- Foto menunjukkan modul PN532 terpasang pada sisi board yang memiliki tombol.
- Foto board utama menunjukkan modul STM32 terpasang, tetapi relay, terminal
  block, dan modul AC-ke-DC tampak belum terpopulasi. Foto tersebut bukan bukti
  bahwa assembly pernah diberi tegangan PLN atau berfungsi.
- Foto menandai regulator SOT-223 yang terpasang sebagai `U5`, sedangkan
  skematik menamai regulator `AMS1117-3.3` sebagai U7 dan U5 sebagai modul
  AC-ke-DC. Ini menunjukkan bahwa reference designator atau revisi foto dan
  skematik belum selaras.
- Foto `SolenoidFlowmeter.jpeg` menunjukkan katup solenoid dan sensor aliran
  tiga kabel; rating, pinout, dan karakteristik pulsanya tidak terbaca.
- Foto `ExamplePowerSupply.jpeg` hanya menunjukkan contoh assembly catu daya;
  part number, rating input/output, kelas isolasi, dan kesesuaiannya dengan
  skematik belum terbukti.
- Sebuah slot isolasi terlihat pada foto PCB, tetapi satu fitur mekanis tidak
  membuktikan creepage, clearance, ataupun isolasi keseluruhan assembly.

Observasi foto tidak membuktikan konektivitas net, rating, fungsi, ataupun hasil
pengujian.

## Gate keselamatan dan desain

- Source PCB EasyEDA tersedia di kedua archive, tetapi belum ada BOM, Gerber,
  stack-up, laporan DRC, kecocokan revisi terhadap unit fisik, data
  creepage/clearance, atau laporan isolasi. Keselamatan terhadap PLN belum
  dapat dinilai tuntas.
- Fuse/proteksi arus lebih tidak dapat diidentifikasi dengan jelas dari
  skematik yang tersedia. Komponen proteksi, rating, dan penempatannya harus
  dikonfirmasi sebelum energisasi.
- R10 berlabel `10D471K` terlihat paralel terhadap `LINE`-`NETRAL`, tetapi tidak
  menggantikan kebutuhan proteksi arus lebih. Fuse/thermal fuse, pembatas arus,
  filter EMI, protective earth, dan proteksi per-beban tidak terlihat pada
  skematik yang tersedia.
- Rating relay, solenoid, flow sensor, konektor, jalur PCB, catu AC-ke-DC, dan
  proteksi surge belum dibuktikan terhadap beban aktual.
- Gate MOSFET SET/RST relay tidak menunjukkan pull-down. Karena relay bersifat
  latching, keadaan kontak dapat bertahan melewati power-cycle; firmware harus
  mencegah SET dan RST aktif bersamaan serta tidak boleh mengasumsikan state
  fisik hanya dari state RAM.
- Firmware Arduino diagnostik terbaru memaksa PA2/PA3/PA4/PB2 LOW paling awal
  di `setup()` dan tidak mem-pulse relay. Ini hanya mitigasi setelah aplikasi
  mulai; reset, bootloader, dan pre-main tetap tidak terlindungi tanpa pull-down
  hardware, dan posisi kontak tetap tidak diketahui tanpa feedback.
- Snubber/TVS pada sisi kontak relay tidak terlihat. Rating kontak dan proteksi
  beban induktif harus dibuktikan untuk solenoid aktual.
- Input flow diberi +5 V, sedangkan PA0 dipull-up ke VCC 3,3 V. Koneksi ini
  hanya dapat dianggap kompatibel setelah output sensor terbukti open-collector
  atau open-drain, atau tersedia level shifting yang sesuai. Output push-pull
  5 V dapat melampaui rating input MCU.
- Pull-up I2C untuk PN532/LCD tidak terlihat pada board schematic. Keberadaan
  pull-up pada modul, nilai efektif paralel, mode antarmuka PN532, tegangan
  backpack LCD, dan kompatibilitas level logika harus diperiksa pada assembly
  aktual.
- Jangan melakukan uji PLN bersamaan dengan debugger/USB/alat ukur ber-ground
  sebelum domain isolasi dan prosedur uji diverifikasi.

## Hal yang belum terbukti

- Varian final board dan revisi PCB yang cocok dengan skematik.
- Part number MCU yang benar pada unit fisik dan pin map firmware final.
- Jenis radio final (`RFM69CW` atau varian lain), frekuensi, antena, dan domain
  regulasinya.
- Tegangan/rating solenoid, karakteristik flow sensor, arah aliran, dan faktor
  kalibrasi.
- Kondisi NO/NC solenoid, batas tekanan, kompatibilitas fluida, pulse-per-liter,
  serta IP rating aktuator/sensor.
- Jenis dan rating catu daya, fuse, MOV/surge protection, grounding, isolasi,
  creepage, dan clearance.
- Logika aplikasi, state machine dispensing, otorisasi RFID, penyimpanan data,
  komunikasi eksternal, dan perilaku saat fault/power loss.
- Revisi firmware audit terakhir dapat dibangun pada dua profile, tetapi belum
  di-flash; runtime, kalibrasi, fault recovery, endurance, dan uji beban/mains
  untuk revisi tersebut belum terbukti.

## Input minimum sebelum scaffold firmware

1. Source atau project MCU yang pernah digunakan, bila ada.
2. Pilihan toolchain dan target build yang diinginkan.
3. BOM serta source skematik/PCB untuk revisi board aktual.
4. Pin map yang telah diverifikasi terhadap PCB dan unit fisik.
5. Datasheet/rating PN532, radio, relay, catu, solenoid, dan flow sensor aktual.
6. Kontrak perilaku dispenser, kondisi fail-safe, serta acceptance test.
