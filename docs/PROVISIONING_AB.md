# Provisioning A/B — prosedur servis dan batas saat ini

Status: implementasi dan simulasi lokal; belum dijalankan pada board pengguna.
Dokumen ini tidak memuat key, UID, atau identifier produksi.

## Prasyarat

- Board tidak tersambung PLN; prosedur isolasi wajib dipastikan sebelum debugger/UART.
- Master dipilih satu kartu; B didaftarkan lebih dahulu. A memerlukan identitas
  master terdaftar melalui provisioning, bukan penempelan master saat dispensing.
- A1, A2, B mempunyai device ID berbeda. System dan versi key konsisten.
- Root envelope dan debit yang sama dipasang pada A/B; issuer, admin dan master
  hanya pada B. Root random berbeda per device. Root bukan hasil hash UID saja.
- Paket credential disimpan di luar repository dengan ACL Windows terbatas.
  Jangan menampilkan paket/key pada terminal, LCD, log atau lampiran laporan.

## Jalur servis yang tersedia

1. Siapkan JSON credential sesuai `scripts/encode_provisioning.cjs` di direktori
   privat. `scripts/provisioning_bundle.cjs` sekarang dapat membuat bundle tiga
   device dari plan non-secret berisi system/version/epoch/application dan
   devices.A1/A2/B. Generator memakai CSPRNG Node, memisahkan root khusus B dan
   random tiap device. CLI: `node scripts/provisioning_bundle.cjs INPUT OUTPUT`;
   kedua path harus di luar repository dan output belum ada. Jalankan hanya
   saat operator benar-benar siap membuat credential produksi.
2. Jalankan encoder dengan path input dan output absolut di luar repository.
   Output 160 byte; file yang sudah ada tidak ditimpa. Jangan memasukkan isi key
   ke argumen command line.
3. Image servis memakai `SMARTDISPENSER_PROVISIONING_SERVICE=1`. Penerima UART
   menerima prefix ASCII `SDPV1` diikuti record 160 byte. UART memakai 115200;
   paket lengkap harus selesai dalam batas waktu receiver. Ini kanal servis
   tepercaya lokal, bukan protokol enkripsi jaringan. Pengirim tersedia di
   `scripts/service_ab.ps1`; pemilihan image servis dalam paket rilis masih
   harus disiapkan sebelum pengujian pengguna.
4. Image servis tidak menjalankan menu, NFC, atau dispensing. Pada profil A,
   reset relay boot tetap berjalan. Hanya status numerik yang dilaporkan UART.
5. Setelah hasil provisioning diverifikasi, gunakan image normal profil device.
   Image normal tidak menerima command provisioning UART. Konfigurasi invalid
   menampilkan setup, bukan menyalakan aktuator untuk transaksi.

## Pendaftaran master dan identitas untuk A

Provisioning awal B dapat memakai master kosong. Operator menempel kartu kosong
dan menahan P1+P3 selama 10 detik; registry menyimpan intent sebelum pemasangan
kunci master. Setelah autentikasi/readback berhasil, pendaftaran di-commit.
Identitas master untuk paket A harus berasal dari pendaftaran B yang sudah
diverifikasi. Pada image servis B, kirim satu byte ASCII `?` ketika tidak sedang
mengirim paket provisioning. Respons JSON `SDAB-MASTER-1` memuat device, system,
version, registered=true dan UID master. Simpan respons ke file privat, bukan
log umum. A menolak query ini; image normal tidak menangani query tersebut.
Jangan memakai UID pelanggan contoh sebagai pengganti master atau menampilkannya
di LCD. Registry pending, konfigurasi tidak valid, atau identitas yang tidak
cocok menghasilkan `MASTER EXPORT UNAVAILABLE`, tanpa UID.

Bundle awal berstatus `B_ENROLLMENT_REQUIRED`; konfigurasi A belum dapat
dienkode karena master kosong. Fungsi `bindMaster` menerima laporan servis
`SDAB-MASTER-1` dengan registered=true, UID empat byte, device B, system dan
version yang cocok; hasilnya `A_PACKAGES_READY`. Konfigurasi awal B tidak
berubah. Laporan ini metadata dari kanal servis tepercaya, bukan tanda tangan
kriptografis. Jangan mengedit status bundle manual untuk melewati pendaftaran B.

## Pengemasan dan pengiriman dari komputer

- `node scripts/package_provisioning.cjs --b BUNDLE NEW_DIRECTORY` menyiapkan
  B.provisioning.bin sebelum pendaftaran master.
- `node scripts/package_provisioning.cjs --a BUNDLE MASTER_REPORT NEW_DIRECTORY`
  menyiapkan A1/A2.provisioning.bin setelah laporan master B cocok.
- Semua input dan direktori output harus privat di luar repository; direktori
  output harus belum ada. Marker PACKAGE_COMPLETE.json ditulis terakhir dengan
  ukuran/hash berkas. Direktori parsial tidak boleh digunakan. ACL Windows
  tetap tanggung jawab operator; mode file POSIX bukan jaminan ACL Windows.
- `service_ab.ps1` memerlukan Mode (Provision/ExportMaster), Port COM eksplisit,
  Role, Device dan System. Provision memakai InputFile; ExportMaster memakai
  OutputFile yang belum ada. Tanpa `-Execute`, hanya validasi lokal, tidak membuka
  port. Eksekusi memerlukan `-Execute -LowVoltageConfirmed` dan konfirmasi aksi.
- Script tidak mencari port otomatis, mengaktifkan DTR/RTS, mereset, mem-flash,
  atau mengirim ulang. Satu timeout/hasil ambigu harus diperiksa sebelum retry.
  Isi respons/master/key tidak dicetak ke terminal. Export menyimpan file privat.
- ST-Link saja belum tentu menyediakan UART. Jalur servis ini membutuhkan UART
  3,3 V ke pin debug yang ditetapkan; jangan menyamakan koneksi ST-Link dengan
  bukti UART sudah tersedia. Jangan mengubah wiring tanpa pemeriksaan pengguna.

Test fixture Node untuk pengemasan lulus. Script PowerShell sudah diperiksa
sintaks dan mode validasi tanpa port; pengiriman/response UART fisik belum diuji.

## Tidak ada penghapusan otomatis

Retry konfigurasi identik boleh dilakukan. Jurnal existing tidak direset dan
counter tidak kembali nol. Konfigurasi committed berbeda/rusak, counter rusak,
atau jurnal legacy/parsial yang tidak valid ditolak. Putus tulis konfigurasi
awal dapat dilanjutkan dengan paket identik; ini bukan jaminan semua kerusakan
EEPROM dapat dipulihkan otomatis.

Jika board berisi data firmware lama, inspeksi dahulu. Penghapusan/migrasi
memerlukan keputusan servis terpisah dan backup yang aman; flashing firmware
saja bukan izin menghapus saldo, master, jurnal, atau menggunakan ulang nonce.

## Bukti pengujian yang masih diperlukan

- Provisioning fisik A1/A2/B dan kesesuaian paket antar-device.
- Pendaftaran master B, ekspor identitas servis, lalu provisioning A.
- Ketahanan terhadap putus listrik di konfigurasi, counter dan jurnal aktual.
- Verifikasi MCU readout protection/penyimpanan key tanpa mengklaim EEPROM CRC
  sebagai proteksi terhadap pembacaan atau modifikasi oleh penyerang.
