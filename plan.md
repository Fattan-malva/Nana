# Full Plan Pengembangan Nana — Universal Windows AI Agent

Repository: [Fattan-malva/Nana](https://github.com/Fattan-malva/Nana?utm_source=chatgpt.com)

Tujuan utama pengembangan ini adalah meningkatkan Nana dari asisten yang sebagian besar hanya membuka aplikasi atau melakukan pencarian menjadi AI agent yang mampu menjalankan perintah secara utuh, berinteraksi dengan berbagai aplikasi Windows, memahami kondisi aplikasi, menangani kegagalan, dan memverifikasi hasilnya.

Rencana ini mengikuti koreksi terbaru kamu:

- Tidak menggunakan Gemini.
- Mempertahankan sistem transkripsi suara dan TTS yang sudah ada di repository terbaru.
- Ollama tetap menjadi model untuk penalaran dan pengambilan keputusan.
- Screenshot hanya diambil ketika dibutuhkan, bukan pada setiap aksi.
- Screenshot disimpan di folder `temp` dan dibersihkan otomatis.
- Pengembangan harus berlaku untuk berbagai aplikasi Windows, bukan hanya browser atau YouTube.
- Memanfaatkan tools yang sudah ada sebelum menambah modul baru.
- Tahap ini hanya perencanaan. Tidak ada perubahan kode atau GitHub.

## 1. Target kemampuan Nana

[YTMDesktop](https://images.openai.com/static-rsc-4/2C266_x6OT6iTey_dK0VQnB1rRawVfLZPxJOAx7NWjsws5sqCMDGlnb0DazXpFW3fGh6WDDd-DGpShW8G4Wt6uRsgMMnwfSE6S5gxps8ESUg2nCT2pEPr6bwSqRyI3NLZI81VkorA239dERril4nTD5g50mKYu1z2xf7WJNghkg?purpose=inline)

Browser dan website

Membuka situs, mencari informasi, memilih hasil, mengklik tombol, mengisi formulir, berpindah tab, scroll, dan menyelesaikan alur website.

[Windows 11: tudo que se sabe sobre o novo sistema da Microsoft](https://images.openai.com/static-rsc-4/yfV683FSQmQ_aNYqpb5OwB9dla2WQwT6FPi2AlyoVXtKBMrd0J_gdqYO4ORyL-E-6PfzfrhPVMhMb6JeIE8rtRfPOxT1dp13I2wB1ZgqOX6C6xd4eMN3FX9-NpsSmdOePrnIW56XC0StRUmdsySdFRmiJ5sUXBGp-JC3C-bEYlo?purpose=inline)

File Explorer dan file

Membuka folder, menemukan file, menavigasi direktori, memilih item, serta melakukan operasi file yang diizinkan.

[Design exploration for improving experience for new users · Issue #115641 · microsoft/vscode · GitHub](https://images.openai.com/static-rsc-4/Ts2mdZhJKid8Q7cbbRwexlHdSYs69CYI9AJSOKPJGfp3cFD2X-AyYNozYoBvYpFTftUtiT_fME0gSO7rrFZ1HOLj4nn9J6RXPjhCkxFIDxug_U-Rf0bjEHZ6VorFem64EnzMfUZcnVk6iOJwT37AXskO6nnSA4e8DTLJfcbn1-s?purpose=inline)

Editor kode dan terminal

Membuka project, berpindah aplikasi, menjalankan perintah, membaca hasil terminal, mendeteksi error, dan melanjutkan tugas berdasarkan output yang sebenarnya.

[How to find the computer name of a Windows 11 device](https://images.openai.com/static-rsc-4/O0qgXJK2k2Ppu7pn-rYUj_OKj_VCYo1xluA-7PkvlEhC9SHvHrSwrugemPMo3pQRok4wRZLEKNCNhmO1b38BIsRIcMrPye-MAJYq-l6iqAz5hdX1MeEMCfFEr30bhBzTKEGdrwvh1PMiVKCHlNmXvV55Air4mKL0ApSsi8jLZbM?purpose=inline)

Aplikasi desktop dan Windows Settings

Menemukan kontrol, mengubah pengaturan yang diminta, mengisi input, menutup dialog, dan memeriksa hasil perubahan.

Contohnya, perintah “buka YouTube dan putar musik instrumental” tidak boleh dianggap selesai hanya karena halaman YouTube sudah terbuka atau judul musik sudah ditemukan. Nana harus berusaha menyelesaikan proses pemilihan dan pemutaran, kemudian memverifikasi statusnya.

## 2. Arsitektur sistem

Nana akan menggunakan satu alur kerja untuk semua aplikasi. Model AI merencanakan tugas, action engine menjalankan aksi, observation membaca kondisi aplikasi, dan verification memastikan hasilnya.

Input suara / teks

Pertahankan transkripsi yang sekarang

Ollama — Reasoning & Planning

Memahami maksud, menyusun langkah, memilih tools

Task Engine

Mengelola progres, langkah, timeout, retry, dan hasil

Interaction

Window, UI Automation, mouse, keyboard, shell

Observation

Status window dan kontrol; screenshot jika diperlukan

Verification & Recovery

Verifikasi tujuan, perbaiki kegagalan, atau laporkan kendala

Respons Nana

Menampilkan hasil dan menggunakan TTS yang sudah ada

### Siklus eksekusi utama

Nana harus menggunakan siklus berikut, bukan sekadar mengirim instruksi ke model lalu menjalankan satu tool.

1. Memahami tujuan pengguna.
2. Memeriksa kondisi aplikasi yang relevan.
3. Menentukan aksi berikutnya.
4. Memvalidasi izin dan argumen aksi.
5. Menjalankan aksi.
6. Memeriksa hasil aksi.
7. Jika gagal, memilih alternatif atau mencoba pemulihan yang aman.
8. Melanjutkan sampai tujuan tercapai, dibatalkan, atau benar-benar tidak bisa dilanjutkan.
9. Memberikan laporan sesuai hasil sebenarnya.

Setiap aksi mengembalikan hasil terstruktur, misalnya `success`, `failed`, `timeout`, atau `needs_confirmation`. Status `success` hanya berarti aksinya berhasil dijalankan; status tersebut belum tentu berarti tujuan akhir pengguna sudah tercapai.

## 3. Rencana modul dan struktur repository

Struktur ini adalah target arsitektur. Sebelum implementasi, kita audit file yang sudah ada agar modul baru tidak menduplikasi fungsi lama.

```
Nana/
├── app.py
├── services/
│   └── ollama.py
├── tools/
│   ├── registry.py
│   ├── runner.py
│   ├── desktop.py
│   ├── keyboard.py
│   ├── shell.py
│   ├── safety.py
│   ├── interaction.py       # bila diperlukan
│   ├── observation.py       # bila diperlukan
│   └── verification.py     # bila diperlukan
├── core/
│   ├── task_engine.py       # bila diperlukan
│   ├── task_state.py        # bila diperlukan
│   └── recovery.py          # bila diperlukan
├── config/
│   └── settings.py          # bila diperlukan
├── temp/
│   └── screenshots/
└── tests/
    ├── test_runner.py
    ├── test_interaction.py
    ├── test_observation.py
    ├── test_task_engine.py
    └── test_safety.py
```

| File atau modul      | Tanggung jawab                                                    |
| -------------------- | ----------------------------------------------------------------- |
| `app.py`             | Mengelola UI, input, alur percakapan, dan koneksi ke sistem tools |
| `services/ollama.py` | Komunikasi dengan model Ollama sesuai implementasi saat ini       |
| `tools/registry.py`  | Daftar tools dan skema argumennya                                 |
| `tools/runner.py`    | Validasi dan eksekusi tools                                       |
| `tools/desktop.py`   | Membuka aplikasi, mendeteksi window, dan operasi desktop          |
| `tools/keyboard.py`  | Mengetik teks dan shortcut keyboard                               |
| `tools/shell.py`     | Menjalankan perintah terminal yang diizinkan                      |
| `tools/safety.py`    | Validasi risiko, pembatasan, dan konfirmasi                       |
| `interaction.py`     | Interaksi elemen UI dan fallback mouse/keyboard                   |
| `observation.py`     | Memeriksa keadaan aplikasi dan screenshot on-demand               |
| `verification.py`    | Memastikan hasil aksi dan tujuan                                  |
| `task_engine.py`     | Mengelola rangkaian aksi dan progres tugas                        |
| `task_state.py`      | Menyimpan status tugas aktif dan langkah yang sudah selesai       |
| `recovery.py`        | Mengatur retry, alternatif aksi, dan pemulihan                    |
| `config/settings.py` | Mengelola timeout, batas langkah, dan kebijakan screenshot        |
| `tests/`             | Menguji kemampuan, regresi, dan keselamatan                       |

Prinsip implementasi: gunakan kembali `desktop.py`, `keyboard.py`, `runner.py`, `registry.py`, `shell.py`, dan `safety.py` terlebih dahulu. File baru hanya dibuat apabila tanggung jawabnya memang belum tersedia atau sudah terlalu kompleks untuk dipertahankan dalam modul lama.

## 4. Universal Interaction Engine

Engine ini menjadi kemampuan utama Nana untuk berinteraksi dengan aplikasi apa pun yang bisa diakses melalui Windows.

### A. Pengelolaan aplikasi dan window

- Membuka aplikasi, dokumen, dan URL.
- Mendeteksi proses dan window yang aktif.
- Memindahkan fokus ke aplikasi yang tepat.
- Menunggu window atau dialog siap sebelum melanjutkan.
- Mendeteksi pop-up yang menghalangi interaksi.
- Mengembalikan fokus ke aplikasi yang relevan setelah aksi lain.

### B. Interaksi dengan kontrol

- Menemukan tombol, input, menu, dropdown, checkbox, dan item berdasarkan informasi UI.
- Klik, double-click, mengetik, memilih, dan scroll.
- Menggunakan shortcut keyboard.
- Mengambil nilai atau status kontrol ketika tersedia.
- Menggunakan koordinat mouse hanya ketika kontrol tidak bisa diakses secara terstruktur.
- Menunggu perubahan kondisi dengan timeout, bukan menggunakan jeda panjang yang tidak perlu.

### C. Pilihan teknologi

| Teknologi                      | Kegunaan                                                           |
| ------------------------------ | ------------------------------------------------------------------ |
| `pywinauto` dengan backend UIA | Mengakses kontrol dan accessibility tree aplikasi Windows          |
| `pyautogui`                    | Interaksi mouse dan keyboard sebagai fallback                      |
| `psutil`                       | Memeriksa proses aplikasi                                          |
| `mss`                          | Mengambil screenshot saat dibutuhkan                               |
| OCR, misalnya PaddleOCR        | Membaca teks visual jika teks tidak tersedia melalui UI Automation |

Kita tidak harus memasang semua library sekaligus. Tahap audit menentukan mana yang belum tersedia dan benar-benar diperlukan.

Untuk browser, Nana dapat menggunakan accessibility tree atau integrasi browser jika sesuai. Untuk aplikasi desktop yang tidak menyediakan informasi kontrol dengan baik, Nana menggunakan interaksi keyboard/mouse dan, bila perlu, screenshot.

## 5. Screenshot on-demand dan pengelolaan folder temporary

Ini adalah ketentuan wajib, bukan fitur tambahan yang selalu aktif.

### Kapan screenshot boleh digunakan?

Utamakan data tanpa gambar

Periksa window, kontrol UI, teks, status aplikasi, dan hasil perintah terlebih dahulu.

Ambil screenshot hanya jika dibutuhkan

Misalnya, Nana tidak menemukan tombol melalui UI Automation, tidak memahami layout visual, atau membutuhkan observasi tambahan untuk memulihkan kegagalan.

Simpan di folder khusus

`temp/screenshots/` di dalam direktori project Nana atau lokasi yang ditentukan konfigurasi.

Hapus otomatis

Hapus file setelah analisis selesai, termasuk ketika terjadi exception. Saat startup, bersihkan screenshot lama yang tertinggal akibat aplikasi berhenti mendadak.

### Aturan pengelolaan file

1. Buat direktori temporary secara otomatis ketika screenshot pertama diperlukan.
2. Beri nama file unik untuk mencegah tabrakan antarproses.
3. Jangan membuat screenshot jika informasi yang dibutuhkan sudah tersedia dari sumber lain.
4. Hapus file menggunakan `try/finally` setelah pemrosesan selesai.
5. Bersihkan hanya file screenshot yang dikelola Nana, bukan seluruh isi folder `temp`.
6. Terapkan masa kedaluwarsa untuk file yang tertinggal setelah crash.
7. Jangan mengirim screenshot ke model atau layanan eksternal kecuali fitur tersebut memang dikonfigurasi dan diizinkan.

Dengan cara ini, screenshot tidak memenuhi penyimpanan dan tidak menjadi overhead pada setiap interaksi. Foldernya pun tidak harus berisi file secara permanen.

## 6. Task Engine: kemampuan menjalankan perintah sampai tuntas

Masalah utama Nana saat ini adalah beberapa perintah berhenti setelah membuka aplikasi atau menemukan hasil. Task Engine akan mengubah perilaku itu menjadi proses bertahap yang terkontrol.

Setiap tugas memiliki:

- `task_id`: identitas tugas.
- `goal`: tujuan pengguna.
- `plan`: langkah yang akan dikerjakan.
- `current_step`: langkah yang sedang berlangsung.
- `completed_steps`: langkah yang sudah terverifikasi.
- `last_result`: hasil aksi terakhir.
- `retry_count`: jumlah percobaan ulang.
- `status`: `planning`, `running`, `waiting`, `completed`, `failed`, atau `cancelled`.

### Contoh: memutar musik di YouTube

| Langkah | Aksi                       | Bukti keberhasilan                              |
| ------- | -------------------------- | ----------------------------------------------- |
| 1       | Buka atau fokuskan browser | Window browser tersedia                         |
| 2       | Buka YouTube               | Halaman YouTube terdeteksi                      |
| 3       | Cari musik instrumental    | Hasil pencarian tersedia                        |
| 4       | Pilih hasil yang sesuai    | Halaman atau pemutar lagu terbuka               |
| 5       | Mulai pemutaran            | Status pemutaran terdeteksi sejauh memungkinkan |
| 6       | Atur volume jika diminta   | Nilai atau indikator volume diperiksa           |
| 7       | Laporkan hasil             | Respons sesuai hasil verifikasi                 |

Jika langkah keempat gagal, Nana tidak boleh langsung mengulang seluruh tugas dari awal. Nana harus memeriksa keadaan saat ini, menentukan penyebab, lalu melanjutkan dari langkah yang relevan.

### Batas dan kontrol eksekusi

- Pertahankan konfigurasi batas langkah yang ada, termasuk `TOOLS_MAX_STEPS`, jika masih sesuai.
- Jangan mengizinkan loop aksi tanpa batas.
- Gunakan timeout per aksi dan batas total durasi tugas.
- Jika langkah baru diperlukan, engine dapat meminta model merencanakan ulang dalam batas yang ditentukan.
- Berikan kesempatan kepada pengguna untuk menghentikan tugas.
- Jika sebuah aksi berisiko, jangan melanjutkan tanpa konfirmasi yang sesuai.

Batas langkah adalah pengaman, bukan alasan bagi Nana untuk berhenti tanpa menjelaskan status tugas.

## 7. Observation, Verification, dan Recovery

Ketiga kemampuan ini harus dibedakan agar Nana tidak salah mengklaim keberhasilan.

Observation — Apa yang sedang terjadi?

Mengumpulkan informasi dari aplikasi aktif, window, kontrol UI, output terminal, atau screenshot ketika diperlukan.

Verification — Apakah aksi berhasil?

Memeriksa bukti spesifik dari aksi. Contohnya, aplikasi benar-benar terbuka, file benar-benar dibuat, atau status pemutar menunjukkan bahwa pemutaran telah dimulai.

Recovery — Apa yang dilakukan jika gagal?

Mencoba alternatif yang masuk akal, mengembalikan fokus, memeriksa dialog, atau menggunakan screenshot jika metode observasi biasa tidak cukup.

Urutan pemulihan yang disarankan:

1. Periksa hasil aksi dan pesan error.
2. Periksa apakah aplikasi masih aktif dan merespons.
3. Perbaiki fokus, tunggu, atau cari ulang kontrol yang tepat.
4. Coba metode interaksi alternatif.
5. Gunakan screenshot/OCR bila informasi visual memang diperlukan.
6. Hentikan percobaan jika batas retry tercapai atau risiko meningkat.
7. Beri tahu pengguna apa yang berhasil dan apa yang gagal.

Tidak semua tindakan memiliki bukti keberhasilan yang sempurna. Dalam kasus seperti itu, Nana harus mengatakan bahwa hasil belum dapat dipastikan, bukan mengklaim keberhasilan.

## 8. AI reasoning dan system prompt

Ollama tetap menjadi pusat penalaran. Yang diperbaiki bukan sekadar prompt agar lebih panjang, melainkan kontrak antara model dan tools.

### Perilaku yang diharapkan

- Memahami tujuan akhir, bukan hanya kata kerja pertama.
- Memecah permintaan menjadi langkah yang logis.
- Memilih tool yang sesuai dengan kondisi aplikasi.
- Menggunakan hasil tool sebagai konteks untuk aksi selanjutnya.
- Menghindari mengulang aksi yang sudah berhasil.
- Tidak mengarang hasil observasi.
- Tidak menyatakan tugas selesai sebelum ada bukti yang memadai.
- Bertanya jika instruksi ambigu secara material.
- Meminta konfirmasi untuk tindakan berisiko atau tidak dapat dibatalkan.

### Format hasil tool

Secara konseptual, setiap tool mengembalikan struktur seragam seperti:

```
{
  "ok": true,
  "status": "success",
  "action": "click",
  "result": "Tombol ditemukan dan diklik",
  "evidence": "Kontrol UI berhasil diaktifkan",
  "error": null
}
```

Format final harus disesuaikan dengan struktur kode saat ini. Contoh ini hanya menunjukkan desain, bukan menyatakan format tersebut sudah diterapkan di repository.

Penting: model boleh menentukan strategi, tetapi kode Python tetap bertanggung jawab atas validasi argumen, izin aksi, timeout, eksekusi, dan pembersihan file sementara.

## 9. Keamanan dan kontrol pengguna

Nana harus tetap berguna tanpa memperoleh kebebasan menjalankan semua perintah secara sembarangan.

- Pertahankan dan tingkatkan `tools/safety.py`.
- Validasi nama tool dan argumen sebelum dieksekusi.
- Terapkan allowlist atau aturan khusus untuk operasi shell yang sensitif.
- Minta konfirmasi sebelum menghapus banyak file, mengirim pesan, melakukan transaksi, atau menjalankan tindakan berisiko lainnya.
- Jangan mengeksekusi instruksi berbahaya yang ditemukan dalam halaman web atau dokumen hanya karena konten tersebut dibaca oleh Nana.
- Jangan membocorkan isi `.env`, kredensial, atau data sensitif dalam log.
- Sediakan mekanisme pembatalan tugas.
- Pastikan screenshot dan hasil observasi tidak disimpan lebih lama dari yang diperlukan.

Perintah seperti membuka aplikasi atau mencari informasi bisa berjalan langsung. Tindakan yang memiliki dampak penting harus melewati pemeriksaan keamanan yang sesuai.

## 10. Tahapan implementasi

Implementasi dilakukan bertahap agar mudah diuji dan tidak merusak fungsi yang sudah berjalan.

01

Audit repository terbaru

Periksa `app.py`, seluruh modul tools, konfigurasi, transkripsi, TTS, dan system prompt. Petakan fungsi yang tersedia, kekurangannya, dan dependensi yang sudah terpasang.

Prasyarat

02

Perkuat eksekusi tools

Perbaiki format hasil, validasi argumen, penanganan error, timeout, dan penggunaan hasil aksi pada langkah berikutnya.

03

Bangun siklus task

Tambahkan pengelolaan progres, rangkaian aksi, pembatalan, retry terbatas, dan kondisi penyelesaian tugas.

04

Tingkatkan interaksi universal

Tingkatkan deteksi window, pencarian elemen UI, klik, input, scroll, keyboard, dan fallback untuk aplikasi yang tidak menyediakan kontrol terstruktur.

05

Tambahkan screenshot on-demand

Buat lifecycle file sementara, integrasi observation, OCR jika dibutuhkan, serta pembersihan otomatis.

06

Implementasikan verification dan recovery

Validasi hasil aksi, pulihkan kegagalan secara aman, dan pastikan status tugas tidak hanya didasarkan pada keberhasilan pemanggilan tool.

07

Pengujian dan stabilisasi

Uji lintas aplikasi, perbaiki regresi, evaluasi waktu respons, dan pastikan fitur suara serta UI yang sudah ada tetap berfungsi.

## 11. Rencana pengujian

Pengujian harus membuktikan bahwa Nana mampu menjalankan tugas, bukan sekadar menghasilkan respons yang terlihat benar.

| Skenario                       | Kriteria lulus                                                        |
| ------------------------------ | --------------------------------------------------------------------- |
| Buka aplikasi                  | Aplikasi yang diminta benar-benar terbuka                             |
| Buka website dan putar musik   | Pencarian, pemilihan, dan pemutaran dilakukan; status akhir diperiksa |
| Navigasi File Explorer         | Folder atau file yang diminta ditemukan                               |
| Mengisi formulir               | Input terisi sesuai instruksi dan hasilnya diperiksa                  |
| Interaksi dengan editor kode   | File atau perintah yang diminta diproses dan hasilnya diperiksa       |
| Aplikasi tidak merespons       | Nana melakukan pemulihan terbatas atau melaporkan kegagalan           |
| Elemen tidak terdeteksi        | Screenshot hanya diambil jika diperlukan                              |
| Screenshot selesai dianalisis  | File sementara dihapus                                                |
| Nana ditutup mendadak          | Screenshot lama dibersihkan saat startup berikutnya                   |
| Perintah berisiko              | Pemeriksaan keamanan dan konfirmasi dijalankan                        |
| Perintah dibatalkan            | Eksekusi berhenti dengan status yang benar                            |
| Tugas tidak dapat diverifikasi | Nana tidak mengklaim bahwa tugas sudah selesai                        |

Pengujian perlu mencakup kondisi sukses, kegagalan, timeout, dialog tambahan, serta aplikasi yang hanya menyediakan dukungan UI Automation terbatas.

## 12. Kriteria selesai proyek

Pengembangan dianggap berhasil jika:

- Sistem transkripsi suara dan TTS yang ada tetap digunakan.
- Ollama tetap menjadi model penalaran.
- Nana mampu menjalankan perintah multi-langkah.
- Nana dapat berinteraksi dengan berbagai aplikasi, bukan hanya membuka aplikasi.
- Nana menggunakan hasil aksi sebelumnya untuk menentukan langkah berikutnya.
- Screenshot hanya digunakan ketika diperlukan.
- Screenshot disimpan di `temp/screenshots/` dan dibersihkan otomatis.
- Nana dapat mendeteksi kegagalan dan mencoba pemulihan yang aman.
- Status selesai didasarkan pada bukti yang memadai.
- Kontrol keamanan, pembatalan, dan konfirmasi tetap berfungsi.
- Fitur lama tidak rusak akibat perubahan.

## 13. Keputusan teknis yang ditetapkan

| Aspek                | Keputusan                                                  |
| -------------------- | ---------------------------------------------------------- |
| AI reasoning         | Ollama, mengikuti konfigurasi repository                   |
| Speech-to-text       | Pertahankan implementasi terbaru                           |
| Text-to-speech       | Pertahankan implementasi terbaru                           |
| Desktop interaction  | Gunakan kembali tools yang tersedia, lalu perluas          |
| Observasi            | UI Automation lebih dahulu, screenshot sebagai fallback    |
| Screenshot storage   | Folder `temp/screenshots/`                                 |
| Pembersihan          | Setelah analisis dan saat startup untuk file tertinggal    |
| Eksekusi tugas       | Multi-langkah dengan status, timeout, dan batas retry      |
| Verifikasi           | Memeriksa hasil nyata, bukan hanya status pemanggilan tool |
| Keamanan             | Validasi, pembatasan, konfirmasi, dan pembatalan           |
| Perubahan repository | Dilakukan setelah rencana dan audit disetujui              |

Rekomendasi saya: mulai dari audit `runner.py`, `registry.py`, `desktop.py`, `keyboard.py`, `shell.py`, `safety.py`, dan alur eksekusi di `app.py`. Setelah itu, perbaiki fondasi eksekusi multi-langkah sebelum menambahkan sistem screenshot dan OCR. Dengan urutan ini, Nana akan memperoleh kemampuan interaksi yang lebih baik tanpa menjadikan screenshot sebagai solusi untuk semua masalah.

Rencana ini belum mengubah GitHub. Implementasi nantinya harus didasarkan pada kode aktual di branch terbaru, mempertahankan fungsi yang sudah berjalan, dan menguji setiap tahap sebelum melanjutkan ke tahap berikutnya.