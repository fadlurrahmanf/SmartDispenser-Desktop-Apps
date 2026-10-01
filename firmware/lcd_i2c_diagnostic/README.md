# Diagnosa I2C tahap 2

Program ini tidak mengakses relay maupun aktuator. Scanner hanya melakukan
START + alamat tulis + STOP pada seluruh rentang alamat I2C normal `0x08..0x77`;
tidak ada byte data atau perintah yang dikirim.

Setelah tiga kedipan awal, LED PC13 menampilkan:

1. Kelompok pertama adalah digit heksadesimal awal alamat.
2. Jeda, lalu kelompok kedua adalah digit heksadesimal akhir alamat.
3. Satu nyala selama dua detik dalam sebuah kelompok berarti digit `0`.
4. Dua kedipan berulang berarti tidak ada perangkat yang ACK pada rentang I2C
   normal.

Setiap kedipan menggunakan nyala 1 detik dan jeda mati 250 ms, lalu pola diulang.
