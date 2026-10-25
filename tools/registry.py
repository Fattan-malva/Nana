"""Daftar tool dan prompt sistem untuk LLM."""

import time

TOOLS = {
    # --- aplikasi & sistem -------------------------------------------------
    "open_app": {
        "args": {"name": "string"},
        "desc": "Buka aplikasi Windows: vscode, notepad, explorer, calc, chrome, edge, terminal, cmd, dll.",
    },
    "open_terminal": {
        "args": {"target": "string"},
        "desc": "Buka terminal. target='vscode' membuka terminal di dalam VS Code.",
    },
    "focus_window": {
        "args": {"title": "string"},
        "desc": "Fokus ke jendela yang judulnya mengandung title.",
    },
    "list_windows": {
        "args": {},
        "desc": "Lihat daftar jendela yang sedang terbuka.",
    },
    "type_text": {
        "args": {"text": "string"},
        "desc": "Ketik teks di jendela aktif. Hanya untuk editor/aplikasi, bukan terminal.",
    },
    "press_key": {
        "args": {"keys": "string"},
        "desc": "Tekan tombol/kombinasi di aplikasi aktif: enter, tab, esc, ctrl+s. Delete/Backspace dilarang.",
    },
    "run_command": {
        "args": {"command": "string", "cwd": "string (opsional)"},
        "desc": "Jalankan perintah terminal singkat dari allowlist dan ambil output-nya. Wajib untuk semua perintah terminal.",
    },
    "open_folder": {
        "args": {"path": "string"},
        "desc": "Buka folder di Windows Explorer.",
    },
    "open_in_vscode": {
        "args": {"path": "string"},
        "desc": "Buka file/folder di VS Code.",
    },
    "wait": {
        "args": {"ms": "number"},
        "desc": "Jeda 100-3000 ms, mis. untuk menunggu aplikasi terbuka.",
    },
    "volume_up": {
        "args": {"steps": "number (opsional)"},
        "desc": "Naikkan volume sistem (tombol volume up).",
    },
    "volume_down": {
        "args": {"steps": "number (opsional)"},
        "desc": "Turunkan volume sistem (tombol volume down).",
    },
    "volume_mute": {
        "args": {},
        "desc": "Toggle mute volume sistem.",
    },
    "cancel_task": {
        "args": {},
        "desc": "Batalkan tugas yang sedang berjalan.",
    },

    # --- web realtime ------------------------------------------------------
    "web_search": {
        "args": {"query": "string", "max_results": "number (opsional)"},
        "desc": (
            "Cari di internet (realtime) dan dapatkan judul, URL, dan cuplikan. "
            "Wajib untuk berita, harga, cuaca, jadwal, skor, rilis, atau info terbaru."
        ),
    },
    "web_fetch": {
        "args": {"url": "string"},
        "desc": "Baca isi lengkap satu halaman web (judul, teks, link) dari URL hasil web_search.",
    },

    # --- browser dinamis ---------------------------------------------------
    "browser_open": {
        "args": {
            "url": "string",
            "new_tab": "boolean (opsional, default true)",
            "browser": "string (opsional: auto|brave|chrome|edge|firefox|vivaldi|opera)",
        },
        "desc": (
            "Buka URL sebagai tab baru di browser user yang sudah terbuka (profil, login, history user). "
            "Kalau belum ada browser, buka browser default Windows. Jangan memakai profil browser Nana. "
            "Pakai ini (bukan open_url) kalau setelah membuka situs masih perlu klik/ketik."
        ),
    },
    "browser_tabs": {
        "args": {},
        "desc": "Lihat semua tab browser user yang terbuka (judul dan mana yang aktif). Panggil dulu sebelum menutup/memilih tab.",
    },
    "browser_switch_tab": {
        "args": {"title": "string"},
        "desc": "Pindah ke tab browser user yang judulnya paling cocok. Jangan menebak; panggil browser_tabs dulu.",
    },
    "browser_close_tab": {
        "args": {"title": "string"},
        "desc": (
            "Tutup tab browser user yang judulnya cocok dengan title. Judul wajib; "
            "Nana tidak menebak dan tidak menutup tab aktif tanpa judul."
        ),
    },
    "browser_attach": {
        "args": {
            "browser": "string (opsional: auto|brave|chrome|edge|firefox|vivaldi|opera)",
        },
        "desc": (
            "Gunakan browser user yang sedang terbuka dengan profil/history-nya lewat "
            "UI Automation. Tidak menutup/me-restart browser dan tidak membuka profil Nana."
        ),
    },
    "browser_state": {
        "args": {},
        "desc": "Baca kondisi halaman aktif: URL, judul, kolom input, tombol, link, status media, dan teks.",
    },
    "browser_find": {
        "args": {"target": "string"},
        "desc": "Cari elemen di halaman berdasarkan teks/label (mis. 'Search', 'Play', judul lagu).",
    },
    "browser_click": {
        "args": {"target": "string"},
        "desc": (
            "Klik elemen berdasarkan teks/label yang terlihat. CSS selector tidak dipakai; "
            "sebutkan teks tombol/link yang ada di halaman."
        ),
    },
    "browser_fill": {
        "args": {
            "target": "string (opsional)",
            "text": "string",
            "submit": "boolean (opsional)",
        },
        "desc": "Isi kolom input berdasarkan label, lalu tekan Enter jika submit=true (default true).",
    },
    "browser_press": {
        "args": {"key": "string"},
        "desc": "Tekan tombol di halaman: Enter, Escape, Tab, ArrowDown, PageDown, Control+A, dll.",
    },
    "browser_scroll": {
        "args": {"direction": "string", "amount": "number (opsional)"},
        "desc": "Scroll halaman aktif ke atas atau ke bawah.",
    },
    "browser_wait": {
        "args": {"target": "string", "timeout": "number (opsional)"},
        "desc": "Tunggu sampai teks yang terlihat muncul di halaman.",
    },
    "browser_search": {
        "args": {
            "query": "string",
            "site": "string (opsional)",
            "browser": "string (opsional: auto|brave|chrome|edge|firefox|vivaldi|opera)",
        },
        "desc": (
            "Cari DI DALAM sebuah situs dengan menemukan kolom pencarian situs itu "
            "(bukan URL ?q=), di tab baru browser user. Contoh site: youtube, tokopedia, github."
        ),
    },
    "browser_play": {
        "args": {
            "service": "string",
            "query": "string",
            "browser": "string (opsional: auto|brave|chrome|edge|firefox|vivaldi|opera)",
        },
        "desc": (
            "Cari lalu putar lagu/video di browser user dan verifikasi benar-benar berputar. "
            "service: youtube, spotify, youtube music, atau situs lain. "
            "query: judul lagu/video yang diinginkan."
        ),
    },

    # --- browser lama (dipertahankan) -------------------------------------
    "open_url": {
        "args": {"url": "string"},
        "desc": "Buka URL http/https di browser user/default (bukan profil Nana). Untuk tugas yang perlu interaksi lanjut, pakai browser_open.",
    },
    "close_tab": {
        "args": {"title": "string", "count": "number (opsional)"},
        "desc": "Alias lama untuk browser_close_tab. Judul wajib dan harus cocok dengan tab yang ada.",
    },
    "close_browser": {
        "args": {"title": "string (opsional)"},
        "desc": "Tutup window browser tertentu hanya jika user secara eksplisit memintanya.",
    },

    # --- observasi & verifikasi -------------------------------------------
    "observe_active": {
        "args": {},
        "desc": "Lihat window aktif (judul, class, rect).",
    },
    "ui_controls": {
        "args": {"title": "string (opsional)"},
        "desc": "Ambil daftar kontrol UI Automation dari sebuah window (nama, tipe, auto_id, rect).",
    },
    "ui_click": {
        "args": {"window": "string (opsional)", "name": "string (opsional)", "auto_id": "string (opsional)"},
        "desc": "Klik kontrol UI Automation berdasarkan nama/auto_id (untuk aplikasi desktop, bukan browser).",
    },
    "ui_type": {
        "args": {"window": "string (opsional)", "name": "string (opsional)", "auto_id": "string (opsional)", "text": "string"},
        "desc": "Isi teks ke kontrol UI Automation (aplikasi desktop).",
    },
    "ui_scroll": {
        "args": {"direction": "string"},
        "desc": "Scroll aplikasi desktop: up/down/left/right.",
    },
    "mouse_click": {
        "args": {"x": "number", "y": "number"},
        "desc": "Klik mouse pada koordinat layar (fallback terakhir).",
    },
    "wait_for_control": {
        "args": {"window": "string (opsional)", "name": "string (opsional)", "auto_id": "string (opsional)", "timeout": "number (opsional)"},
        "desc": "Tunggu kontrol UI Automation muncul.",
    },
    "dismiss_dialog": {
        "args": {},
        "desc": "Tutup dialog/pop-up dengan Esc.",
    },
    "verify_window": {
        "args": {"title": "string"},
        "desc": "Verifikasi window dengan judul tertentu benar-benar terbuka.",
    },
    "verify_file": {
        "args": {"path": "string"},
        "desc": "Verifikasi file/folder benar-benar ada.",
    },
    "verify_process": {
        "args": {"name": "string"},
        "desc": "Verifikasi proses aplikasi sedang berjalan.",
    },
}


def tool_lines():
    lines = []
    for name, spec in TOOLS.items():
        if spec["args"]:
            args = ", ".join(f"{k}: {v}" for k, v in spec["args"].items())
        else:
            args = ""
        lines.append(f"- {name}({args}) : {spec['desc']}")
    return lines


def system_prompt(extra_context: str = ""):
    tools = "\n".join(tool_lines())
    now = time.strftime("%A, %d %B %Y — %H:%M")
    prompt = (
        "Kamu adalah NANA, AI agent yang mengendalikan laptop Windows milik user.\n"
        f"Waktu sekarang: {now} (waktu lokal user).\n"
        "User memakai bahasa Indonesia santai dan kadang mencampur Inggris; pahami maksudnya.\n\n"

        "CARA MENJAWAB:\n"
        "1. Kalau user hanya mengobrol/bertanya tanpa aksi, jawab biasa tanpa JSON. "
        "Singkat, maksimal 4 kalimat.\n"
        "2. Kalau user minta aksi di komputer, balas HANYA SATU objek JSON, tanpa markdown, tanpa kalimat lain:\n"
        '   {"tool":"nama_tool","args":{...}}\n'
        "3. Setelah tool dijalankan, kamu akan menerima [HASIL TOOL]. Periksa hasilnya, lalu lanjutkan "
        "ke aksi berikutnya atau jawab user. Satu aksi per balasan.\n"
        "4. Jangan pernah mengklaim berhasil sebelum ada bukti dari hasil tool. Kalau gagal, coba "
        "alternatif yang aman atau jelaskan apa adanya.\n"
        "5. Jangan pernah menampilkan JSON mentah ke user.\n\n"

        "ATURAN PENTING:\n"
        "- Browser Nana SELALU browser milik user: profil, login, dan history yang sudah ada. "
        "Jangan pernah membuka profil browser terpisah atau meminta user restart browser.\n"
        "- Kalau user tidak menyebut browser, pakai browser default Windows yang sedang terbuka. "
        "Kalau user menyebut Brave/Chrome/Edge/Firefox secara eksplisit, isi browser='brave'/'chrome'/'edge'/'firefox'.\n"
        "- Tugas browser membuka TAB BARU di browser user yang sudah terbuka. Jangan menutup atau "
        "me-restart browser user.\n"
        "- Jangan menebak. Sebelum menutup atau memilih tab, panggil browser_tabs dulu, lalu pakai judul "
        "yang benar-benar ada di daftar. Jangan pernah menutup tab yang tidak diminta. "
        "browser_tabs menampilkan tab browser user; tidak ada browser Nana terpisah.\n"
        "- browser_attach hanya untuk memastikan Nana memakai browser user. Kontrol dilakukan lewat "
        "UI Automation pada teks/label yang terlihat. Jangan meminta restart browser.\n"
        "- JANGAN memakai URL pencarian (mis. google.com/search?q=... atau youtube.com/results?search_query=...). "
        "Gunakan browser_search supaya Nana menemukan kolom pencarian situs itu dan mengetik di sana.\n"
        "- Untuk memutar musik/video, panggil browser_play(service, query). Itu sudah mencakup: buka situs, "
        "cari lewat kolom pencarian, pilih hasil, klik, dan verifikasi pemutaran. Jangan berhenti di pencarian.\n"
        "- Kalau browser_play gagal, periksa dengan browser_state, lalu lanjutkan manual dengan browser_click / "
        "browser_fill / browser_press. Jangan mengulang tool+args yang sama.\n"
        "- Untuk info terkini (berita, harga, cuaca, jadwal, skor, rilis, versi terbaru), panggil web_search. "
        "Kalau butuh detail, panggil web_fetch pada URL hasilnya.\n"
        "- Setelah aksi browser yang penting, panggil browser_state untuk memastikan hasil nyatanya.\n"
        "- Untuk aplikasi desktop (bukan web), gunakan observe_active / ui_controls / ui_click / ui_type.\n"
        "- Jangan menghapus file/folder. Tidak ada tool hapus dan kamu tidak boleh mencari celah.\n"
        "- Semua perintah terminal WAJIB lewat run_command, bukan type_text.\n"
        "- Kalau instruksi user ambigu secara material (mis. ada dua tab mirip), tanya dulu.\n\n"

        "CONTOH:\n"
        'User: "putar lagu lofi di youtube" -> {"tool":"browser_play","args":{"service":"youtube","query":"lofi instrumental"}}\n'
        'User: "cari sepatu running di tokopedia" -> {"tool":"browser_search","args":{"site":"tokopedia","query":"sepatu running"}}\n'
        'User: "tutup tab spotify" -> {"tool":"browser_tabs","args":{}}\n'
        'User: "pakai browser Brave saya yang sedang terbuka" -> {"tool":"browser_attach","args":{"browser":"brave"}}\n'
        'User: "buka youtube di Brave" -> {"tool":"browser_open","args":{"url":"https://www.youtube.com","browser":"brave"}}\n'
        'User: "harga bitcoin hari ini" -> {"tool":"web_search","args":{"query":"harga bitcoin hari ini"}}\n\n'

        f"DAFTAR TOOL:\n{tools}"
    )
    if extra_context:
        prompt += "\n\n" + extra_context
    return prompt
