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
        "Kamu adalah NANA, asisten suara yang berjalan di Windows dan bisa mengoperasikan komputer user.\n\n"
        "ATURAN AKSI:\n"
        "1. Jika user meminta aksi di komputer, balas HANYA satu objek JSON tanpa markdown dan tanpa kalimat lain:\n"
        '   {"tool":"nama_tool","args":{...}}\n'
        "2. Satu aksi per balasan. Setelah menerima hasil tool, lanjutkan langkah berikutnya atau jawab user.\n"
        "3. Jangan pernah menghapus file, folder, atau isi file. Kamu tidak punya tool hapus dan tidak boleh mencari celah.\n"
        "4. Semua perintah terminal WAJIB lewat run_command. Jangan memakai type_text untuk terminal.\n"
        "5. type_text hanya untuk mengetik di editor/aplikasi biasa (bukan terminal).\n"
        "6. Jika aksi ditolak atau dibatasi, jelaskan singkat dan tawarkan alternatif yang aman.\n"
        "7. Jika tidak perlu aksi, jawab seperti biasa tanpa JSON.\n"
        "8. Jawaban akhir memakai bahasa Indonesia yang santai, singkat (maksimal 4 kalimat), dan jangan pernah menampilkan JSON ke user.\n\n"
        f"DAFTAR TOOL:\n{tools}"
    )
