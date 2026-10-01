# Status implementasi firmware A/B

## Keputusan terbaru — target Classic

Paket kandidat terbaru tersedia di
`firmware/smartdispenser_firmware/.pio/packages/candidate_classic_02/`.
Keempat profil normal/servis A/B berhasil dibangun; suite host 38.107 pemeriksaan
dan fixture provisioning lulus. Verifikasi pascapaket mencocokkan SHA-256 delapan
artefak binary/ELF, lima dokumen, serta 89 file sumber terhadap manifest.
Paket menggunakan kebijakan satu master tetap, tidak membawa credential, dan
belum di-upload. Status tetap kandidat: audit software menyeluruh belum ditutup
dan pengujian perangkat merupakan pekerjaan pengguna. Paket 01 bukan terbaru.

Tambahan audit master tetap: suite host lulus 38.107 pemeriksaan, termasuk
pembatalan hitungan enrollment saat kartu diangkat/diganti/tombol dilepas,
penolakan penggantian master setelah reboot, serta larangan izin operator bagi
UID master tanpa autentikasi atau identitas master yang berbeda. Tes aplikasi
memakai adapter model; pembuktian kriptografi chip fisik tetap terpisah.

Verifikasi terbaru setelah keputusan master tetap: build normal `smartdispenser_a`
dan `smartdispenser_b` berhasil. Suite host lulus 38.088 pemeriksaan. Tambahan
tes alur B membuktikan pada model: izin kedaluwarsa saat browsing/edit setelah
60 detik, cancel menghabiskan izin, sukses hanya mengizinkan satu perubahan,
95+5 L diterima, 96+5 L ditolak tanpa mengubah saldo, dan kegagalan tersebut
tidak memberikan izin perubahan kedua. Ini belum bukti tombol/NFC perangkat.

Pengguna membatalkan kebutuhan pergantian master/migrasi: B hanya memiliki satu
master tetap. Pekerjaan migrasi dihentikan dan tidak menjadi syarat penyelesaian
firmware. Fondasi yang sudah dibuat belum terhubung ke runtime; bukan fitur aktif.
Catatan migrasi di bawah adalah riwayat sebelum keputusan ini. Fokus tersisa:
audit alur A/B, verifikasi build/test, paket terbaru, dan checklist uji pengguna.
Master hilang/rusak tidak memicu bypass atau reset otomatis.

Fondasi migrasi `KeyVersions` mendukung konteks customer aktif dan satu versi
sebelumnya dengan identitas system/device/application konsisten. Selector versi
dari header tetap harus melewati GCM; perubahan versi palsu, UID berbeda, atau
versi tidak dikenal ditolak. Otorisasi master mengacu konteks aktif, bukan otomatis
master lama. Tes host terbaru 36.528 pemeriksaan lulus. Modul ini belum diaktifkan
di runtime: persistensi/aktivasi migrasi dan pergantian kunci kartu masih terbuka.

Recovery jurnal A yang tertinggal setelah B menangani cadangan diperbaiki:
versi kartu lebih baru dengan reservation Frozen/hilang tidak ditimpa checkpoint
lama. A mempertahankan catatan pulsa, menutup pending lokal tanpa write saldo,
dan kembali menu. Konflik lain menampilkan CEK TRANSAKSI dengan intent tetap
tersimpan. Tes pencairan parsial/penuh B lalu kembali A lulus, tanpa revision
atau saldo tambahan. Suite host terbaru: 36.504 pemeriksaan lulus.

Audit binding kartu menambahkan pemeriksaan autentikasi/identitas sebelum
transisi timer Detected/Chosen dan pada menu B. Kartu hilang, diganti, atau UID
sama tanpa autentikasi membatalkan menu/izin; tidak maju ke halaman Start.
Tes host mencakup A/B, halaman deteksi/menu, dan transisi konfirmasi terputus;
suite terbaru 36.484 pemeriksaan lulus. Paket kandidat 01 belum mencakup ini.

Reservasi stack minimum khusus profil A/B dinaikkan dari legacy 1 KiB menjadi
8 KiB setelah audit frame transaksi 1.088 byte. Build A/B berhasil dan simbol
ELF menunjukkan 0x2000; heap allocator framework menghormati batas tersebut.
Tidak mengklaim high-water/call-chain maksimum sudah diukur. Paket kandidat 01
belum memuat perubahan ini maupun perbaikan laporan LCD A/B terakhir.

CLI `package_provisioning.cjs` dapat mengemas B terlebih dahulu dan A1/A2 setelah
laporan master cocok. File/direktori tidak ditimpa; marker selesai ditulis
terakhir. Test fixture Node lulus. `service_ab.ps1` menyediakan kirim sekali
atau capture metadata, dengan mode default validasi tanpa port, guard tegangan
rendah dan konfirmasi eksekusi. Sintaks dan validasi tanpa port lulus; belum
membuka UART, menghasilkan credential produksi, atau mengubah perangkat.

Ekspor master melalui query `?` tersedia khusus image servis B, di luar paket
provisioning. Metadata berasal dari konfigurasi dan registry master committed,
bukan pembacaan UID pelanggan atau autentikasi kartu live. Respons tidak memuat
root/key; normal firmware tidak memproses query. Tes host 36.443 pemeriksaan
lulus, termasuk registry pending dan buffer respons terlalu kecil ditolak.
Pengiriman/capture file servis dari host masih perlu dilengkapi.

Pembuat bundle provisioning tiga device tersedia di `provisioning_bundle.cjs`:
root envelope/debit dibagi A/B, root issuer/admin/master hanya B, random dan ID
device berbeda. Bundle A baru dapat diikat setelah metadata master B cocok;
konfigurasi B awal tidak diubah. Test fixture Node lulus tanpa menghasilkan
secret produksi, menulis file privat atau mengakses device. Ekspor metadata
master dari B dan CLI pengiriman/pengemasan final masih terbuka.

Audit provisioning menambah simulasi putus tulis di seluruh 161 batas operasi
konfigurasi awal, penolakan perubahan root pada konfigurasi committed, pemisahan
profil A/B, kapasitas penyimpanan kurang, registry device berbeda, dan konfigurasi
rusak. Retry provisioning identik mempertahankan byte jurnal (termasuk master,
pending dan recovery), sementara counter maju. Suite host: 36.435 pemeriksaan
lulus. Uji ini tidak mencakup provisioning aktual melalui UART/ST-Link.

Audit recovery A memperbaiki pemulihan binding kartu setelah reboot: kembali
ke menu tidak lagi memicu kesalahan kartu berganti untuk kartu yang sama.
Simulasi mencakup listrik terputus sebelum intent reserve, sebelum write reserve,
sesudah reserve committed tetapi intent belum selesai, dan sesudah checkpoint
323 pulsa. Tidak ada start aktuator otomatis; cadangan yang belum selesai
dibekukan, bukan diasumsikan sebagai air yang pasti belum keluar.

Audit UI menambahkan indikator biru untuk menu pelanggan/konfirmasi, merah untuk
penolakan/error, dan mempertahankan kepemilikan LED biru oleh pulsa saat flow.
Kartu tidak dikenal memakai halaman penolakan 3 detik lalu utama dengan syarat
kartu dilepas sebelum deteksi baru. Tes host terbaru: 33.916 pemeriksaan lulus;
build A/B berhasil. Checklist keamanan diperbaiki agar tidak lagi mengklaim
anti-rollback atau pembatasan top-up tingkat chip DESFire pada kartu Classic.

Pengguna mengonfirmasi tetap memakai kartu yang dilaporkan scanner sebagai
MifareClassic/NfcA/NdefFormatable. Pemilihan jenis chip tidak lagi menjadi blocker.
Kapasitas belum diketahui. Revisi batas keamanan dicatat di design; dukungan
Classic tidak boleh diklaim memiliki anti-cloning/rollback setara DESFire.

`ab_classic_blocks.h` dan `Pn532Channel::classicExchange` mulai menyediakan
autentikasi sektor, read 16 byte dan write data + readback, dengan geometri
eksplisit serta binding sesi. Write sektor 0/trailer ditolak oleh jalur data.
`ab_main.cpp` sekarang memakai `ClassicCards`, bukan placeholder. Boot memuat
provisioning dan jurnal, lalu menginisialisasi transport NFC; konfigurasi tidak
valid tetap berada di halaman setup tanpa transaksi. Kartu UID empat byte dengan
SAK 08/18 memakai jendela akses konservatif 1K, hanya sektor yang diperlukan.
Ini indikator kompatibilitas, bukan bukti kapasitas fisik atau keaslian chip.
Autentikasi dan readback tetap wajib; Mini/SAK lain ditolak oleh transport.

**Koreksi cakupan build:** sebelumnya filter A/B belum memasukkan berkas CPP
Classic dan transport NFC. Build historis tidak membuktikan integrasi tersebut.
Filter kini memasukkan `ab_*.cpp` dan `bounded_pn532_i2c.cpp`; build integrasi
A/B berhasil setelah koreksi. Suite host terakhir: 33.907 pemeriksaan lulus.
Belum upload atau menguji kartu/perangkat fisik.

Pemulihan pending B setelah reboot memakai jalur idle yang dapat menangani
perso parsial, bukan jalur kehilangan kartu saat flow milik A. Uji integrasi
memastikan pending terselesaikan tanpa membuka aktuator.

P2 pada A kini disampel timer 1 kHz, debounce 30 sampel, untuk meminta RST tanpa
menunggu loop NFC. Penyelesaian saldo/laporan tetap di main loop. Ini rancangan
waktu software; latensi aktual ISR/relay dan kontak belum diukur. Pemulihan
transport NFC dibatasi satu percobaan per detik dan hanya saat bukan dispensing.

### Integrasi antarmuka kartu Classic

`ab_classic_cards.cpp` menyediakan `CardPort` untuk baca/autentikasi customer,
master, perso, perubahan saldo, dan readback transaksi. Backend ini sengaja
terpisah dari kontrak `SecureChip` DESFire: tidak mengklaim counter native atau
anti-rollback chip. Kapasitas masih parameter eksplisit 64/256 blok, bukan hasil
identifikasi kartu pengguna. Runtime memakai jendela 64 blok yang dibatasi
SAK kompatibel; lihat catatan integrasi boot di atas.

Simulasi lintas peran memakai satu model kartu: perso 20 L di B, retry tanpa
write tambahan, baca di A, reservasi 5 L, retry tanpa potongan tambahan, penolakan
top-up melalui A, kemudian baca/top-up kembali di B. UID sama pada kartu factory
tidak diterima A sebagai customer. Total suite host: 33.905 pemeriksaan lulus.
Build A/B berhasil; belum ada uji RF maupun upload atas integrasi ini.

### Detail saldo awal Classic

`ClassicWalletStore::initialize` menambahkan saldo awal dari intent perso yang
identik dengan transaksi tersimpan, setelah tahap pemeriksaan kartu kosong dan
pemasangan kunci oleh pemanggil. Dua bank invalid tidak dianggap sebagai bukti
kartu baru. API ini hanya boleh dipanggil dari pemulihan/perso ber-intent;
`ClassicCards::personalize` menghubungkannya dengan pemasangan kunci pelanggan.

Penulisan menggunakan invalidasi bank tujuan, payload GCM, lalu marker terakhir.
Retry atas saldo awal yang sudah sah tidak menulis/top-up lagi walaupun nonce
envelope retry berbeda. Saldo yang sudah berubah setelah perso menolak retry
perso lama. Simulasi menguji setiap batas byte pada 224 byte penulisan awal dan
perubahan saldo; bank sumber harus tetap utuh. Ini bukan bukti atomic write
chip maupun perlindungan rollback terhadap penyerang.

### Pemasangan kunci pelanggan Classic

`ab_classic_issuer.cpp` memerlukan registry B dengan master terdaftar dan intent
perso persisten untuk UID serta device yang sama. Seluruh sektor 1–10 diperiksa
sebelum write pertama: sektor harus sudah memakai kedua kunci turunan dan ACL
yang benar, atau masih factory dengan data kosong. Data asing pada sektor akhir
menolak proses tanpa mengubah trailer sektor awal.

Sektor factory diperiksa ulang sebelum diganti; pemasangan memverifikasi kedua
kunci lewat autentikasi baru. Retry melewati sektor yang sudah selesai. Jalur
ini tidak menulis data saldo, sektor 0, atau sektor master 11. Simulasi pencabutan
kartu setelah masing-masing dari sepuluh write trailer berhasil dipulihkan;
sektor selesai tidak ditulis ulang. Total suite host saat penambahan ini: 33.884
pemeriksaan lulus. Ini model protocol/block, bukan bukti kartu fisik tahan tear.

### Detail master Classic

`ab_classic_master.cpp` memakai sektor 11: blok 44–46 untuk record kanonis
48 byte (header 32 byte + AES-CMAC 16 byte), trailer 47 untuk Key A/B hasil
derivasi khusus master. Autentikasi memeriksa registry B, autentikasi sektor,
ACL master, dan seluruh record; kecocokan UID saja tidak memberi izin.

Pemasangan hanya diizinkan bila registry persisten mempunyai `masterInstalling`
untuk kartu dan device yang tepat. Sebelum mengganti trailer pabrik, sektor
1–11 wajib memiliki ACL transport dan data kosong; sektor 0 tidak ditulis.
Sesudah trailer terpasang, retry dapat melengkapi record yang terputus.
Status `masterSet` tetap menjadi commit aplikasi setelah verifikasi berhasil.
Master yang telah terdaftar tetapi record-nya berubah ditolak, bukan ditulis ulang.

Simulasi PN532 mencakup kehilangan respons pada trailer/tiga blok record,
rekonstruksi objek setelah reboot, retry tanpa write ganda, record berubah,
registry salah/rusak, kartu berisi data lain, dan kapasitas Mini ditolak.
Simulator tidak membuktikan Crypto1, timing RF, ketahanan EEPROM kartu, atau
anti-cloning. Record master statis masih dapat disalin jika perlindungan
Classic berhasil ditembus. Pengujian fisik dan integrasi runtime masih terbuka.

## Riwayat keputusan yang sebelumnya ditunggu (sudah terjawab)

Target chip belum dikunci: DESFire EV3 masih kandidat dalam design. Pengguna
diminta memastikan apakah firmware ditargetkan ke DESFire EV3 atau harus memakai
100 kartu yang sudah dimiliki (perlu tipe/tautan produk atau hasil identifikasi).
Belum ada bukti identifikasi kartu pengguna yang ditemukan pada artefak proyek;
log di `scripts/testdata` bukan bukti kemampuan kartu fisik.

Implementasi bootstrap pabrik, klasifikasi blank, instalasi aplikasi/key/file
dan pengaktifan backend menu tidak dilanjutkan berdasarkan tebakan jenis chip.
Kode kandidat yang sudah dibuat dipertahankan. Build sukses terakhir tidak
membuktikan kompatibilitas kartu; runtime normal masih `UnprovisionedCards`.
Tahap 5 belum selesai, integrasi penuh dan audit design belum selesai, tidak ada
upload. Estimasi persentase bukan bukti kesiapan firmware maupun hardware.

Setelah keputusan kartu tersedia: cocokkan kebutuhan protokol dengan chip yang
dipilih, laporkan setiap penyimpangan design, lalu selesaikan backend dan alur
perso/master A/B. Jika hanya identifikasi fisik yang diperlukan, minta arahan
pengguna sebelum akses programmer/UART/perangkat; tidak menganggapnya diizinkan
oleh kelanjutan otomatis goal ini.

Pekerjaan belum selesai; jangan menganggap build sebagai bukti kartu/keamanan siap.
Arahan terbaru pengguna: selesaikan software dua environment dahulu, ST-Link sesudahnya.
Persetujuan tambahan: saldo maksimum 100 L, empat slot cadangan/beku per kartu.
Pembagian kerja terbaru: Codex menyelesaikan implementasi firmware, pemeriksaan
kode dan build. Pengujian perangkat A/B dilakukan pengguna berdasarkan checklist
`CHECKLIST_UJI_AB.md`. Uji perangkat tidak dijadikan syarat untuk melanjutkan
implementasi software, tetapi hasilnya tetap wajib sebelum klaim fitur teruji.

## Sudah ada di source

- `ab_classic_access.h`/`ClassicBlocks::installTrailer`: validasi bit komplemen,
  profil trailer 011 (key B mengubah key/ACL, key tidak bisa dibaca), data
  pelanggan 000 (read/write A/B), data master 100 (write B). Sektor 0 ditolak;
  wallet dibatasi 1..10, master sektor 11. Setelah write, autentikasi ulang key A
  dan B serta cek ACL/GPB, bukan membandingkan byte key yang dibaca sebagai nol.
  Caller wajib menyimpan intent sebelum pemanggilan; integrasi intent/perso
  belum selesai, belum diuji pada kartu. Salah access bits berisiko mengunci sektor.
  Pembatasan top-up hanya B pada Classic masih aturan firmware, bukan kontrol
  debit-only chip. MCU A yang dikuasai penyerang tidak mendapat jaminan tersebut.

- `ab_classic_data.h`: port dompet ke autentikasi sektor Classic; bind kartu
  eksplisit dan invalidasi ketika generation/session berubah. A memakai key A,
  B key B; derivasi terpisah per kartu/sektor/jenis key melalui AES-CMAC KDF.
  Key hardware Classic hanya 48 bit, bukan keamanan AES 128 bit pada chip.
  Sector 0/trailer/di luar sektor bank 1..10 ditolak. Belum pemasangan trailer
  dan ACL, master/perso atau aktivasi runtime; belum uji komunikasi fisik.

- `ab_classic_wallet_store.h`: dua bank envelope GCM, sektor 1..5 dan 6..10,
  masing-masing satu blok marker + 12 blok payload; sector 0/trailer tidak
  disentuh. Invalidate tujuan, tulis payload, marker terakhir, readback/GCM/revisi.
  Memerlukan Classic 1K atau 4K yang telah diidentifikasi; Mini tidak muat format
  empat cadangan/beku ini. Belum port autentikasi sektor, inisialisasi kartu baru,
  integrasi runtime atau uji power-cut. Pemilihan bank valid bukan anti-rollback;
  data lama yang sah masih dapat dipulihkan penyerang, sesuai batas desain Classic.

- Recovery konfigurasi sebelum commit: paket servis tepercaya dapat melanjutkan
  marker 0 bila setiap byte sebelumnya cocok dengan paket atau masih erased FF.
  Konfigurasi committed A5 tidak diperbaiki/ditimpa dengan aturan ini. Counter
  baru dibuat setelah konfigurasi committed. Ini pemulihan penulisan awal, bukan
  migrasi key atau jaminan autentikasi kanal servis. Belum diuji power-cut fisik.

- `ab_provisioning_receiver.h` dan cabang servis `ab_main.cpp`: compile flag
  `SMARTDISPENSER_PROVISIONING_SERVICE=1` mengaktifkan penerima UART lokal
  115200 untuk prefix ASCII SDPV1 + konfigurasi kanonis 160 byte. Timeout paket
  2 detik, validasi lengkap sebelum provisioning, buffer dibersihkan setelah
  selesai/gagal, log hanya kode hasil. Mode ini tidak menjalankan menu/NFC/flow
  dispensing; reset relay boot A tetap berjalan. Flag tidak aktif pada build
  normal. UART servis cleartext tanpa autentikasi: hanya bench lokal tepercaya,
  wajib kembali ke image normal sebelum dipasang di lapangan. Belum upload/uji UART.

- `ab_device_provisioner.h`: urutan provisioning lokal menyatukan konfigurasi
  immutable, counter autentikasi/wallet dan jurnal awal. Retry mempertahankan
  jurnal yang ada beserta master/sequence/transaksi pending; counter tidak direset.
  Device ID konflik/area jurnal rusak ditolak. Tidak dipanggil otomatis saat boot
  dan belum mempunyai transport servis. Partial record rusak masih memerlukan
  prosedur servis eksplisit, bukan penghapusan otomatis. Belum uji power-cut.

- `scripts/encode_provisioning.cjs`: codec offline konfigurasi 160 byte yang
  sama dengan `ConfigurationStore`; validasi profil, UID, angka, root terpisah
  dan CRC. Input JSON/output bin wajib di luar repo, output existing tidak
  ditimpa, error tidak mencetak secret. Schema: role A/B, system/device/version/
  epoch/application integer positif, masterUid hex (boleh kosong untuk B awal),
  roots berisi envelope/debit/issuer/applicationAdmin/masterAuthentication/random
  masing-masing hex 16 byte. Root khusus B pada A wajib nol. Secret harus berasal
  dari provisioning CSPRNG tepercaya, bukan UID; codec tidak menghasilkan secret.
  Baru diperiksa sintaks Node; belum roundtrip/test integrasi. Tidak menulis
  perangkat dan belum provisioning lengkap (counter/jurnal/transport belum ada).
  File tersebut rahasia dan membutuhkan ACL Windows; mode file POSIX 0600 bukan
  jaminan ACL Windows. String JSON dalam runtime Node tidak dijamin terhapus RAM.

- `ApplicationKeyInstaller::retryPending`: jalur retry eksplisit untuk intent
  tersimpan. Coba bukti key baru dahulu; jika belum selesai, buktikan key lama
  pada slot target sebelum autentikasi admin dan write ulang. Tidak membuat
  intent baru, tidak mengganti kartu/slot dan tidak memakai key default fallback.
  Belum dipanggil UI/servis dan belum diuji fault fisik. Bootstrap DES legacy
  PICC pabrik masih belum tersedia pada dependency kriptografi saat ini.

- Pembuatan aplikasi AES melalui sesi PICC AES admin tersedia; pengaturan kandidat
  0x09 dan jumlah key 2 untuk master/4 untuk pelanggan. Pemeriksaan key settings
  sudah ditambahkan setelah autentikasi client wallet dan master. Bootstrap
  PICC pabrik dengan key legacy belum diimplementasikan; tidak ada fallback key
  default otomatis. ACK create masih wajib dilanjutkan autentikasi/readback aplikasi.
- `ab_wallet_issuance.h`: membuat file hilang tanpa menghapus konflik, memeriksa
  nilai native awal, lalu menginisialisasi izin dan envelope dalam satu commit.
  Envelope nonkosong yang berbeda ditolak; retry selesai direkonsiliasi lapisan
  atas. Masih memerlukan orkestrasi intent, key, aplikasi dan integrasi menu.

- Inventaris file authenticated `GetFileIDs` dan `inspectBackup/inspectValue`
  membedakan Missing/Matching/Conflict/Unavailable. Daftar ID duplikat/di luar
  batas ditolak. Komunikasi gagal tidak dianggap aplikasi kosong; hasil Matching
  hanya membuktikan kebijakan file, bukan nilai saldo/isi file atau kepemilikan
  intent perso. Primitive tersedia untuk recovery; orchestrator belum selesai.

- `DesfireFiles::createBackup/createValue`: perintah pembuatan file encrypted
  dengan sesi admin slot 0, validasi batas/ACL dan readback kebijakan file.
  Error/ACK hilang tetap uncertain; tidak menerima duplicate sebagai sukses
  atau menghapus file konflik. Nilai awal harus dibaca melalui sesi issuer
  sebelum perso final; create bukan transaksi backup atomik dan memerlukan
  intent pemulihan di orchestrator. Belum terhubung alur perso dan belum uji
  kartu fisik. Format perintah merujuk
  [libfreefare create_file1/create_value_file](https://raw.githubusercontent.com/nfc-tools/libfreefare/master/libfreefare/mifare_desfire.c).

- `ab_desfire_chip.h/.cpp`: adapter `SecureChip` ke client wallet dan autentikasi
  master AES slot 1 (slot 0 tetap admin). Master bukan wallet pelanggan.
  Deteksi hanya memberi hint; autentikasi ulang tetap wajib. Baca envelope
  mencocokkan native state melalui client wallet. Administrasi kartu baru/perso
  masih berupa kontrak `DesfireAdministration`, bukan implementasi lengkap;
  adapter belum diinstansiasi runtime. Tidak ada fallback aplikasi-hilang=blank.
  Pembacaan berulang antar-layer masih perlu ditinjau pada integrasi/latensi.

- `ab_desfire_wallet.h/.cpp`: client aplikasi pelanggan yang sudah diperso.
  Scan UID yang diharapkan, pilih aplikasi, autentikasi key 2 A/key 3 B,
  baca envelope, verifikasi GCM dan cocokan dengan native saldo/total/revisi/izin.
  Commit memakai perubahan wallet yang tepat dan transaksi native multi-file,
  lalu readback; gagal/uncertain tidak menjadi sukses dari ACK saja.
  Tidak mengklasifikasikan aplikasi hilang sebagai kartu blank. Client belum
  dipanggil menu, belum adapter `SecureChip`, perso atau autentikasi master.
  Belum ada bukti interoperabilitas kartu fisik ataupun uji fault client ini.

- `ab_security_boot.h`: sudah dipanggil runtime setelah reset relay A.
  Memuat konfigurasi, memeriksa device ID terhadap jurnal, mengikat identitas
  master dari registry pending/terdaftar, memvalidasi counter envelope melalui
  alokasi satu nonce, lalu menginisialisasi random autentikasi dari counter boot.
  Tidak membuat konfigurasi/counter/jurnal otomatis. Secret sementara dibersihkan;
  log hanya kode tahap, tanpa UID/key. `Ready` di sini hanya kesiapan bahan
  keamanan lokal, bukan bukti kartu/transport siap. `UnprovisionedCards` masih
  menahan aplikasi dari transaksi. Epoch counter wallet memakai versi key;
  epoch counter random memakai epoch konfigurasi, jangan disamakan saat provisioning.

- `ab_configuration_store.h`: format konfigurasi kanonis 160 byte, pemeriksaan
  profil/parameter/root, commit marker terakhir dan readback. Provisioning hanya
  menerima area kosong atau retry data identik; record prepared lengkap dapat
  menyelesaikan marker. Partial record lain menolak operasi dan perlu servis,
  tidak dianggap alasan menghasilkan secret baru. Buffer sementara dibersihkan.
  Format ini menyimpan secret di EEPROM lokal tanpa enkripsi at-rest/anti-tamper;
  CRC bukan autentikasi. Provisioning channel, readout protection, backup aman,
  pemulihan partial provisioning dan migrasi masih perlu diselesaikan. Belum ada
  konfigurasi produksi yang ditulis. Store sudah dibaca oleh pemeriksaan boot.

- `ab_device_keys.h/.cpp`: implementasi `KeyProvider` berbasis konfigurasi
  tervalidasi. Profil A wajib tidak mempunyai root issuer/admin/master-auth;
  root envelope, debit dan random terpisah. B menerima enam root independen,
  menolak root kosong/erased atau root sama antarfungsi. Derivasi mengikutkan UID
  master terdaftar dan UID pelanggan. Binding master tidak boleh mengganti UID
  yang sudah ada. Pemeriksaan ini tidak membuktikan entropy secret; penyedia
  konfigurasi persisten sudah dibaca saat boot; kanal provisioning belum ada. Tidak ada secret
  produksi yang dibuat atau dimasukkan repo. B sebelum master terdaftar belum
  dapat menurunkan key pelanggan; alur enrollment harus mengikat identitas
  pending secara persisten sebelum pemasangan, lalu memverifikasi autentikasi.

- `ab_key_installer.h/.cpp`: penghubung intent persisten, seleksi kartu/aplikasi,
  AuthenticateAES, ChangeKey dan autentikasi ulang key tujuan. ACK tidak menjadi
  bukti keberhasilan; operasi pending yang sama hanya diverifikasi saat retry,
  tanpa mengulang write otomatis. Parameter key disediakan pemanggil, tanpa
  fallback key pabrik. Versi native key memakai 8 bit rendah versi derivasi.
  Belum terhubung ke menu/master/perso; pembuatan aplikasi, pemasangan multi-slot,
  izin master aktual, dan retry servis jika intent tersimpan sebelum write masih
  harus diselesaikan. `Authority::Operator` adalah guard software, bukan bukti
  otorisasi master ataupun pengganti hak akses chip.

- `ab_installation_journal.h`: dua bank metadata pemasangan kunci, format
  kanonis tanpa secret, commit marker terakhir, CRC dan readback. Intent pending
  terikat kartu/operasi/aplikasi/slot/versi dan tidak dapat ditimpa intent lain.
  Status verified harus merujuk intent yang sama; bukti autentikasi fisiknya
  wajib disediakan orchestrator, belum terhubung pada runtime. Area rusak tanpa
  bank sah tidak dianggap kosong. Belum diuji power-cut; CRC bukan anti-tamper.

- `ab_storage_layout.h`: region EEPROM berbatas dengan pemeriksaan overflow dan
  kapasitas. Runtime jurnal memakai region 0..1023, bukan seluruh EEPROM lagi.
  Counter boot autentikasi 1024..1087; counter envelope 1088..1151;
  konfigurasi dicadangkan 1152..1663; intent pemasangan 1664..1919.
  Total layout 1920 byte; compiler menolak jika jurnal atau EEPROM tidak muat.
  Area konfigurasi/intent belum mempunyai implementasi format/provisioning.
  Pembatas alamat bukan perlindungan secret terhadap pembacaan fisik/debugger.
  Tidak ada penghapusan, migrasi, atau penulisan EEPROM perangkat pada tahap ini.

- `ab_auth_random.h/.cpp`: generator challenge HMAC_DRBG-SHA256 dengan seed
  turunan AES-CMAC dari secret acak khusus perangkat dan counter boot yang
  dipersistenkan sebelum dipakai. Menolak credential kosong/counter gagal,
  membersihkan state rahasia, dan tidak memakai UID/timer sebagai sumber random.
  Sudah diinisialisasi saat boot jika provisioning sah; belum diuji dengan vektor pembanding.
  Tidak mengklaim sumber entropy hardware, ketahanan rollback EEPROM oleh penyerang,
  atau sertifikasi NIST; kekuatan dibatasi secret provisioning 128 bit.
  Mekanisme rujukan: [NIST SP800-90A Rev.1](https://csrc.nist.gov/pubs/sp/800/90/a/r1/final).
- Pemasangan key aplikasi DESFire tersedia melalui `changeApplicationKey`:
  percobaan write membatalkan sesi, hasil wajib dibuktikan dengan autentikasi
  baru memakai key tujuan. Bukan implementasi lengkap provisioning/PICC rekey;
  jurnal pemasangan dan orkestrasi recovery masih diperlukan.

- `smartdispenser_a` dan `smartdispenser_b`: environment terpisah dan berhasil build.
- `ab_wallet.h`: transisi saldo integer, reserve/checkpoint kumulatif/settle/freeze/
  release, revisi, operasi idempotent, batas saldo/slot, pemeriksaan kewenangan logis.
- `ab_application.h`: controller A/B, enrollment master 10 detik dengan jurnal,
  otorisasi satu transaksi, menu/konfirmasi, timeout sesi, freeze lintas perangkat,
  pembacaan ulang melalui kontrak adapter, serta pemulihan operasi pending.
- `ab_journal.h`: dua bank, commit marker terakhir, CRC korupsi, readback.
  Menggunakan storage EEPROM melalui adapter MCU. Tidak menyimpan secret.
- `ab_crypto.cpp`: AES-CMAC RFC4493, KDF counter-mode SP800-108 dengan input UID
  master/pelanggan dan konteks role/system/version; AES128-GCM nonce 12 byte,
  tag penuh 16 byte. Primitive AES/GCM memakai `rweather/Crypto@0.4.0`.
  Plaintext hasil decrypt baru dilepas setelah tag terverifikasi.
- `ab_nonce.h`: counter nonce persisten pada dua bank khusus, terpisah dari jurnal
  aplikasi; perlu provisioning eksplisit, menolak counter korup tanpa rollback.
  Region dan instance counter sudah dipakai saat boot; provisioning belum tersedia.
- `ab_card_format.h`: format kanonis wallet 123 byte, envelope AES-GCM 179 byte,
  header/identitas pelanggan ikut diautentikasi. Ini bukan protokol DESFire.
- `ab_secure_cards.h`: adapter autentikasi, encrypt/write/readback, retry perso,
  dan penolakan klaim ACK yang tidak terbukti dari pembacaan ulang. Kontrak
  `SecureChip` dan `KeyProvider` masih memerlukan implementasi perangkat nyata.
- `ab_pn532_channel.h` / `ab_pn532_wire.h`: channel APDU melalui transport I2C
  bounded yang sudah ada, parser target Type A dan validasi panjang ATS/UID.
  Dipakai oleh `smartdispenser_card_identify`, belum transaksi saldo A/B.
  Tidak mengulang APDU write secara otomatis; error membatalkan target/session.
  Frame PN532 MI/NAD ditolak; dukungan chaining belum diimplementasikan.
- `ab_desfire_auth.h`: handshake `AuthenticateAES` (0xAA), pemeriksaan challenge
  kartu dan pembentukan session key. Belum secure messaging atau pemasangan key.
  Sesi batal setelah scan/raw APDU berikutnya; session key hanya dapat diserahkan
  satu kali. Sumber random produksi wajib disediakan melalui kontrak terpisah,
  tanpa fallback UID/timer/PRNG tidak di-seed. Belum dipanggil runtime A/B.
- `ab_desfire_mac.h`: sesi CMAC AES kompatibel EV1, IV diteruskan antar-command/
  response, tag respons diverifikasi sebelum data dilepas. Menolak replay dalam
  transcript uji, respons tanpa MAC, status gagal, dan sesi berubah. Mendukung
  command data enciphered AES-CBC dengan CRC32 internal sesuai protokol: panjang
  hasil harus diketahui, CRC/padding diverifikasi sebelum data dilepas, balasan
  write wajib CMAC sah. Ini bukan pengganti envelope AES-GCM wallet.
  Transfer saat ini satu frame terbatas; belum driver file/dompet terintegrasi.
  Memerlukan handshake pada channel yang sama, bukan session key arbitrer.
- `ab_desfire_files.h`: validasi kebijakan backup/value file (jenis, mode
  enciphered, hak akses, ukuran/batas), read 32 byte dan write 16 byte per chunk,
  Abort/CommitTransaction eksplisit. Transaksi terikat token sesi; ganti sesi
  tidak dapat meneruskan commit lama. Belum adapter dompet/runtime/provisioning.
- `ab_native_wallet.h`: kandidat penghubung dompet ke native value files untuk
  saldo tersedia, total belum terpakai dan counter revisi; izin aktif memakai
  backup file yang hanya dapat diubah key issuer B. Perubahan diterjemahkan ke
  Credit/Debit/LimitedCredit, ditulis bersama envelope, commit, lalu baca ulang.
  Belum diaktifkan dalam runtime; konfigurasi chip dan provisioning masih diperlukan.
- `ab_main.cpp`: LCD center, tombol debounce/release, flow interrupt A, timer
  pemutusan pulsa coil 60 ms, reset boot A, dan profil B tanpa aktuator.
- Delapan slot jurnal pemulihan lokal per perangkat (terpisah dari empat slot
  kartu); ketika penuh ditolak, tidak menimpa bukti. Ini kapasitas implementasi
  sementara yang masih harus ditinjau terhadap kapasitas/endurance EEPROM.

## Bukti pengujian saat ini

`scripts/test_ab.ps1` terakhir menghasilkan **PASS 7135 checks**. Angka ini mencakup
assertion berulang pada batas penulisan dan isi buffer, bukan 7135 fitur berbeda.
Test mengeksekusi C++ yang sama menggunakan backend kartu simulasi khusus host.
Termasuk floor 99/100/199/523, saldo 0/1/4/5/10/20, cap 100, penuh empat slot,
retry checkpoint/perso kehilangan ACK, partial freeze release, stale refund,
no-flow menunggu P2, kartu hilang 60 detik, reboot tidak resume, master dan wizard B,
serta power-cut tiap byte pada penulisan bank EEPROM simulasi. Uji kriptografi
menambahkan empat vektor CMAC RFC4493, known-answer AES-GCM, penolakan perubahan
cipher/tag/AAD/key/nonce, dan pemisahan derivasi sepuluh UID pelanggan beserta
perubahan UID master/system/version/role. Tambahan mencakup power-cut counter nonce,
perubahan tiap byte envelope, serta adapter dengan ACK hilang, ACK tanpa write,
retry tanpa saldo ganda, ciphertext dipindah ke UID lain, penolakan top-up dari A,
dan UID master cocok tetapi autentikasi gagal. Emulator chip hanya untuk host dan
tidak mengimplementasikan DESFire. Ini bukan bukti anti-cloning kartu.
Uji channel PN532 mencakup layout perintah, UID/ATS terpotong, target tidak valid,
status MI yang belum didukung, buffer hasil terlalu kecil, serta invalidasi target
setelah komunikasi gagal. Referensi layout:
[NXP PN532 UM0701-02, bagian 7.3.5 dan 7.3.8](https://www.nxp.com/docs/en/user-guide/141520.pdf).
Uji AuthenticateAES memakai transcript ciphertext pembanding yang dihitung dengan
.NET AES-CBC (bukan primitive firmware): key `00..0F`, RndA `10..1F`, RndB `20..2F`.
Ini fixture publik khusus host, bukan secret produksi atau rekaman kartu fisik.
Uji mencakup setiap byte proof/status diubah, frame pendek, kunci salah, random
gagal, key number tidak valid, session key satu kali, dan scan ulang UID sama.
Referensi alur autentikasi:
[libfreefare authenticate()](https://github.com/nfc-tools/libfreefare/blob/master/libfreefare/mifare_desfire.c).
Uji sesi MAC menggunakan transcript CMAC pembanding yang dihitung dengan AES
Node/OpenSSL: command GetValue diikuti Debit, IV berantai, respons/tag/status
diubah, respons lama diputar ulang, buffer kecil, dan pemilihan aplikasi yang
membatalkan sesi. Referensi alur:
[libfreefare AS_NEW crypto processing](https://raw.githubusercontent.com/nfc-tools/libfreefare/master/libfreefare/mifare_desfire_crypto.c).
Uji ini tidak membuktikan pemisahan kewenangan kartu atau penolakan rollback
dompet lintas perangkat; itu masih memerlukan driver dan uji chip.
Tambahan mode enciphered meliputi GetValue/Debit, ReadData 32 byte (3 blok AES
respons), WriteData 16 byte (2 blok AES command), IV berantai, ciphertext rusak,
CRC rusak dengan ciphertext valid, padding rusak, padding marker 0x80, respons
pendek, panjang data tidak cocok, dan setiap byte status/MAC write dirusak.
Fixture dapat direproduksi dengan `node scripts/crypto_transcript_fixtures.cjs`;
script hanya mencetak data uji publik dan tidak mengakses kartu atau secret.
Uji file yang sudah dilakukan sebelum pembagian kerja terbaru: setiap chunk write
dan read gagal, hasil read parsial tidak dilepas, file policy berubah, pergantian
sesi, abort, dan ACK commit hilang tanpa retry otomatis. Atomisitas chip dalam
uji ini adalah perilaku emulator, bukan hasil pengujian kartu pengguna.

Build A/B berhasil dengan warning aplikasi diperlakukan sebagai error. Warning
framework clock reset default tetap berasal dari variant baseline.

## Belum selesai / tidak boleh diklaim

- Adapter kartu nyata masih `UnprovisionedCards`: selalu tidak siap dan menolak
  commit/perso/master. Binary berhenti di `SETUP KEAMANAN`; ini sengaja tidak
  diganti dengan fake/UID-only. Belum firmware yang bisa dipakai pelanggan.
- Modul KDF/AEAD, envelope, counter nonce, dan adapter telah diuji bersama di host.
  Secure messaging, hardware key slots, provisioning role/device/key, migrasi
  master belum terintegrasi pada runtime A/B. Alokasi nonce dan pemeriksaan
  konfigurasi lokal sudah terhubung pada boot, tanpa mengaktifkan backend kartu.
  Generator challenge tersedia terpisah; penyedia secret provisioning dan
  counter boot sudah terhubung ke runtime tetapi belum ke alur kartu.
  Sesi MAC dan command data enciphered tersedia terpisah, tetapi belum pemetaan
  file/hak akses, transaksi chip, provisioning, atau validasi interoperabilitas.
  Jangan memakai seal() dengan nonce sembarang/berulang.
- Hak A/B di wallet software belum membuktikan pemisahan hak pada chip kartu.
- Model jurnal bukan wire format kartu. Kapasitas dan mekanisme transaksi chip
  masih harus diverifikasi. Belum simulasi penuh serangan/protokol kartu.
- Belum uji fisik EEPROM, latensi interrupt/I2C saat EEPROM write, reset coil,
  volume, kartu dicabut, power loss, atau anti-cloning. Belum upload.
- Masih perlu audit seluruh teks LCD (label hasil vs cek saldo), semua cancel,
  error recovery/provisioning, dan kecocokan lengkap dengan design.

## Perintah

Jalankan dari `firmware/smartdispenser_firmware`:

```powershell
& '.\scripts\test_ab.ps1'
& 'C:\Users\MSI\.platformio\penv\Scripts\pio.exe' run -e smartdispenser_a -e smartdispenser_b
```

Setelah implementasi firmware lengkap, buat goal audit kesesuaian terhadap
`DESIGN_NFC_PERSO_DISPENSER.md` sesuai permintaan pengguna. Perbedaan dilaporkan
kepada pengguna; jangan mengubah design hanya agar cocok dengan kode.
