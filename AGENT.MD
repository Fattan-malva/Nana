# Nana — Windows Voice AI Agent

Nana adalah asisten suara desktop untuk Windows: mendengarkan wake word,
mengubah suara menjadi teks, meminta model Ollama, dan menjalankan tool
aplikasi, terminal, UI Automation, serta browser atas nama user.

## Arsitektur

| Bagian | Teknologi |
| --- | --- |
| UI desktop | `pywebview` (HTML/CSS/JS inline di `app.py`) |
| Audio input | `pyaudio` + VAD sederhana |
| Speech-to-text | `SpeechRecognition` (`recognize_google`, bahasa Indonesia) |
| Reasoning | Ollama OpenAI-compatible API (`OLLAMA_URL`) |
| Aksi desktop | `ctypes`, `pywinauto`, `psutil` |
| Browser | UI Automation + keyboard pada browser user |
| Web realtime | Ollama Web Search API + fallback DuckDuckGo |

Tidak ada server FastAPI, template, atau static asset terpisah. Seluruh UI
berjalan di dalam jendela `pywebview` yang dibuat oleh `app.py`.

## Alur

1. `app.py` memuat `.env`, membuat jendela, lalu menjalankan loop audio.
2. Loop menunggu wake word (`WAKE_WORD`), lalu merekam sampai ada jeda.
3. Rekaman ditranskripsi menjadi teks.
4. Jika pertanyaan butuh info terbaru, `tools/web.py` menyuntikkan konteks
   web ke system prompt.
5. Model membalas dengan teks biasa atau satu aksi JSON:
   `{"tool": "browser_play", "args": {"service": "youtube", "query": "..."}}`.
6. `tools/runner.py` memvalidasi dan menjalankan aksi, lalu hasilnya
   dikirim kembali ke model. Loop berlanjut sampai selesai atau
   `TOOLS_MAX_STEPS` tercapai (maksimum 25).
7. Jawaban akhir ditampilkan di jendela Nana.

## Struktur Folder

```text
Nana/
├── app.py                  # UI pywebview, audio loop, agent loop
├── requirements.txt        # dependency runtime langsung
├── AGENT.MD                # dokumen ini
├── plan.md                 # roadmap pengembangan
├── .env                    # konfigurasi lokal (tidak di-commit)
├── .env.example            # contoh konfigurasi
├── core/
│   ├── __init__.py
│   └── task_engine.py      # state task multi-step + flag pembatalan
├── services/
│   ├── __init__.py
│   └── ollama.py           # web search/fetch API Ollama + fallback DDG
└── tools/
    ├── __init__.py
    ├── browser.py          # UI Automation untuk tab/klik/cari/play
    ├── desktop.py          # app, window, folder, terminal, volume
    ├── interaction.py      # klik/ketik kontrol UIA, mouse
    ├── keyboard.py         # input keyboard via ctypes
    ├── observation.py      # daftar window dan control tree
    ├── registry.py         # definisi tool + system prompt
    ├── runner.py           # dispatcher tool
    ├── safety.py           # allowlist, larangan hapus, validasi path
    ├── shell.py            # run_command dengan allowlist
    ├── verification.py     # verifikasi window/file/proses
    └── web.py              # tool web + deteksi pertanyaan realtime
```

Cache runtime tidak disimpan di folder source:

* Cache mapping aplikasi: `%LOCALAPPDATA%\Nana\apps_map.json`
* Rekaman sementara STT: `temp.wav` di folder kerja (dihapus saat keluar)

Nana tidak menyimpan profil browser sendiri. Semua tugas browser memakai
profil, login, dan history browser milik user.

## Instalasi

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
# isi OLLAMA_API_KEY di .env
python app.py
```

Kontrol browser memakai UI Automation + keyboard pada window browser user. Tidak
ada dependency browser automation tambahan. Pastikan Brave/Chrome/Edge/Firefox
sudah terpasang dan pernah dipakai user.

## Environment Variables

Wajib:

```env
OLLAMA_URL=https://ollama.com/v1/chat/completions
OLLAMA_MODEL=gemma4:31b-cloud
OLLAMA_API_KEY=...
```

Agent dan tool:

* `TOOLS_ENABLED` — `false` untuk mematikan semua aksi komputer
* `TOOLS_MAX_STEPS` — batas langkah tool (default 8, maksimum 25)
* `TOOLS_STRICT_VSCODE` — `true` untuk melarang ketik langsung ke VS Code
* `TOOLS_ALLOWED_COMMANDS` — allowlist executable `run_command` (dipisah koma)
* `TOOLS_CMD_TIMEOUT` — timeout perintah terminal dalam detik (default 20)
* `WAKE_WORD` — kata bangun (default `NANA`)
* `SLEEP_AFTER_SECONDS` — tidur setelah idle (0 = nonaktif)

Browser:

* `NANA_BROWSER` — opsional: `brave` / `chrome` / `edge` / `firefox` / `vivaldi` / `opera`.
  Kosong = browser default Windows yang sedang dipakai user.

Tidak ada profil browser Nana, port debug, atau mode headless: browser selalu
browser user yang tampil dengan profil/history asli.

Web realtime:

* `OLLAMA_HOST` — host API native Ollama (default `https://ollama.com`)
* `OLLAMA_WEB_TIMEOUT` — timeout web search/fetch (default 35 detik)
* `WEB_AUTO_SEARCH` — `true` untuk konteks web otomatis
* `WEB_CACHE_SECONDS` — masa simpan cache web (default 600)

## Tool

Sistem & desktop:

`open_app`, `open_terminal`, `focus_window`, `list_windows`, `type_text`,
`press_key`, `run_command`, `open_folder`, `open_in_vscode`, `wait`,
`volume_up`, `volume_down`, `volume_mute`, `open_url`, `close_tab`,
`close_browser`, `cancel_task`

Web:

`web_search`, `web_fetch`

Browser:

`browser_open`, `browser_tabs`, `browser_switch_tab`, `browser_close_tab`,
`browser_attach`, `browser_state`, `browser_find`, `browser_click`,
`browser_fill`, `browser_press`, `browser_scroll`, `browser_wait`,
`browser_search`, `browser_play`

UI Automation & verifikasi:

`observe_active`, `ui_controls`, `ui_click`, `ui_type`, `ui_scroll`,
`mouse_click`, `wait_for_control`, `dismiss_dialog`, `verify_window`,
`verify_file`, `verify_process`

## Browser Automation

Nana memakai browser milik user, lengkap dengan profil, login, dan history.
Tidak ada browser/profil terpisah untuk Nana.

Mode kontrol: UI Automation pada window browser user + keyboard. Nana memakai
pohon aksesibilitas Windows untuk membaca halaman, tab, tombol, dan link.
Tidak perlu restart browser dan tidak mengubah profil.

Saat belum ada browser terbuka, Nana membuka browser default Windows (atau
browser yang disebut user, mis. Brave) dengan profil normal user. Tugas browser
selalu menambah tab baru di browser itu.

* Buka halaman: `browser_open`
* Cari lewat kolom pencarian situs (bukan URL `?q=`): `browser_search`
* Putar musik/video sampai terverifikasi: `browser_play(service, query)`
* Lihat kondisi nyata halaman: `browser_state`, `browser_find`
* Aksi: `browser_click`, `browser_fill`, `browser_press`, `browser_scroll`, `browser_wait`
* Tab: `browser_tabs`, `browser_switch_tab`, `browser_close_tab`
* Pastikan browser user aktif: `browser_attach`

Aturan tab:

* `browser_tabs` menampilkan tab browser user yang benar-benar terbaca. Tidak ada
  browser Nana terpisah.
* Tab hanya ditutup/dipilih kalau judulnya cocok. Judul wajib untuk menutup tab;
  kalau tidak ada yang cocok, Nana melaporkan daftar tab yang tersedia, bukan
  menutup tab sembarangan.
* URL mesin pencari (`?q=`, `/results?search_query=`, dll.) diblokir; Nana
  harus mengetik di kolom pencarian asli situs.

### Memilih browser

Kalau user menyebut browser tertentu, isi `browser` pada tool, misalnya:

```json
{"tool":"browser_open","args":{"url":"https://www.youtube.com","browser":"brave"}}
```

Kalau tidak disebut, Nana memakai browser default Windows yang sedang terbuka.
Browser yang sudah terbuka tidak ditutup, tidak di-restart, dan tidak diganti
profilnya.

## Realtime Web

`web_search` dan `web_fetch` memakai Ollama Web Search API (butuh
`OLLAMA_API_KEY`). Kalau API tidak tersedia, Nana memakai DuckDuckGo HTML
sebagai cadangan. Untuk pertanyaan yang butuh info terkini, konteks web
disuntikkan otomatis ke system prompt (lihat `WEB_AUTO_SEARCH`).

## Keamanan

* Nana tidak boleh menghapus file, folder, atau data.
* Perintah terminal harus executable yang ada di allowlist, tanpa operator
  shell berbahaya, dan tanpa pola aksi hapus.
* Path user divalidasi sebelum dibuka.
* Tab browser tidak pernah ditutup berdasarkan tebakan.
