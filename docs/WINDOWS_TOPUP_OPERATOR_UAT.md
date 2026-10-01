# Alur operator dan UAT aplikasi Windows Top-up

**Status:** draft operasional untuk `windows_topup`, tervalidasi hanya pada mode simulasi. Dokumen ini bukan prosedur top-up kartu fisik, bukan otorisasi USB, dan bukan bukti siap produksi.

## Ruang lingkup, fakta, dan asumsi

Komputer Windows adalah aplikasi operator; reader USB kelak hanya bridge NFC ber-domain terbatas. Komputer tidak boleh menerima/mengirim APDU, blok kartu, UID, Key A/B, derivasi key, atau perintah PN532 mentah.

`windows_topup/docs/USB_READER_CONTRACT.md` adalah **usulan**, belum diimplementasikan firmware. Inspeksi `firmware/smartdispenser_firmware/src/onefile/Topup.cpp` menunjukkan UART sekarang logger dan top-up masih dilakukan MCU.

Fakta aplikasi saat ini:

- Mode awal simulasi, tidak membuka COM/perangkat.
- Simulator menerima 1, 5, 10, 20 L; batas saldo 100 L; revision menolak state lama.
- `request_id` yang sama idempoten pada simulator dan sukses memerlukan wallet final/readback.
- Audit JSONL memakai token kartu hash/potong, saldo, dan revision; bukan UID/secret.

Asumsi UAT: operator memakai akun Windows organisasi, simulator mewakili adapter secured kelak, dan satu transaksi dilakukan satu operator untuk satu kartu. Login aplikasi, role/otorisasi server, pemilihan COM, dan adapter USB produksi belum ada; seluruhnya adalah gate, bukan klaim implementasi.

## Peran dan PIC

| Peran | PIC sebelum UAT | Tanggung jawab | Larangan penting |
|---|---|---|---|
| Operator | Supervisor operasional menunjuk nama | Scan, review, nominal, konfirmasi, simpan nomor transaksi | Retry dengan ID baru setelah hasil ambigu |
| Supervisor | Pemilik proses bisnis | Akses operator, keputusan insiden, rekonsiliasi audit | Mengubah saldo lewat file audit/simulator |
| Admin Windows/IT | Pemilik PC | ACL akun, instalasi EXE resmi, waktu/backup audit | Mengakses/mengirim key kartu |
| Engineer aplikasi | Pemilik `windows_topup` | Build, unit test, review adapter/log | Mengaktifkan mutasi USB tanpa gate |
| Engineer reader | Pemilik bridge firmware | Bridge fail-closed dan bench low-voltage | Memakai UART logger sebagai bridge produksi |
| QA/UAT lead | Penanggung jawab evidence | Jalankan matriks dan sign-off tahap | Menyamakan simulasi dengan USB/kartu fisik |

Nama PIC aktual, jalur eskalasi, retensi audit, dan kebijakan nominal harus ditetapkan supervisor sebelum UAT formal.

## Alur operator target

1. **Masuk dan otorisasi.** Operator login Windows dan membuka EXE resmi. Versi target wajib memeriksa role top-up serta mencatat `operator_authorized`; versi kini belum melakukannya. Role/sesi tidak valid berarti tidak ada scan atau mutasi.
2. **Koneksi reader.** Pilih reader terdaftar dan handshake bridge v1. Jika USB/COM putus, frame/versi buruk, atau reader tidak sehat, fail-closed. Bila request sudah dikirim, tandai `ambiguous`; jangan top-up ulang otomatis.
3. **Scan dan cek wallet.** Setelah `card_present`, kirim `wallet_read`. Tampilkan token aman, saldo, aktif/nonaktif, revision, serta status. Kartu hilang/bertukar membatalkan tinjauan dan nominal belum dikonfirmasi.
4. **Pilih nominal.** UI menghitung saldo sebelum→sesudah, tetapi reader tetap menguji kartu hadir, nominal, batas saldo dan `expected_revision`; UI bukan otoritas tunggal.
5. **Konfirmasi.** Tampilkan token, nominal, saldo sebelum/proyeksi sesudah. Batal sebelum request tidak mengubah wallet dan dicatat `topup_cancelled`.
6. **Commit dan readback.** Buat satu UUID `request_id`, kirim `topup_request`, dan nyatakan sukses hanya bila `topup_result` sukses berisi state/readback final yang cocok (request, nominal, token, revision baru). ACK transport bukan sukses.
7. **Audit dan selesai.** Catat waktu, pseudonim/ID operator sesuai kebijakan, versi EXE/bridge, request ID, event, nominal, token aman, saldo/revision sebelum-sesudah, outcome/error. Jangan catat UID/key/APDU/data blok/data pelanggan. Tampilkan nomor transaksi lalu idle sesudah kartu dilepas.

## Cancel, error, dan recovery

| Keadaan | Tindakan operator | Aturan aplikasi/reader | Bukti |
|---|---|---|---|
| Batal sebelum konfirmasi | Pilih batal | Tidak kirim request; wallet tidak berubah | Event cancel |
| Kartu hilang sebelum request | Tempel ulang, scan ulang | Batalkan kandidat | Event kartu hilang; tanpa request ID |
| Kartu hilang sesudah request | Jangan scan kartu lain; eskalasi | Outcome ambigu sampai rekonsiliasi ID sama | Request ID, error, readback |
| USB/COM timeout/putus | Jangan klik top-up baru | Retry ID sama pada sesi sama atau `wallet_read` | Disconnect/timeout + rekonsiliasi |
| Revision/nominal/saldo ditolak | Scan ulang, review | Tidak buat ID baru dari state lama | Error + wallet terbaru |
| Respons hilang setelah commit | Jangan anggap gagal | Readback atau resend ID sama; harus idempoten | ID dan wallet final |
| PC/aplikasi mati | Jangan ulang berdasar ingatan | Supervisor cocokkan audit dan readback | Catatan insiden/outcome |
| Saldo beku/transaksi tunda | Hentikan dan eskalasi | Tidak diubah tanpa policy recovery | Status dan tiket |

## Matriks UAT tanpa hardware

Jalankan dari `windows_topup`: `py -3.12 -m unittest discover -s tests -v`, lalu UI simulasi. Gunakan token simulasi/non-produksi. Catat PASS/FAIL, operator, waktu, versi source/EXE, dan audit tersanitasi.

| ID | Skenario/rangsangan | Hasil penerimaan |
|---|---|---|
| SIM-01 | Buka UI tanpa simulasi | Menyatakan mode simulasi; tidak membuka COM; tidak ada mutasi |
| SIM-02 | `Simulasikan kartu`, lalu `Scan ulang` | Token aman, saldo/aktif/revision tampil; audit tanpa UID/key |
| SIM-03 | Saldo 10, tambah 5, setujui | Final 15, revision naik satu, request ID dan `topup_completed` ada |
| SIM-04 | Tolak dialog konfirmasi | Event cancel; saldo/revision tidak berubah |
| SIM-05 | Unit test saldo 95, tambah 10 | Ditolak; saldo tidak berubah |
| SIM-06 | Unit test `expected_revision` lama | Ditolak; scan ulang diperlukan |
| SIM-07 | Dua `topup` dengan UUID sama | Wallet final sama; tidak ada kredit kedua |
| SIM-08 | Unit test frame panjang/versi tidak sah | `ProtocolError`; tidak diproses |
| SIM-09 | `SecureReaderAdapter` read/mutasi | Gagal tertutup; tidak ada NFC nyata |
| SIM-10 | Periksa audit SIM-02/03 | Hanya token aman/metadata diizinkan; tanpa UID/key/APDU/blok |

SIM-07 sampai SIM-09 dijalankan sebagai fixture/unit test, bukan dengan modifikasi aplikasi produksi. Simulasi tidak membuktikan USB, driver, PN532, autentikasi kartu, atomisitas write, atau kartu fisik.

## Tahap bukti dan gate

| Tahap | Bukti diterima | Tidak dibuktikan |
|---|---|---|
| Simulasi | UI/unit test, model idempoten/batas saldo, sanitasi audit | EXE final, USB, PN532, kartu, secret |
| Build EXE | Build sukses, hash/versi artefak, instalasi terkendali | Runtime PC target/hardware |
| USB low-voltage | Bridge direview, capture tersanitasi, reconnect/timeout/cabut-kabel | Autentikasi kartu/anti-clone tanpa uji khusus |
| Kartu fisik | Sampel disetujui, auth, read/write/readback, cabut/power-loss, retry same-ID | Produksi, keselamatan AC, endurance |
| Operasional | PIC/ACL, SOP insiden, retensi/rekonsiliasi, UAT sign-off | Sertifikasi/compliance/crypto belum dibuktikan |

Gate OPEN: profil wallet tunggal untuk kontrak Windows (repo berisi profil Classic satu-blok fungsional dan desain wallet terenkripsi/jurnal yang lebih kuat); login/role; bridge secured + firmware/review; kebijakan nominal, retensi audit, transaksi ambigu dan saldo beku; bukti USB/kartu/fault/power-loss; serta penyimpanan/rotasi secret di luar EXE/repository. Sampai gate relevan ditutup, EXE hanya demonstrasi simulasi.

## Referensi diperiksa

- `AGENTS.md`
- `windows_topup/README.md`, `app.py`, `topup_core.py`, `tests/test_topup_core.py`, `docs/USB_READER_CONTRACT.md`
- `firmware/smartdispenser_firmware/src/onefile/Topup.cpp`
- `docs/DESIGN_NFC_PERSO_DISPENSER.md`, `docs/PROVISIONING_AB.md`, `docs/TECHNICAL_SPEC_WALLET_V2_SATU_BLOK.md`
