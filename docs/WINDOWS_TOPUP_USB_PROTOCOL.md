# Kontrak USB virtual-COM untuk aplikasi top-up Windows

## Status, batas, dan dasar bukti

**Status: usulan kontrak `SDR-USB/1`; belum diimplementasikan maupun diuji pada
firmware, USB, kartu, atau aplikasi Windows.** Dokumen ini mendefinisikan batas
antarmuka untuk alat B yang bertindak sebagai *NFC reader/secure adapter* dan
aplikasi Windows yang menjalankan alur operator. Ini bukan izin upload, reset,
penyambungan USB ke board bertegangan PLN, atau pengujian kartu nyata.

Fakta yang diperiksa dari repositori:

- `README.md` dan `HARDWARE_BASELINE.md` menyatakan baseline masih belum siap
  produksi; build/source bukan bukti perangkat atau kartu fisik bekerja.
- `docs/DESIGN_NFC_PERSO_DISPENSER.md` menetapkan saldo maksimum 100 L,
  transaksi harus idempoten dengan commit dan readback, dan key/secret tidak
  boleh muncul pada kartu, log, atau repositori.
- `docs/IMPLEMENTATION_STATUS_AB.md` menyatakan adapter Classic/runtime adalah
  kandidat software; integrasi serta bukti perangkat fisik masih terpisah.
- `firmware/smartdispenser_firmware/src/onefile/Topup.cpp` adalah implementasi
  lama MCU-top-up dengan `Uart logger` pada 115200, bukan bridge USB ini. Ia
  berisi key contoh dan format wallet lama, sehingga **bukan** sumber API,
  keamanan, atau format yang boleh diekspos ke PC.

Semua bagian setelah ini adalah **usulan desain** sampai implementasi, review,
dan bench low-voltage membuktikannya. Nama `secured adapter` berarti image/perangkat
yang mampu mengautentikasi kartu dan menjaga material rahasia di sisi adapter;
status tersebut belum dibuktikan oleh artefak ini.

## Peran dan batas kewenangan

```text
Aplikasi Windows (UI, operator, audit) -- USB virtual COM -- Reader/secure adapter -- PN532 -- kartu
```

- PC mengelola sesi operator, meminta operasi bisnis yang terbatas, dan menyimpan
  jurnal audit. PC tidak mengirim command NFC mentah.
- Reader mendeteksi/menjaga kehadiran kartu dan, hanya ketika `secured adapter`
  aktif, menjalankan operasi kartu tingkat tinggi, commit, lalu readback.
- Tidak ada command shell, firmware update, reset, GPIO, relay/solenoid, flow,
  PN532 raw frame, APDU bebas, autentikasi blok/sector, atau read/write block.
  Reader ini tidak boleh mengendalikan aktuator dispenser.
- Key, hasil KDF, nonce internal, UID mentah, dump kartu, trailer Classic, APDU,
  dan debug PN532 tidak boleh masuk frame, EXE, UI, atau log. `card_token` adalah
  token sesi opaque yang dibuat adapter dan habis saat kartu/sesi berakhir; ia
  bukan UID maupun pengganti autentikasi.

## Transport dan framing

Transport adalah satu port USB CDC ACM/virtual COM dengan satu koneksi aplikasi
aktif. Baud-rate serial hanyalah parameter driver; framing ini tidak bergantung
padanya. Tidak gunakan line-delimited JSON.

Setiap frame adalah:

```text
+---------------------+------------------------------+
| uint16 big-endian N | N byte JSON UTF-8             |
+---------------------+------------------------------+
```

- `1 <= N <= 4096`; zero length, length lebih besar, UTF-8/JSON invalid, JSON
  bukan object, field wajib hilang, tipe tidak cocok, atau field tidak dikenal
  ditolak dengan `protocol_error` bila header masih dapat dibaca; selain itu
  koneksi dibuang dan parser disinkronkan dengan membuka ulang port.
- Parser bersifat streaming: harus menangani fragmentasi dan beberapa frame dalam
  satu read tanpa alokasi melebihi batas. Tidak ada kompresi, nested payload
  arbitrer, binary base64, atau ekstensi diam-diam.
- Frame hanya diizinkan setelah `hello`/`hello_ack` versi cocok. Untuk v1,
  implementasi menolak versi mayor selain `1`, dan menolak `minor` lebih tinggi
  daripada yang didukung. Negosiasi versi baru memerlukan perubahan dokumen.

Envelope semua pesan:

```json
{"v":{"major":1,"minor":0},"type":"...","request_id":"UUID", "body":{}}
```

`request_id` wajib untuk pesan yang meminta/menjawab operasi dan harus UUID
RFC 4122 canonical lowercase. Event asynchronous memakai `event_id` UUID dan
`reader_session`; tidak memakai `request_id`. PC membuat request ID secara
kriptografis acak dan **tidak membuat ID baru** ketika hasil operasi belum pasti.

## Handshake, sesi, dan capabilities

1. Setelah port terbuka, PC mengirim `hello` dalam 2 detik:
   `{"type":"hello",...,"body":{"client_instance_id":"UUID","versions":[{"major":1,"minor":0}]}}`.
2. Reader mengirim `hello_ack` berisi satu versi terpilih, `reader_id` opaque,
   `boot_id` UUID, `max_frame_bytes`, `capabilities`, dan `secured_adapter`.
   Kegagalan handshake menutup sesi.
3. PC hanya mengizinkan UI mutasi apabila `secured_adapter:true` dan capability
   `wallet_mutation_v1` hadir. Jika tidak, PC boleh menampilkan status perangkat
   tetapi harus menolak top-up sebelum mengirim request. Reader juga wajib
   menjawab `adapter_not_secured`; enforcement ganda ini mencegah UI lama
   membypass gate.
4. Reader menerbitkan `card_present` untuk satu kartu stabil dan membuat
   `reader_session` UUID + `card_token`. Perubahan, lepas kartu, reboot, timeout,
   atau port disconnect mengakhiri sesi. `card_removed` memuat alasan, token
   tidak berlaku lagi, dan semua operasi belum final menjadi uncertain.
5. PC tidak boleh mengasumsikan sesi tetap hidup setelah reconnect. `boot_id`
   berubah berarti seluruh cache dan ACK lokal harus direkonsiliasi melalui
   `operation_query` setelah kartu yang sama kembali hadir.

Capabilities v1 yang didefinisikan hanya `card_presence_v1`, `wallet_read_v1`,
`wallet_mutation_v1`, dan `operation_query_v1`. Unknown capability tidak memberi
hak baru. `wallet_mutation_v1` tidak boleh diiklankan sebelum adapter secured
benar-benar tersedia dan direview.

## Pesan domain yang diperbolehkan

| Arah | `type` | Body minimum | Aturan hasil |
|---|---|---|---|
| PC → reader | `hello` | `client_instance_id`, `versions` | hanya sebelum sesi |
| reader → PC | `hello_ack` | versi, `reader_id`, `boot_id`, capabilities, `secured_adapter` | menegaskan gate |
| reader → PC | `card_present` | `event_id`, `reader_session`, `card_token` | token opaque; tanpa UID |
| reader → PC | `card_removed` | `event_id`, `reader_session`, `reason` | membatalkan token/sesi |
| PC → reader | `wallet_read` | `reader_session`, `card_token` | balasan `wallet_state` atau error |
| reader → PC | `wallet_state` | `reader_session`, token, `available_liter`, `frozen_liter`, `operator_active`, `revision` | hanya data teredaksi yang diperlukan UI |
| PC → reader | `topup_request` | token, `amount_liter`, `expected_revision`, `operator_authorization` | high-level; tidak ada raw write |
| PC → reader | `set_operator_active_request` | token, `active`, `expected_revision`, `operator_authorization` | high-level; mutasi terbatas |
| PC → reader | `operation_query` | `reader_session`, `card_token`, `operation_id` | rekonsiliasi hasil ambigu |
| reader → PC | `operation_result` | request ID, operation ID, `outcome`, `wallet_state` atau error | hasil final hanya sesudah readback |
| reader → PC | `protocol_error` / `device_error` | kode stabil, retryable | tanpa data sensitif |

`amount_liter` adalah integer dan untuk top-up v1 hanya `5`, `10`, atau `20`;
reader juga memeriksa total kuota maksimum 100 L dan `expected_revision`. Nilai
lain, overflow, saldo/frozen state yang tidak dapat dibuktikan, izin operator
tidak ada/kedaluwarsa, atau revision berbeda harus ditolak tanpa write.
`operator_authorization` adalah handle opaque terbatas waktu, terikat pada sesi
operator dan kartu. Format, issuer, login/role, penyimpanan credential, dan
validasi online/offline belum ditentukan; sampai mekanisme itu ada, adapter wajib
menolak mutasi dengan `authorization_unavailable`.

Tidak ada command umum `write`, `authenticate`, `transceive`, `raw`, `apdu`,
`block`, atau parameter key. Masa depan yang membutuhkan domain baru harus
mengalokasikan `type` eksplisit, skema bounded, state machine, otorisasi, dan
uji negatif baru—bukan menambahkan escape hatch.

## Idempotensi, readback, timeout, dan ACK hilang

`topup_request` serta `set_operator_active_request` adalah operasi mutasi. Reader
mencatat `request_id`, `operation_id`, binding `reader_session/card_token`, intent,
dan status durable sebelum mutasi. Cache idempotensi harus bertahan minimal sampai
operasi final direkonsiliasi atau kebijakan jurnal yang aman menutupnya; cache RAM
saja tidak cukup melintasi reboot. Request ID yang sama dengan payload/binding
identik harus mengembalikan `operation_result` tersimpan; ID sama dengan payload
berbeda menjawab `idempotency_conflict` tanpa akses kartu.

Urutan usulan mutasi:

1. Validasi frame, sesi, presence, adapter secured, otorisasi, nominal, dan
   `expected_revision`.
2. Baca dan autentikasi state kartu melalui adapter; simpan intent durable.
3. Jalankan satu operasi dompet tingkat tinggi, commit sesuai format kartu, lalu
   baca ulang state terautentikasi dan pastikan `operation_id`/revisi/hasil cocok.
4. Baru kembalikan `operation_result` dengan `outcome:"applied"` dan state final.

Timeout transport PC adalah 8 detik untuk read, 15 detik untuk mutasi; reader
boleh mengirim `device_error {"code":"in_progress","retryable":true}` sebelum
batas itu. Timeout lokal PC, putus USB, atau tidak diterimanya `operation_result`
**bukan** bukti gagal dan tidak boleh memicu top-up baru. Saat kartu kembali,
PC mengirim ulang request ID sama atau `operation_query` dengan `operation_id`.
Jika pembuktian commit/readback tidak tersedia, hasilnya `outcome:"uncertain"`;
UI menandai `PERLU PEMERIKSAAN`, tidak mengulang kredit otomatis.

## Kehilangan kartu, state machine, dan recovery

```text
NO_CARD -> CARD_PRESENT -> READY -> MUTATING -> READBACK -> FINAL
                       \-> CARD_REMOVED -> UNCERTAIN / RECONCILE
```

- Kehilangan kartu sebelum intent: jawab `card_removed`, tidak ada mutasi.
- Kehilangan kartu sesudah intent atau selama write/readback: reader mengakhiri
  sesi, tidak menganggap ACK sebelumnya sukses, dan menandai `uncertain`.
  Ia tidak mencoba write lagi pada token/sesi lama.
- Kartu yang ditempel lagi selalu mendapat `reader_session`/`card_token` baru.
  Adapter hanya mengaitkan operasi lama setelah autentikasi/readback membuktikan
  kartu dan operasi terkait; kesamaan UID atau token lama tidak cukup.
- Reboot reader, reconnect COM, atau kehilangan ACK mengikuti jalur yang sama:
  query/retry ID lama + readback, bukan operasi kredit baru. PC menyimpan audit
  lokal append-only dengan request/operation ID, waktu, outcome, dan kode error
  teredaksi; log bukan sumber saldo kanonis.

## Model ancaman ringkas dan kontrol

| Ancaman | Kontrol kontrak | Batas yang tersisa |
|---|---|---|
| PC/UI jahat mengirim write mentah atau key | allowlist tipe pesan; tidak ada raw command/key; adapter secured | malware PC masih dapat meminta operasi high-level bila otorisasi lemah |
| Retry/ACK hilang menggandakan top-up | request ID durable, intent, operation query, commit + readback | perlu pembuktian persistence di kartu fisik |
| Kartu dicabut/ditukar | token sesi opaque, binding session/kartu, card_removed, readback | reader/card physical presence dan anti-relay belum dibuktikan |
| Frame rusak/DoS serial | length bound, parser streaming, timeout, satu client | USB fisik dapat tetap dicabut/diblokir |
| Clone/rollback Classic | revision, jurnal, authenticated readback, penolakan conflict | desain repo sendiri menyatakan Classic tidak setara anti-clone/anti-rollback DESFire |
| Kebocoran audit/log | token opaque, redaksi UID/key/raw frame, ACL Windows perlu desain | ACL, signing EXE, dan secure storage belum ditentukan |

Transport USB ini bukan kanal aman kriptografis dengan sendirinya. Jika host tidak
tepercaya, perlu desain identitas perangkat, otentikasi host, perlindungan replay,
dan key storage yang terpisah sebelum mengklaimnya aman untuk produksi.

## Uji penerimaan, negatif, dan fuzz

Implementasi baru tidak diterima hanya karena UI atau port COM terbuka. Minimal
uji host/simulator dan bench low-voltage perlu membuktikan:

1. Fragmentasi pada setiap batas byte, dua/lebih frame satu read, JSON UTF-8
   invalid, `N=0`, `N=4097`, declared-length mismatch, object terlalu dalam,
   field unknown/duplikat, versi/tipo salah, UUID malformed, dan overflow angka
   selalu ditolak bounded tanpa crash/leak.
2. `hello` ganda, command sebelum handshake, unknown capability/type, dua client,
   reconnect/boot ID berubah, dan token dari sesi lain ditolak.
3. 95+5 diterima; 96+5, nominal negatif/pecahan/di luar allowlist, stale revision,
   authorization kosong/kedaluwarsa, dan adapter tidak secured ditolak tanpa write.
4. Pengiriman `topup_request` sama berkali-kali (termasuk setelah reader reboot,
   response hilang, dan PC reconnect) memberi satu hasil kanonis tanpa kredit
   ganda. ID sama dengan body berbeda menghasilkan `idempotency_conflict`.
5. Cabut kartu pada sebelum intent, sesudah intent, tiap batas write, saat commit,
   dan saat readback; cabut USB sebelum/selepas result; kartu berbeda ditempel.
   Tidak boleh ada operasi baru otomatis, raw data, atau klaim sukses tanpa
   rekonsiliasi/readback.
6. Fuzz stateful minimal 10.000 urutan bounded berisi handshake/presence/remove/
   request/retry/reconnect, dengan assertion: tidak ada mutasi tanpa gate,
   maksimum 100 L, request ID tidak menggandakan operasi, dan parser tetap
   bounded. Hasil simulator tidak menggantikan kartu/PN532/USB fisik.

Gate release yang masih terbuka: implementasi adapter secured, format dan
durabilitas jurnal, definisi otorisasi operator, Windows secure storage/ACL,
auth host-device, test vector, signing/installer EXE, dan uji bench low-voltage
dengan kartu target. Sampai seluruh gate tersebut ditutup dengan bukti terpisah,
aplikasi hanya boleh diposisikan sebagai kandidat/simulator—bukan alat top-up
produksi.
