"""Daftar tool dan prompt sistem untuk LLM."""

TOOLS = {
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
    "type_text": {
        "args": {"text": "string"},
        "desc": "Ketik teks di jendela aktif. Hanya untuk editor/aplikasi, bukan terminal.",
    },
    "press_key": {
        "args": {"keys": "string"},
        "desc": "Tekan tombol/kombinasi: enter, tab, esc, ctrl+s, ctrl+shift+s. Delete/Backspace dilarang.",
    },
    "run_command": {
        "args": {"command": "string", "cwd": "string (opsional)"},
        "desc": "Jalankan perintah terminal singkat dari allowlist dan ambil output-nya. Wajib untuk semua perintah terminal.",
    },
    "open_url": {
        "args": {"url": "string"},
        "desc": "Buka URL http/https di browser default.",
    },

    "open_folder": {
        "args": {"path": "string"},
        "desc": "Buka folder di Windows Explorer.",
    },
    "open_in_vscode": {
        "args": {"path": "string"},
        "desc": "Buka file/folder di VS Code.",
    },
    "list_windows": {
        "args": {},
        "desc": "Lihat daftar jendela yang sedang terbuka.",
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
    "close_tab": {
        "args": {"title": "string (opsional)", "count": "number (opsional)"},
        "desc": "Tutup tab browser (Ctrl+W) count kali; jika title diberikan, pilih tab itu dulu.",
    },
    "close_browser": {
        "args": {"title": "string (opsional)"},
        "desc": "Tutup window browser (seluruh jendela).",
    },
    "search_web": {
        "args": {"query": "string"},
        "desc": "Cari di web dan buka hasil pertama (generik, dinamis).",
    },
    "cancel_task": {
        "args": {},
        "desc": "Batalkan tugas yang sedang berjalan.",
    },
    "observe_active": {
        "args": {},
        "desc": "Lihat window aktif (judul, class, rect).",
    },
    "ui_controls": {
        "args": {"title": "string (opsional)"},
        "desc": "Ambil daftar kontrol UI dari window (nama, tipe, auto_id, rect).",
    },
    "ui_click": {
        "args": {"window": "string (opsional)", "name": "string (opsional)", "auto_id": "string (opsional)"},
        "desc": "Klik kontrol UI berdasarkan nama/auto_id.",
    },
    "ui_type": {
        "args": {"window": "string (opsional)", "name": "string (opsional)", "auto_id": "string (opsional)", "text": "string"},
        "desc": "Isi teks ke kontrol UI.",
    },
    "ui_scroll": {
        "args": {"direction": "string"},
        "desc": "Scroll halaman/aplikasi: up/down/left/right.",
    },
    "mouse_click": {
        "args": {"x": "number", "y": "number"},
        "desc": "Klik mouse pada koordinat layar (fallback).",
    },
    "wait_for_control": {
        "args": {"window": "string (opsional)", "name": "string (opsional)", "auto_id": "string (opsional)", "timeout": "number (opsional)"},
        "desc": "Tunggu kontrol UI muncul (timeout).",
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


def system_prompt():
    tools = "\n".join(tool_lines())
    return (
        "Kamu adalah NANA, asisten yang membantu user.\n"
        "Pengguna bisa mencampur bahasa Indonesia dan Inggris dalam satu kalimat; pahami maksudnya.\n\n"
        "ATURAN AKSI:\n"
        "1. Jika user meminta aksi di komputer, balas HANYA satu objek JSON tanpa markdown dan tanpa kalimat lain:\n"
        '   {"tool":"nama_tool","args":{...}}\n'
        "2. Satu aksi per balasan. Setelah menerima hasil tool, lanjutkan langkah berikutnya atau jawab user.\n"
        "3. Jangan pernah menghapus file, folder, atau isi file. Kamu tidak punya tool hapus dan tidak boleh mencari celah.\n"
        "4. Semua perintah terminal WAJIB lewat run_command. Jangan memakai type_text untuk terminal.\n"
        "5. type_text hanya untuk mengetik di editor/aplikasi biasa (bukan terminal).\n"
        "6. Jika aksi ditolak atau dibatasi, jelaskan singkat dan tawarkan alternatif yang aman.\n"
        "7. Jika tidak perlu aksi, jawab seperti biasa tanpa JSON.\n"
        "8. Untuk browser, buka URL dengan open_url; interaksi lanjut (ketik/cari/putar) dilakukan di browser yang terbuka memakai type_text/press_key.\n"
        "9. Untuk pencarian/putar/buka konten apa pun, gunakan search_web (generik) alih-alih membuka search page manual.\n"
        "9. Untuk permintaan kompleks, lanjutkan langkah demi langkah sampai tujuan selesai; jangan berhenti hanya di pencarian.\n"
        "10. Jawaban akhir memakai bahasa Indonesia yang santai, singkat (maksimal 4 kalimat), dan jangan pernah menampilkan JSON ke user.\n\n"
        f"DAFTAR TOOL:\n{tools}"
    )
