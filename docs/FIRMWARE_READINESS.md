# Audit kesiapan firmware SmartDispenser

Tanggal audit: 2026-09-02

## Kesimpulan

Status saat ini: **belum siap produksi**.

Firmware `smartdispenser_firmware` sudah menjadi baseline diagnostik LCD/NFC yang lebih
bounded, defensif, dan reproducible. Namun belum ada kontrak aplikasi dispenser,
otorisasi, kontrol relay/solenoid, verifikasi flow, watchdog, penyimpanan
transaksi, atau bukti keselamatan/pengujian hardware yang dibutuhkan untuk
menyebut sistem siap produksi.

Audit ini tidak mengaktifkan relay, solenoid, flowmeter, atau beban AC. Perubahan
terakhir hanya dibangun secara statis; belum di-flash atau diuji ulang pada unit.

## Perbaikan yang sudah masuk

| Area | Perubahan | Bukti saat ini |
| --- | --- | --- |
| Transport NFC | Adapter I2C bounded, signed timeout, exact read, validasi frame/checksum, klasifikasi NACK/error | 24 native fake-Wire tests PASS, source review, dan build; HAL/electrical belum tercakup |
| Inisialisasi NFC | `READY` hanya jika address, firmware, SAM, retry, dan RF sukses | Source review dan build |
| Recovery NFC | State `STARTING/READY/FAULT`, retry 1–30 s, host-I2C re-init (termasuk clock-pulse recovery bawaan STM32duino bila SDA LOW), fault setelah timeout berulang, best-effort abort + RF OFF sebelum backoff | Source/framework review dan build; outcome bus-clear, reset hardware NFC, serta fail-off fisik belum tersedia/dibuktikan |
| Discovery NFC | Type A prioritas, lalu Type B, FeliCa 212/424, dan Jewel dengan command/response yang divalidasi ketat; field RF direset sebelum aktivasi | 15 native logic tests PASS, source review, dan build; hardware/jenis kartu aktual belum dibench |
| Presence/count | Source mengimplementasikan policy hardware-free: UID 4/7/8/10 menurut teknologi, direct switch termasuk UID sama lintas teknologi, removal tiga full sweep, re-present, timeout bukan removal, invalid input fail-closed, count global maksimal 1 Hz | 15 native logic tests PASS, compile-time assertions, source review, dan build; belum ada bench PASS |
| Primitive input | Debounce active-low/generic dan raw pulse-activity tracker memiliki baseline boot tanpa edge palsu, reset, timeout, serta clock/counter rollover-safe | 19 native tests PASS dan compile-time target gate; belum terhubung ke pin/runtime dan bukan bukti kompatibilitas listrik atau flow fisik |
| Tampilan/log | Baris LCD selalu ditimpa 16 karakter; UID panjang diberi marker; log berbasis transisi; seluruh reset flag STM32 dicatat saat boot | Source review dan build; reset cause belum divalidasi di unit |
| Relay | PA2/PA3/PA4/PB2 dipaksa LOW paling awal di `setup()` dan tidak dipulse | Source review; pre-main belum terlindungi |
| Reproducibility | dependency NFC dipin, linker script lokal, clock metadata 2,097152 MHz, verifier native-test/clean-build/hash/ELF tanpa upload | Full local verifier PASS memakai GCC portable; CI/host kedua belum ada |
| Stack source | Build menghasilkan metadata `-fstack-usage`; verifier menampilkan frame aplikasi terbesar 320 B dan transport terbesar 312 B untuk kedua profile | PASS sebagai bukti frame statis source saja; belum ada call-chain, ISR, library, atau stack high-water pada unit |
| I2C profile | profile bench internal-pull-up dipisah dari kandidat external-pull-up | Dua profile build sukses |
| Instrumentasi bench NFC | Profile low-voltage terpisah mencetak hasil/durasi setiap scan tanpa mengubah jalur aktuator; capture bertimestamp dan analyzer log tersedia | Build PASS (RAM 2.152 B, Flash 32.784 B); parser/analyzer fixture PASS; uji unit masih diperlukan |

Hasil build terakhir:

| Environment | RAM (metrik PlatformIO) | Flash (metrik PlatformIO) | BIN/LOAD aktual | Status |
| --- | ---: | ---: | ---: | --- |
| `smartdispenser_lcd_arduino` | 2.156 B / 20.480 B | 33.172 B / 131.072 B | 33.408 B | PASS (PLATFORMIO BUILD) |
| `smartdispenser_external_pullups` | 2.156 B / 20.480 B | 33.332 B / 131.072 B | 33.568 B | PASS (PLATFORMIO BUILD) |

Angka 33.172 B dan 33.332 B adalah metrik penggunaan flash yang dilaporkan
PlatformIO; 33.408 B dan 33.568 B adalah footprint BIN/load aktual pada artefak
lokal masing-masing profile. Angka tersebut hanya bukti build, bukan native
runtime PASS, upload/flash, atau validasi live. Pemeriksaan program header ELF
menunjukkan segmen flash `R E` dan tidak menemukan segmen `RWE`.
Satu warning framework tetap ada karena `SystemClock_Config()` sengaja kosong
dan clock reset MSI 2,097152 MHz digunakan; source project sendiri dibangun
dengan warning sebagai error.

Clean rebuild lokal terakhir menghasilkan SHA-256 berikut:

- profile bench:
  `0385178B85A7125E97519EF2E1B7371D9A9D07C873E6E561A3D31CCD46E20ACE`;
- profile external-pull-up candidate:
  `9D161CAACE16603F2D0CFE71B00D15A0409179F20BEFDE67CFCE5ACBDE93814D`.

Artifact belum disimpan sebagai release immutable dan belum direproduksi oleh
CI atau host kedua. Hash ini hanya mengidentifikasi build lokal snapshot audit.

`scripts/verify_firmware.ps1` menjalankan setiap native suite secara terpisah,
melakukan clean-build kedua profile, memastikan object compile-time gate ada,
memeriksa commit PN532 dan versi LCD yang benar-benar terunduh, menjalankan
`pio check`, memeriksa program header ELF, dan menghitung hash di atas; full
gate lokal PASS.
Gate compile-time mencakup `zero-filled length sweep` 0..253 ditambah fixture
valid/malformed terpilih, bentuk Type-A maksimum, presence/switch/removal/
re-present, timeout/fault, invalid input, rate limit, rollover, dan long-idle.
Gate target tambahan memeriksa transisi debounce, timeout pulse activity, serta
rollover timer/counter. Ini bukan corpus seluruh payload bernilai 0..253.
`pio check` lulus tanpa temuan high/medium. Native Unity menghasilkan 58/58 PASS
dengan GCC 16.1.0 C++17: 24 test source transport produksi dengan fake
Wire/clock, 15 test parser/presence/rate, dan 19 test primitive input. Compiler
portable hanya ditambahkan ke PATH proses audit; archive WinLibs yang dipakai
diverifikasi dengan SHA-256
`2FF1522A70ADEB4E9BC450E917501DA72BF48CB583E47530BAA8CD0524FEA0FD`.
Fake-Wire tidak membuktikan HAL, listrik, timing device, atau live hardware.
Verifier tidak melakukan upload/flash atau validasi live.

Pemeriksaan `-fstack-usage` dari build terakhir menemukan 33 frame source per
profile; frame statis terbesar adalah helper scan `main.cpp` 320 B dan
`BoundedPn532I2c::readResponse()` 312 B. Nilai tersebut tidak boleh dijumlahkan
secara naif, karena compiler, jalur pemanggilan, library, interrupt, dan
runtime stack belum dianalisis. Karena itu, pengukuran stack high-water di unit
tetap merupakan syarat P1-03, bukan PASS produksi.

## Blocker produksi

| ID | Blocker | Evidence gate yang wajib | Status |
| --- | --- | --- | --- |
| P0-01 | Gate relay tanpa pull-down dan relay latching tanpa feedback | Pull-down terpasang/terukur; posisi valve/kontak dapat dibuktikan; uji reset/brownout | OPEN |
| P0-02 | PA0 FLOW dapat terkena 5 V bila sensor push-pull | Datasheet/ukur output open-collector atau level shifter tervalidasi | OPEN |
| P0-03 | Keselamatan domain AC, fuse, creepage, clearance, rating, isolasi belum terbukti | Design review, BOM, layout/Gerber, laporan electrical safety | OPEN |
| P0-04 | Kontrak dispensing belum didefinisikan | State, volume target, timeout, abort, retry, power-loss, dan acceptance test disetujui | OPEN |
| P0-05 | UID belum merupakan otorisasi aman | Model credential/allowlist/backend, anti-replay, audit log, default-deny | OPEN |
| P1-01 | Pull-up/level/rise-time shared I2C belum diukur; bus-clear framework tidak menjamin pulih dari slave/SCL yang wedge | R efektif, VHIGH, rise-time, capacitance, serta fault-injection satu slave menahan SDA/SCL | OPEN |
| P1-02 | NFC tidak memiliki reset/IRQ ke MCU; best-effort RF OFF tidak menjamin recovery/fail-off saat bus atau chip wedge | Keputusan hardware reset/load-switch dan field-power policy, atau prosedur power-cycle tervalidasi; fault-injection lulus | OPEN |
| P1-03 | Tidak ada watchdog/health gate; reset cause baru dicatat tetapi belum dibuktikan live | Analisis worst-case latency, IWDG policy, validasi reset-cause, soak dan recovery test | OPEN |
| P1-04 | Belum ada persistent transaction model | Atomic record, counter policy, wear/endurance, recovery setelah power loss | OPEN |
| P1-05 | Build belum berada pada commit/release immutable dan belum ada CI | Commit/tag, lock/artifact hash, clean build CI, retained binary/map | OPEN |
| P1-06 | Kontrak radio/UART2 di source tidak konsisten | BOM/marking radio dan koreksi net/header source | OPEN |
| P1-07 | Deadline software transport masih dapat overshoot satu blocking call HAL I2C | Ukur worst-case latency/stall pada fault injection dan buktikan memenuhi watchdog/loop budget | OPEN |

## State machine produksi yang diusulkan

State berikut adalah proposal, bukan implementasi:

```text
BOOT_SAFE -> SELF_TEST -> IDLE -> CARD_DETECTED -> AUTHORIZING
               |                                  |
               v                                  v
          FAULT_LOCKOUT <- fault ----------- AUTH_DENIED
                                                  |
                                                  v
                  COMPLETE <- VERIFY_CLOSED <- DISPENSING
                                      ^              |
                                      +---- ABORT ----+
```

Prinsip wajib:

- output aktuator tetap safe pada boot, reset, brownout, exception, dan timeout;
- SET/RST satu relay tidak pernah aktif bersamaan dan pulse dibatasi hardware
  serta software;
- UID detection dipisahkan dari authorization;
- `DISPENSING` hanya boleh dimulai setelah seluruh precondition valid;
- flow harus membuktikan aliran dan berhenti; tidak ada flow atau flow terus
  setelah close harus menuju fault lockout;
- transaksi hanya dinyatakan selesai setelah kondisi akhir fisik tervalidasi;
- setiap reboot menyimpan dan melaporkan reset cause serta memulihkan secara
  default-deny.

## Matriks verifikasi berikutnya

| Test | Acceptance | Bukti | Status |
| --- | --- | --- | --- |
| Clean build dua profile | Exit 0, dependency commit tetap, hash artifact tersimpan | Full verifier lokal PASS dan dua hash dicatat; CI/retention belum ada | PARTIAL |
| Compile-time parser/gate | `Zero-filled length sweep` 0..253 ditambah fixture valid/malformed terpilih; strict no-card, UID/ATS maksimum, presence/switch/removal/timeout/fault, invalid input, rate/rollover/long-idle | Assertions dikompilasi otomatis pada dua profile; bukan native runtime test | PASS (COMPILE) |
| Runtime host logic | Type A/B, FeliCa, Jewel, parser/presence/rate lulus di native C++17 | 15/15 PASS dengan GCC 16.1.0 | PASS (HOST) |
| Runtime fake-Wire NFC | Jalur frame, ACK/NACK, short read, error, timeout, capacity, dan rollover transport lulus dengan fake clock/Wire | 24/24 PASS terhadap `bounded_pn532_i2c.cpp` produksi | PASS (HOST LOGIC) |
| Runtime input primitives | Bounce, boot-held, active-high/low, reset, timeout/restart, dan rollover clock/counter | 19/19 PASS di native C++17; source belum diintegrasikan ke `main.cpp` | PASS (HOST LOGIC) |
| Reset cause | Seluruh flag aktif tercetak dan kemudian dibersihkan | Source/build tersedia; UART per jenis reset | NOT RUN |
| Boot low-voltage | LCD/NFC init; empat gate relay tetap LOW pada scope | UART + scope capture | NOT RUN |
| NFC latency | Distribusi p50/p95/p99 untuk no-card dan card, tanpa stall > deadline budget | Log bertimestamp >=1.000 scan | NOT RUN |
| Card hold | Count naik 1 Hz tanpa false removal | Video/log 5 menit | NOT RUN |
| Remove/re-present | Stop setelah <=3 miss; kartu sama dapat aktif lagi | Log 100 siklus | NOT RUN |
| UID switching | Minimal 5 kartu ISO14443A bergantian, UID benar setiap siklus | Log 500 switch | NOT RUN |
| Unsupported card | Ditolak sebagai unsupported/no-card tanpa lockup | Matrix jenis kartu | NOT RUN |
| I2C fault injection | LCD/NFC cabut, SDA/SCL stuck, NACK/short frame; sistem fault dan pulih bounded | Scope + log | NOT RUN |
| Power cycle/brownout | 1.000 siklus tanpa pulse gate dan tanpa state transaksi palsu | Fixture log + scope | NOT RUN |
| Soak | 72 jam tanpa hang, leak, counter corruption, atau uncontrolled output | Retained log | NOT RUN |
| Watchdog | Stall yang diinjeksi menghasilkan reset cause dan safe recovery | Fault-injection report | NOT RUN |
| Buttons/flow/actuator | Primitive debounce/pulse sudah teruji host; arti tombol, input/ISR flow, calibration, interlock, aktuasi, dan fault process belum ada | Requirements + bench report | PURE LOGIC ONLY |
| AC/load safety | Hanya setelah gate desain dan prosedur keselamatan disetujui | Formal test report | BLOCKED BY DESIGN |

## Keputusan yang masih dibutuhkan

1. Apakah kartu yang ditahan berarti satu transaksi atau continuous dispense?
2. Apa daftar jenis kartu yang wajib didukung: Type A saja, MIFARE, FeliCa,
   e-money tertentu, atau credential aplikasi khusus?
3. Apakah otorisasi lokal, online, atau hybrid; dan apa perilaku saat jaringan
   tidak tersedia?
4. Volume target, toleransi flow, timeout start/stop, dan respons terhadap sensor
   stuck seperti apa?
5. Posisi fisik default valve/relay saat power-up dan bagaimana pembuktiannya?
6. Data apa yang harus persisten dan berapa endurance/retention targetnya?
7. Target respons, availability, MTBF, suhu, kelembapan, dan lifecycle produk?

Tanpa jawaban dan evidence gate tersebut, pekerjaan yang aman adalah terus
mematangkan firmware bench dan testability, bukan mengaktifkan dispenser.
