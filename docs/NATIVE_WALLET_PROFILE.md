# Kandidat profil native wallet DESFire

Status: detail implementasi kandidat, **belum dikunci untuk kartu pengguna** dan
belum diaktifkan di runtime. Tidak mengubah ketentuan saldo/menu/pencairan design.
Identifikasi serta validasi kemampuan chip tetap diperlukan sebelum provisioning.

## Data dan kewenangan

Slot key aplikasi kandidat: 0 pengelola ACL/provisioning B, 2 pemakaian A,
3 issuer B. Nomor slot bukan nilai secret. A tidak menerima key 0/3 atau root
yang dapat menghasilkan key tersebut. Autentikasi master B adalah aplikasi kartu
terpisah, bukan slot tambahan yang dianggap sebagai tipe kartu ketiga.

| File logis | Tipe | Batas/ukuran | Rights kandidat | Fungsi |
|---|---|---|---|---|
| Tersedia | Value | 0–100 | 0x3022 | Debit A; LimitedCredit A untuk refund normal; Credit hanya B |
| Total belum terpakai | Value | 0–100 | 0x302F | Available + semua held/beku; dikurangi saat pemakaian ditagih; Credit hanya B |
| Sisa counter revisi | Value | 0–2147483647 | 0x302F | Awal maksimum; Debit 1 setiap perubahan, mencegah revisi kembali dengan key A |
| Izin aktif operator | Backup data | 1 byte | 0x3023 | Dibaca A/B, ditulis hanya B |
| Envelope dompet | Backup data | 179 byte | 0x3022 | Wallet kanonis terenkripsi; wajib cocok dengan nilai native |

Semua file memakai mode enciphered. Empat nibble rights berurutan RW/Change/Read/
Write; `F` berarti akses dilarang dan `E` (free access) tidak diizinkan dalam profil.
Nomor file harus unik dan ditentukan dalam provisioning; tidak diasumsikan dari UID.
Pengkodean/semantik command mengacu pada
[implementasi DESFire libfreefare](https://raw.githubusercontent.com/nfc-tools/libfreefare/master/libfreefare/mifare_desfire.c).

## Perubahan atomik

- Sebelum mutasi, rekonsiliasi operasi lama dilakukan oleh lapisan aplikasi.
  Transaksi baru diawali AbortTransaction eksplisit untuk membuang staging lama.
- Baca ulang nilai native dan cocokkan dengan wallet awal, termasuk revisi/izin.
- Reserve men-debit tersedia; checkpoint men-debit total sesuai tambahan pemakaian.
- Settle mengembalikan sisa cadangan melalui LimitedCredit, bukan Credit issuer.
  Freeze atau settle tanpa refund menutup allowance LimitedCredit dengan nilai 0.
- Top-up meng-credit tersedia dan total. Release beku hanya meng-credit tersedia;
  total belum terpakai tidak bertambah karena saldo beku sudah termasuk di dalamnya.
- Counter revisi, nilai native, perubahan izin jika ada, dan envelope dipersiapkan
  sebelum satu CommitTransaction. ACK saja bukan sukses: baca ulang semuanya.
- Gagal/ACK hilang tidak diulang sebagai kredit baru; hasil uncertain diselesaikan
  memakai identitas transaksi pada jurnal dan wallet.

`ab_native_wallet.h` memeriksa transisi dengan aturan `ab_wallet.h` sebelum
menghasilkan operasi native. Profil ini menolak perubahan saat counter revisi
habis; tidak melakukan wrap/reset otomatis. Sesi berganti membatalkan staging lokal.

## Yang masih harus dipastikan

- Kartu nyata mendukung tipe file, transaksi gabungan dan autentikasi kandidat.
- Perilaku LimitedCredit(0), batas allowance setelah Debit/Commit, dan pencairan
  setelah freeze harus diuji pada chip yang dipilih. Jangan mengaktifkan profil
  bila perilakunya berbeda; laporkan penyimpangan kepada pengguna.
- Pencegahan rollback bukan klaim dari envelope AES-GCM saja. Uji mismatch native
  counter/saldo/izin, serta serangan memakai kewenangan A tanpa key issuer.
- Nomor file, instalasi key, recovery provisioning terputus, derivasi root terpisah,
  master enrollment dan generator challenge belum terhubung penuh ke runtime.
- Model ancaman tidak menganggap MCU A yang dikuasai penyerang dapat membuktikan
  jumlah air fisik secara tepercaya. Tidak ada klaim anti-tamper MCU atau pengukuran
  metrologi dari validasi data kartu semata.
