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
| Browser | Playwright + CDP attach/takeover + UI Automation fallback |
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
    ├── browser.py          # Playwright + UIA untuk tab/klik/cari/play
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

* Profil browser Nana: `%LOCALAPPDATA%\Nana\browser`
* Cache mapping aplikasi: `%LOCALAPPDATA%\Nana\apps_map.json`
* Rekaman sementara STT: `temp.wav` di folder kerja (dihapus saat keluar)

## Instalasi

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
# isi OLLAMA_API_KEY di .env
python app.py
```

Playwright memakai Edge/Brave/Chrome yang sudah terpasang. Jika tidak ada
browser Chromium sama sekali, jalankan `python -m playwright install chromium`.

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

* `NANA_BROWSER` — `brave` / `msedge` / `chrome` (kosong = deteksi otomatis)
* `NANA_BROWSER_PROFILE` — folder profil (default `%LOCALAPPDATA%\Nana\browser`)
* `NANA_CDP_PORTS` — port CDP browser user (default `9222,9223,9333`; `0` = nonaktif)
* `NANA_BROWSER_HEADLESS` — `true` untuk browser tak terlihat
* `NANA_BROWSER_TIMEOUT` — timeout operasi browser dalam detik (default 20)

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

Nana memakai Playwright dengan browser Chromium yang benar-benar terpasang
(Brave/Edge/Chrome), bukan browser tiruan.

* Buka halaman: `browser_open`
* Cari lewat kolom pencarian situs (bukan URL `?q=`): `browser_search`
* Putar musik/video sampai terverifikasi: `browser_play(service, query)`
* Lihat kondisi nyata halaman: `browser_state`, `browser_find`
* Aksi: `browser_click`, `browser_fill`, `browser_press`, `browser_scroll`, `browser_wait`
* Tab: `browser_tabs`, `browser_switch_tab`, `browser_close_tab`
* Ambil alih browser user yang sedang terbuka: `browser_attach`

Aturan tab:

* `browser_tabs` memisahkan **Browser Nana** / **Browser user (CDP penuh)**
  dan **Browser lain (UIA)**.
* Tab hanya ditutup/dipilih kalau judul/URL-nya cocok. Kalau tidak ada yang
  cocok, Nana melaporkan daftar tab yang tersedia, bukan menutup tab sembarangan.
* Untuk tab di browser user yang belum terhubung penuh, isi `browser: "user"`.
* URL mesin pencari (`?q=`, `/results?search_query=`, dll.) diblokir; Nana
  harus mengetik di kolom pencarian asli situs.

### Mengambil alih browser user

Nana bisa mengendalikan browser yang sedang user pakai, lengkap dengan tab
dan login yang sudah ada:

1. `browser_attach` tanpa restart mencoba attach lewat CDP. Ini langsung
   berhasil kalau browser user sudah dibuka dengan port debug.
2. Kalau belum, Nana menjelaskan bahwa browser perlu ditutup dan dibuka ulang
   sekali. Setelah user setuju, panggil:
   `browser_attach(browser="brave", restart=true, confirm=true)`.
3. Nana menutup window browser target secara graceful, membukanya lagi dengan
   `--remote-debugging-port` (port kosong dari `NANA_CDP_PORTS`) dan
   `--restore-last-session`, lalu attach.
4. Setelah terhubung, semua tool browser memakai browser user itu. Tab
   incognito tidak bisa dipulihkan.

Profil Nana tetap tersedia untuk tugas yang tidak boleh mengganggu browser
user. Sekali saja, login ke Spotify/YouTube di jendela browser Nana supaya
pemutaran penuh bisa berjalan tanpa mengambil alih browser user.

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
