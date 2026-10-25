import os
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"

import json
import re
import wave
import threading
import time

import numpy as np
import pyaudio
import httpx
import speech_recognition as sr
import webview
from dotenv import load_dotenv

load_dotenv()

from tools import runner  # noqa: E402  (setelah .env dimuat)
from core.task_engine import TaskEngine, is_cancelled, reset_cancel  # noqa: E402

OLLAMA_URL = os.getenv("OLLAMA_URL", "https://ollama.com/v1/chat/completions")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")

HEADERS = {"Content-Type": "application/json"}
if OLLAMA_API_KEY:
    HEADERS["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

TOOLS_ENABLED = os.getenv("TOOLS_ENABLED", "true").strip().lower() in (
    "1", "true", "yes", "on",
)
try:
    TOOLS_MAX_STEPS = max(0, min(8, int(os.getenv("TOOLS_MAX_STEPS", "4") or 4)))
except ValueError:
    TOOLS_MAX_STEPS = 4

# --- Mode tidur: berapa detik tanpa pertanyaan sebelum NANA tidur (0 = nonaktif) ---
try:
    SLEEP_AFTER_SECONDS = float(os.getenv("SLEEP_AFTER_SECONDS", "30") or 0)
except ValueError:
    SLEEP_AFTER_SECONDS = 30.0

# --- Kata yang diucapkan untuk membangunkan NANA ---
WAKE_WORD = (os.getenv("WAKE_WORD", "NANA") or "NANA").strip()


def build_wake_pattern(word):
    letters = [re.escape(c) for c in re.sub(r"[^a-z0-9]", "", word.lower())]
    if not letters:
        return None
    # toleran terhadap pemisahan suku kata, mis. "NA NA"
    return r"\b" + r"\s*".join(letters) + r"\b"


WAKE_PATTERN = build_wake_pattern(WAKE_WORD)

# Ukuran jendela saat tidur (tombol panah di tepi kiri layar)
SLEEP_WIN_W = 44
SLEEP_WIN_H = 62

CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000

# VAD parameters
SPEECH_THRESHOLD = 100
SILENCE_THRESHOLD = 40
SILENCE_DURATION = 1.2
WAIT_SPEECH_TIMEOUT = 10.0
MAX_RECORD_DURATION = 15.0

p = pyaudio.PyAudio()
window = None

HTML = r"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <title>Nana</title>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body {
            width: 100%; height: 100%;
            overflow: hidden;
            font-family: 'Inter', sans-serif;
            background: #000000;
            color: #f8fafc;
            user-select: none;
            -webkit-user-select: none;
        }

        #app {
            width: 100%; height: 100%;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: flex-start;
            padding: 8px 18px;
            gap: 6px;
        }

        /* ---- Stage: wadah tetap untuk spectrum & thinking (crossfade di satu tempat) ---- */
        #stage {
            position: relative;
            width: 100%;
            height: 84px;
            flex-shrink: 0;
            transition: height 0.3s ease, margin 0.3s ease;
        }
        #stage.collapsed {
            height: 0;
            margin-bottom: -6px;
        }

        /* ---- Spectrum 5 bar ---- */
        #spectrum {
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            transition: opacity 0.35s ease, transform 0.35s ease, visibility 0.35s;
        }
        #spectrum.hidden-state {
            opacity: 0;
            transform: scale(0.94);
            visibility: hidden;
            pointer-events: none;
        }

        .bar {
            width: 12px;
            min-height: 8px;
            border-radius: 999px;
            background: linear-gradient(to top, #6366f1, #22d3ee);
            box-shadow: 0 0 12px rgba(99, 102, 241, 0.55);
            transition: height 0.05s linear, background 0.2s;
        }
        #spectrum.listening .bar {
            background: linear-gradient(to top, #f43f5e, #fbbf24);
            box-shadow: 0 0 14px rgba(244, 63, 94, 0.6);
        }

        /* ---- Thinking: 3 titik bouncing sederhana ---- */
        #thinking {
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            opacity: 0;
            transform: scale(0.94);
            visibility: hidden;
            pointer-events: none;
            transition: opacity 0.35s ease, transform 0.35s ease, visibility 0.35s;
        }
        #thinking.show {
            opacity: 1;
            transform: scale(1);
            visibility: visible;
        }
        #thinking .dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #818cf8;
            box-shadow: 0 0 10px rgba(99, 102, 241, 0.7);
            animation: bounce 1.2s ease-in-out infinite;
        }
        #thinking .dot:nth-child(1) { animation-delay: 0s; }
        #thinking .dot:nth-child(2) { animation-delay: 0.15s; }
        #thinking .dot:nth-child(3) { animation-delay: 0.3s; }

        @keyframes bounce {
            0%, 60%, 100% { transform: translateY(0); opacity: 0.5; }
            30% { transform: translateY(-10px); opacity: 1; }
        }

        /* ---- Action status (ikon Lucide CDN, tanpa emoji) ---- */
        #action {
            display: none;
            align-items: center;
            gap: 7px;
            width: 100%;
            flex-shrink: 0;
            padding: 2px 2px 0;
            font-size: 11.5px;
            color: #94a3b8;
            white-space: nowrap;
            overflow: hidden;
        }
        #action.show { display: flex; animation: fadeIn 0.18s ease-out; }
        #action .ico {
            flex: 0 0 auto;
            width: 13px;
            height: 13px;
            background: #a5b4fc;
            -webkit-mask-repeat: no-repeat;
            -webkit-mask-position: center;
            -webkit-mask-size: contain;
            mask-repeat: no-repeat;
            mask-position: center;
            mask-size: contain;
        }
        #action .label {
            overflow: hidden;
            text-overflow: ellipsis;
        }
        #action.busy .ico { animation: spin 0.9s linear infinite; }
        #action.error { color: #fbbf24; }
        #action.error .ico { background: #fbbf24; }
        #action.done .ico { background: #34d399; }
        @keyframes spin { to { transform: rotate(360deg); } }

        /* ---- Answer ---- */
        #answer {
            display: none;
            width: 100%;
            font-size: 13px;
            font-weight: 400;
            color: #e2e8f0;
            text-align: left;
            line-height: 1.55;
            word-break: break-word;
            overflow-wrap: anywhere;
            white-space: normal;
            padding: 0 2px;
        }
        #answer.show { display: block; animation: fadeIn 0.2s ease-out; }

        #answer.scrolling {
            overflow-y: auto;
            overflow-x: hidden;
            padding-right: 6px;
        }
        #answer.scrolling::-webkit-scrollbar { width: 4px; }
        #answer.scrolling::-webkit-scrollbar-thumb { background: #4b5563; border-radius: 2px; }
        #answer.scrolling::-webkit-scrollbar-track { background: transparent; }

        /* Markdown */
        #answer p { margin: 4px 0; }
        #answer code {
            background: #1e293b;
            color: #fbbf24;
            padding: 1px 5px;
            border-radius: 4px;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 12px;
        }
        #answer pre {
            background: #1e293b;
            padding: 10px;
            border-radius: 6px;
            overflow-x: auto;
            margin: 6px 0;
            border-left: 3px solid #6366f1;
        }
        #answer pre code { padding: 0; background: none; color: #e2e8f0; }
        #answer ul, #answer ol { padding-left: 22px; margin: 4px 0; }
        #answer li { margin: 2px 0; }
        #answer strong { color: #c7d2fe; font-weight: 600; }
        #answer em { color: #a5b4fc; }
        #answer a { color: #818cf8; text-decoration: underline; }
        #answer h1, #answer h2, #answer h3 {
            margin: 8px 0 4px;
            color: #c7d2fe;
            font-size: 14px;
            font-weight: 600;
        }
        #answer blockquote {
            border-left: 3px solid #4b5563;
            padding-left: 8px;
            color: #94a3b8;
            margin: 4px 0;
            font-style: italic;
        }
        #answer hr { border: none; border-top: 1px solid #334155; margin: 6px 0; }
        #answer table { border-collapse: collapse; margin: 6px 0; font-size: 12px; }
        #answer th, #answer td { border: 1px solid #334155; padding: 4px 8px; }
        #answer th { background: #1e293b; color: #c7d2fe; }

        /* Cursor */
        #answer .cursor {
            display: inline-block;
            color: #818cf8;
            font-weight: bold;
            width: 8px;
        }
        #answer .cursor::before {
            content: '▊';
            animation: blink 0.8s step-end infinite;
        }
        #answer .err-text { color: #fbbf24; font-weight: 500; }

        @keyframes blink { 50% { opacity: 0; } }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(3px); }
            to   { opacity: 1; transform: translateY(0); }
        }

        /* ---- Mode tidur: jendela kecil di tepi kiri, tanpa border, ikon ZZZ ---- */
        body.sleeping #app { display: none; }
        #wakeBtn {
            position: fixed;
            inset: 0;
            display: none;
            align-items: center;
            justify-content: center;
            padding: 0;
            border: none;
            outline: none;
            background: #000000;
            color: #a5b4fc;
            cursor: pointer;
        }
        body.sleeping #wakeBtn { display: flex; }
        #wakeBtn:hover { color: #e0e7ff; background: #0d0d16; }

        /* ZZZ animasi: tiga huruf Z naik bergantian */
        #wakeBtn .zzz {
            position: relative;
            width: 30px;
            height: 38px;
        }
        #wakeBtn .zzz span {
            position: absolute;
            font-family: 'Inter', sans-serif;
            font-weight: 700;
            line-height: 1;
            color: currentColor;
            opacity: 0;
            text-shadow: 0 0 9px rgba(99, 102, 241, 0.55);
            animation: zzzFloat 2.6s ease-in-out infinite;
        }
        #wakeBtn .zzz span:nth-child(1) {
            left: 0; bottom: 1px; font-size: 11px; animation-delay: 0s;
        }
        #wakeBtn .zzz span:nth-child(2) {
            left: 8px; bottom: 10px; font-size: 15px; animation-delay: 0.4s;
        }
        #wakeBtn .zzz span:nth-child(3) {
            left: 16px; bottom: 20px; font-size: 20px; animation-delay: 0.8s;
        }
        @keyframes zzzFloat {
            0%   { opacity: 0;   transform: translate(0, 5px) scale(0.75); }
            20%  { opacity: 1;   transform: translate(1px, 2px) scale(0.95); }
            70%  { opacity: 0.85; transform: translate(4px, -6px) scale(1); }
            100% { opacity: 0;   transform: translate(7px, -12px) scale(1.1); }
        }
    </style>
</head>
<body>
    <button id="wakeBtn" type="button" title="Bangunkan NANA" aria-label="Bangunkan NANA">
        <span class="zzz" aria-hidden="true">
            <span>Z</span><span>Z</span><span>Z</span>
        </span>
    </button>
    <div id="app">
        <div id="stage">
            <div id="spectrum">
                <div class="bar"></div>
                <div class="bar"></div>
                <div class="bar"></div>
                <div class="bar"></div>
                <div class="bar"></div>
            </div>
            <div id="thinking">
                <div class="dot"></div>
                <div class="dot"></div>
                <div class="dot"></div>
            </div>
        </div>
        <div id="action">
            <span class="ico" id="actionIcon"></span>
            <span class="label" id="actionLabel"></span>
        </div>
        <div id="answer"></div>
    </div>

    <script>
        const stage = document.getElementById('stage');
        const spectrum = document.getElementById('spectrum');
        const bars = spectrum.querySelectorAll('.bar');
        const thinking = document.getElementById('thinking');
        const answerEl = document.getElementById('answer');
        const actionEl = document.getElementById('action');
        const actionIcon = document.getElementById('actionIcon');
        const actionLabel = document.getElementById('actionLabel');

        let rawAnswer = '';
        let typedLen = 0;
        let typeTimer = null;
        let lastW = 220, lastH = 100;

        const W_LISTEN  = 220;
        const W_ANSWER  = 400;   // lebih sempit, tinggi memanjang sampai batas layar
        const H_LISTEN  = 100;
        const SPECTRUM_H = 84;
        const PADDING_V = 20;
        const MAX_H_RATIO = 0.92;
        const TYPE_SPEED_MS = 16;
        const TYPE_CHARS_PER_TICK = 2;
        const RENDER_EVERY_N_TICKS = 4;
        const MIN_THINK_MS = 1200;

        let tickCount = 0;
        let isListening = false;
        let doneSoundPlayed = false;
        let thinkingShownAt = 0;
        let hideTimer = null;

        marked.setOptions({ breaks: true, gfm: true });

        // ===== Sound effects (Web Audio, tanpa file eksternal) =====
        let audioCtx = null;
        let pendingSpawn = null;

        function getAudio() {
            try {
                if (!audioCtx) {
                    const AC = window.AudioContext || window.webkitAudioContext;
                    if (!AC) return null;
                    audioCtx = new AC();
                }
                return audioCtx;
            } catch (e) {
                return null;
            }
        }

        // Jalankan suara hanya setelah AudioContext benar-benar running
        function withAudio(fn, queueIfBlocked) {
            const ctx = getAudio();
            if (!ctx) return;
            if (ctx.state === 'running') {
                try { fn(ctx); } catch (e) {}
                return;
            }
            let settled = false;
            const giveUp = setTimeout(() => {
                if (settled) return;
                settled = true;
                if (queueIfBlocked) pendingSpawn = fn;
            }, 400);
            ctx.resume().then(() => {
                clearTimeout(giveUp);
                if (settled) return;
                settled = true;
                if (ctx.state === 'running') {
                    try { fn(ctx); } catch (e) {}
                }
            }).catch(() => {
                clearTimeout(giveUp);
                if (settled) return;
                settled = true;
                if (queueIfBlocked) pendingSpawn = fn;
            });
        }

        function playTone(ctx, o) {
            const type = o.type || 'sine';
            const peak = o.peak ?? 0.2;
            const attack = o.attack ?? 0.01;
            const t0 = o.t0;
            const dur = o.dur;

            const osc = ctx.createOscillator();
            const g = ctx.createGain();
            osc.type = type;
            osc.frequency.setValueAtTime(o.freq, t0);
            if (o.freqEnd) {
                osc.frequency.exponentialRampToValueAtTime(o.freqEnd, t0 + dur);
            }
            g.gain.setValueAtTime(0.0001, t0);
            g.gain.exponentialRampToValueAtTime(peak, t0 + attack);
            g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);

            osc.connect(g);
            g.connect(ctx.destination);
            osc.start(t0);
            osc.stop(t0 + dur + 0.05);
        }

        function playBell(ctx, freq, t0, peak) {
            // parsial inharmonik supaya terdengar seperti lonceng
            playTone(ctx, { type: 'sine', freq: freq,        t0: t0, dur: 0.9,  peak: peak,        attack: 0.005 });
            playTone(ctx, { type: 'sine', freq: freq * 2.76, t0: t0, dur: 0.5,  peak: peak * 0.25, attack: 0.005 });
            playTone(ctx, { type: 'sine', freq: freq * 5.4,  t0: t0, dur: 0.25, peak: peak * 0.10, attack: 0.005 });
        }

        // Saat listening dimulai: sweep naik + kilau nada tinggi
        function playSpawnSound(ctx) {
            const t = ctx.currentTime + 0.02;
            playTone(ctx, { type: 'sine',     freq: 260, freqEnd: 1400, t0: t, dur: 0.45, peak: 0.12, attack: 0.08 });
            playTone(ctx, { type: 'triangle', freq: 390, freqEnd: 2100, t0: t, dur: 0.45, peak: 0.05, attack: 0.10 });
            [1568, 2093, 2637].forEach((f, i) => {
                playTone(ctx, { type: 'sine', freq: f, t0: t + 0.28 + i * 0.06, dur: 0.35, peak: 0.09, attack: 0.005 });
            });
        }

        // Saat jawaban selesai diketik: dua denting lonceng berurutan
        function playDoneSound(ctx) {
            const t = ctx.currentTime + 0.02;
            playBell(ctx, 1047, t,        0.16);
            playBell(ctx, 1568, t + 0.13, 0.20);
        }

        // Setiap klik/tekan tombol memastikan audio aktif, dan memutar suara yang sempat tertahan
        function unlockAudio() {
            const ctx = getAudio();
            if (!ctx) return;
            const go = () => {
                if (pendingSpawn && ctx.state === 'running') {
                    const f = pendingSpawn;
                    pendingSpawn = null;
                    try { f(ctx); } catch (e) {}
                }
            };
            if (ctx.state === 'running') go();
            else ctx.resume().then(go).catch(() => {});
        }
        document.addEventListener('pointerdown', unlockAudio, true);
        document.addEventListener('keydown', unlockAudio, true);

        // ===== Helpers =====
        function escapeHtml(s) {
            return String(s).replace(/[&<>"']/g, c => ({
                '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
            }[c]));
        }

        // ===== Status aksi (ikon dari Lucide CDN, tanpa emoji) =====
        const ICON_CDN = 'https://cdn.jsdelivr.net/npm/lucide-static@1.61.0/icons/';
        const ACTION_ICONS = {
            app: 'app-window',
            terminal: 'terminal',
            keyboard: 'keyboard',
            key: 'command',
            command: 'square-terminal',
            focus: 'focus',
            globe: 'globe',
            folder: 'folder-open',
            list: 'layout-list',
            timer: 'timer',
            busy: 'loader-2',
            check: 'check',
            blocked: 'shield-alert'
        };

        function setActionIcon(name) {
            const file = ACTION_ICONS[name] || ACTION_ICONS.app;
            const url = 'url("' + ICON_CDN + file + '.svg")';
            actionIcon.style.webkitMaskImage = url;
            actionIcon.style.maskImage = url;
        }

        window.showAction = function (icon, label) {
            setActionIcon('busy');
            actionLabel.textContent = label || 'Bekerja...';
            actionEl.classList.add('show', 'busy');
            actionEl.classList.remove('done', 'error');
        };

        window.finishAction = function (ok, label) {
            actionEl.classList.remove('busy');
            actionEl.classList.toggle('done', !!ok);
            actionEl.classList.toggle('error', !ok);
            setActionIcon(ok ? 'check' : 'blocked');
            if (label) actionLabel.textContent = label;
        };

        window.hideAction = function () {
            actionEl.classList.remove('show', 'busy', 'done', 'error');
        };

        function maxWindowHeight() {
            return Math.floor(window.screen.availHeight * MAX_H_RATIO);
        }

        function currentStageH() {
            return stage.classList.contains('collapsed') ? 0 : SPECTRUM_H;
        }

        function resize(w, h, force) {
            if (!window.pywebview?.api?.resize) return;
            const maxH = maxWindowHeight();
            h = Math.min(h, maxH);
            if (!force && Math.abs(w - lastW) < 4 && Math.abs(h - lastH) < 6) return;
            lastW = w; lastH = h;
            window.pywebview.api.resize(w, h);
        }

        function measureAnswerHeight() {
            if (!answerEl.classList.contains('show')) return 0;
            return answerEl.scrollHeight || 0;
        }

        function updateAnswerSize() {
            if (!window.pywebview?.api?.resize) return;
            const stageH = currentStageH();
            const actionH = actionEl.classList.contains('show') ? (actionEl.offsetHeight + 6) : 0;
            const ansH = measureAnswerHeight();
            const maxH = maxWindowHeight();
            const neededH = stageH + actionH + PADDING_V + ansH + 12;

            if (neededH <= maxH) {
                answerEl.classList.remove('scrolling');
                answerEl.style.maxHeight = '';
                resize(W_ANSWER, Math.max(H_LISTEN, neededH), false);
            } else {
                answerEl.classList.add('scrolling');
                const innerMax = maxH - stageH - actionH - PADDING_V - 20;
                answerEl.style.maxHeight = innerMax + 'px';
                resize(W_ANSWER, maxH, false);
                answerEl.scrollTop = answerEl.scrollHeight;
            }
        }

        // ===== Thinking show / hide =====
        function showThinking() {
            clearTimeout(hideTimer);
            hideTimer = null;
            if (!thinking.classList.contains('show')) {
                thinkingShownAt = performance.now();
            }
            stage.classList.remove('collapsed');
            spectrum.classList.add('hidden-state');
            spectrum.classList.remove('listening');
            thinking.classList.add('show');
        }

        // thinking baru hilang setelah typewriter selesai dan minimal MIN_THINK_MS terlewati
        function hideThinking() {
            clearTimeout(hideTimer);
            const wait = Math.max(0, MIN_THINK_MS - (performance.now() - thinkingShownAt));
            hideTimer = setTimeout(() => {
                hideTimer = null;
                thinking.classList.remove('show');
                stage.classList.add('collapsed');
                setTimeout(() => {
                    if (answerEl.classList.contains('show')) updateAnswerSize();
                }, 320);
            }, wait);
        }

        // Dipanggil Python: true jika masih ada proses (typewriter / thinking) yang berjalan
        window.isBusy = function () {
            return typeTimer !== null || hideTimer !== null || thinking.classList.contains('show');
        };

        // ===== Audio bars =====
        window.updateBars = function (levels) {
            for (let i = 0; i < bars.length; i++) {
                const h = Math.max(8, Math.min(84, (levels[i] || 0)));
                bars[i].style.height = h + 'px';
            }
        };

        // ===== Back to listening (keep previous answer) =====
        window.setListening = function () {
            clearTimeout(hideTimer);
            hideTimer = null;
            window.hideAction();

            stage.classList.remove('collapsed');
            spectrum.classList.remove('hidden-state');
            spectrum.classList.add('listening');
            thinking.classList.remove('show');
            bars.forEach(b => b.style.height = '8px');

            // suara spawn hanya saat transisi dari non-listening ke listening
            if (!isListening) {
                isListening = true;
                withAudio(playSpawnSound, true);
            }

            answerEl.classList.remove('err');

            clearInterval(typeTimer);
            typeTimer = null;

            if (rawAnswer) {
                answerEl.innerHTML = marked.parse(rawAnswer);
                answerEl.classList.add('show', 'done');
                updateAnswerSize();
            } else {
                answerEl.innerHTML = '';
                answerEl.classList.remove('show', 'done', 'scrolling');
                answerEl.style.maxHeight = '';
                resize(W_LISTEN, H_LISTEN, true);
            }
        };

        // ===== Processing: SEMBUNYIKAN spectrum, TAMPILKAN thinking =====
        window.startProcessing = function () {
            isListening = false;
            showThinking();
            resize(W_LISTEN, H_LISTEN, true);
        };

        // ===== New answer =====
        window.startAnswer = function () {
            isListening = false;
            window.hideAction();
            showThinking(); // thinking tetap tampil selama typewriter berjalan

            rawAnswer = '';
            typedLen = 0;
            tickCount = 0;
            doneSoundPlayed = false;
            clearInterval(typeTimer);
            typeTimer = null;

            answerEl.innerHTML = '<span class="cursor"></span>';
            answerEl.classList.add('show');
            answerEl.classList.remove('err', 'done', 'scrolling');
            answerEl.style.maxHeight = '';
            resize(W_ANSWER, H_LISTEN + 30, true);
        };

        // ===== Token masuk =====
        window.appendAnswer = function (text) {
            if (!text) return;
            if (actionEl.classList.contains('show')) window.hideAction();
            rawAnswer += text;
            if (!typeTimer) startTypewriter();
        };

        // ===== Typewriter markdown live =====
        function startTypewriter() {
            typeTimer = setInterval(() => {
                let changed = false;

                if (typedLen < rawAnswer.length) {
                    typedLen = Math.min(rawAnswer.length, typedLen + TYPE_CHARS_PER_TICK);
                    changed = true;
                }

                tickCount++;
                if (changed && (tickCount % RENDER_EVERY_N_TICKS === 0 || typedLen >= rawAnswer.length)) {
                    const partial = rawAnswer.slice(0, typedLen);
                    answerEl.innerHTML = marked.parse(partial) + '<span class="cursor"></span>';
                }

                if (changed) {
                    updateAnswerSize();
                }

                if (typedLen >= rawAnswer.length) {
                    clearInterval(typeTimer);
                    typeTimer = null;
                    if (answerEl.classList.contains('done')) {
                        finalizeAnswer();
                    }
                }
            }, TYPE_SPEED_MS);
        }

        // ===== Stream selesai =====
        window.endAnswer = function () {
            answerEl.classList.add('done');
            if (!typeTimer) finalizeAnswer();
        };

        function finalizeAnswer() {
            // typewriter sudah selesai → thinking dihentikan, lalu bunyi selesai
            hideThinking();

            if (!rawAnswer) {
                answerEl.innerHTML = '';
                answerEl.classList.remove('show');
                return;
            }

            if (!doneSoundPlayed) {
                doneSoundPlayed = true;
                withAudio(playDoneSound, false);
            }

            answerEl.innerHTML = marked.parse(rawAnswer);
            answerEl.classList.add('done');
            requestAnimationFrame(() => {
                setTimeout(() => {
                    updateAnswerSize();
                    if (answerEl.classList.contains('scrolling')) {
                        answerEl.scrollTop = answerEl.scrollHeight;
                    }
                }, 20);
            });
        }

        // ===== Error =====
        window.showError = function (msg) {
            clearInterval(typeTimer);
            typeTimer = null;
            clearTimeout(hideTimer);
            hideTimer = null;
            isListening = false;
            window.hideAction();

            stage.classList.remove('collapsed');
            thinking.classList.remove('show');
            spectrum.classList.remove('hidden-state');
            answerEl.innerHTML = '<div class="err-text">⚠ ' + escapeHtml(msg) + '</div>';
            answerEl.classList.add('show', 'err');
            answerEl.classList.remove('done', 'scrolling');
            answerEl.style.maxHeight = '';
            resize(W_ANSWER, H_LISTEN + 40, true);
        };

        // ===== Mode tidur / bangun =====
        const wakeBtn = document.getElementById('wakeBtn');
        wakeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            unlockAudio();
            if (window.pywebview?.api?.wake) window.pywebview.api.wake();
            else document.body.classList.remove('sleeping');
        });

        window.enterSleepUI = function () {
            clearInterval(typeTimer);
            typeTimer = null;
            clearTimeout(hideTimer);
            hideTimer = null;
            window.hideAction();
            isListening = false;
            rawAnswer = '';
            typedLen = 0;
            tickCount = 0;
            doneSoundPlayed = false;
            answerEl.innerHTML = '';
            answerEl.classList.remove('show', 'done', 'err', 'scrolling');
            answerEl.style.maxHeight = '';
            stage.classList.remove('collapsed');
            thinking.classList.remove('show');
            spectrum.classList.add('hidden-state');
            spectrum.classList.remove('listening');
            bars.forEach(b => b.style.height = '8px');
            document.body.classList.add('sleeping');
        };

        window.wakeUI = function () {
            document.body.classList.remove('sleeping');
            lastW = 0;
            lastH = 0;
            window.setListening();
        };

        document.getElementById('app').addEventListener('click', () => {});
        window.addEventListener('load', () => resize(W_LISTEN, H_LISTEN, true));
    </script>
</body>
</html>
"""

class Api:
    def __init__(self):
        self._window = None
        self._running = True
        self._loop_thread = None
        self._sleeping = False
        self._last_activity = time.time()
        self._prev_xy = None
        self._history = []
        self._task_engine = TaskEngine()
        self._current_task = None
        # True setelah terminal VS Code dibuka pada request yang sama:
        # type_text diblokir supaya perintah tidak "nyasar" ke terminal.
        self._terminal_guard = False

    def set_window(self, w):
        self._window = w

    def resize(self, w, h):
        # saat tidur ukuran jendela dikendalikan oleh mode tidur
        if self._sleeping:
            return "ok"
        try:
            self._window.resize(int(w), int(h))
        except Exception:
            pass
        return "ok"

    def _js(self, code):
        for _ in range(3):
            try:
                self._window.evaluate_js(code)
                return
            except Exception:
                time.sleep(0.15)

    def _js_get(self, code):
        try:
            return self._window.evaluate_js(code)
        except Exception:
            return None

    def _send_levels(self, levels):
        self._js(f"window.updateBars({json.dumps(levels)})")

    # Tunggu sampai typewriter dan thinking di UI selesai sebelum kembali ke listening
    def _wait_idle(self, timeout=90.0):
        end = time.time() + timeout
        time.sleep(0.1)
        while self._running and time.time() < end:
            busy = self._js_get("window.isBusy()")
            if not busy:
                return
            time.sleep(0.1)

    # ---------------- Mode tidur / bangun ----------------
    def _screen(self):
        try:
            s = webview.screens[0]
            return int(s.x), int(s.y), int(s.width), int(s.height)
        except Exception:
            return 0, 0, 1536, 864

    # Jendela mengecil dan menempel di tepi kiri layar, hanya tombol panah
    def _enter_sleep(self):
        if self._sleeping or self._window is None:
            return
        print("[sleep] tidak ada pertanyaan, NANA tidur")
        self._sleeping = True
        try:
            self._prev_xy = (int(self._window.x), int(self._window.y))
        except Exception:
            self._prev_xy = None
        try:
            self._window.on_top = True
            self._js("window.enterSleepUI()")
            self._window.resize(SLEEP_WIN_W, SLEEP_WIN_H)
            sx, sy, sw, sh = self._screen()
            self._window.move(sx, sy + max(0, (sh - SLEEP_WIN_H) // 2))
        except Exception as e:
            print(f"[sleep] {e}")

    def _wake_up(self):
        if not self._sleeping:
            return
        print("[sleep] NANA bangun")
        self._sleeping = False
        self._last_activity = time.time()
        try:
            self._window.on_top = True
            if self._prev_xy:
                self._window.move(*self._prev_xy)
        except Exception:
            pass
        self._js("window.wakeUI()")

    # Dipanggil tombol panah di UI
    def wake(self):
        self._wake_up()
        return "ok"

    @staticmethod
    def _norm_text(text):
        return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

    def _contains_wake_word(self, text):
        if not WAKE_PATTERN or not text:
            return False
        return re.search(WAKE_PATTERN, self._norm_text(text)) is not None

    def _strip_wake_word(self, text):
        norm = self._norm_text(text)
        if WAKE_PATTERN:
            norm = re.sub(WAKE_PATTERN, " ", norm)
        return " ".join(norm.split())

    # Selama tidur mic tetap mendengarkan wake word ("NANA")
    def _sleep_listen(self):
        frames = self._record_vad(send_levels=False, abort=lambda: not self._sleeping)
        if not self._running or not self._sleeping or not frames:
            return

        text = self._transcribe(frames)
        if not text:
            return
        print(f"[sleep] terdengar: {text!r}")

        if not self._contains_wake_word(text):
            return

        rest = self._strip_wake_word(text)
        self._wake_up()

        # Kalau wake word diucapkan bersama pertanyaan, langsung jawab.
        if len(rest) >= 2:
            print(f"[sleep] pertanyaan langsung: {rest!r}")
            self._last_activity = time.time()
            self._js("window.startProcessing()")
            self._js("window.startAnswer()")
            self._stream_llm(rest)
            self._js("window.endAnswer()")
            self._wait_idle()
            self._last_activity = time.time()

    # ---------------- Auto loop ----------------
    def start_auto(self):
        if self._loop_thread and self._loop_thread.is_alive():
            return "already_running"
        self._running = True
        self._loop_thread = threading.Thread(target=self._loop, daemon=True)
        self._loop_thread.start()
        return "ok"

    def stop_auto(self):
        self._running = False
        return "ok"

    def _loop(self):
        time.sleep(1.5)
        print("[loop] started")
        self._last_activity = time.time()

        while self._running:
            try:
                # tidur kalau sudah lama tidak ada pertanyaan
                if (SLEEP_AFTER_SECONDS > 0
                        and time.time() - self._last_activity >= SLEEP_AFTER_SECONDS):
                    self._enter_sleep()

                if self._sleeping:
                    self._sleep_listen()
                    continue

                self._js("window.setListening()")
                print("[loop] listening...")
                frames = self._record_vad()

                if not self._running:
                    break
                if not frames:
                    continue

                self._last_activity = time.time()
                print(f"[loop] speech detected: {len(frames)} chunks "
                      f"(~{len(frames)*CHUNK/RATE:.1f}s)")

                self._js("window.startProcessing()")
                text = self._transcribe(frames)
                print(f"[loop] transcribed: {text!r}")

                if not text:
                    # tidak ada transkripsi -> jawaban lama tetap tampil
                    time.sleep(0.8)
                    continue

                low = text.lower()
                if "batalkan" in low or "cancel" in low or "batal" in low:
                    reset_cancel()
                    from core.task_engine import request_cancel as _rc
                    _rc()
                    if self._current_task is not None:
                        self._current_task.status = "cancelled"
                    self._js("window.startAnswer()")
                    self._emit("Tugas dibatalkan.")
                    self._js("window.endAnswer()")
                    self._wait_idle()
                    self._last_activity = time.time()
                    time.sleep(1.0)
                    continue

                self._js("window.startAnswer()")
                ok = self._stream_llm(text)
                if not ok:
                    print("[loop] stream fallback failed")
                self._js("window.endAnswer()")

                # tunggu typewriter & thinking selesai dulu, baru kembali ke listening
                self._wait_idle()
                if not self._running:
                    break

                # jawaban tetap tampil, tidak dihapus
                self._last_activity = time.time()
                time.sleep(1.0)
            except Exception as e:
                print(f"[loop error] {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(1.0)

    # ---------------- VAD ----------------
    def _open_stream(self):
        for rate in (RATE, 44100, 48000):
            try:
                stream = p.open(format=FORMAT, channels=CHANNELS,
                                rate=rate, input=True,
                                frames_per_buffer=CHUNK)
                return stream, rate
            except Exception as e:
                print(f"[mic] rate {rate} failed: {e}")
                continue
        return None, RATE

    def _record_vad(self, send_levels=True, abort=None):
        stream, rate = self._open_stream()
        if stream is None:
            if not self._sleeping:
                self._js("window.showError('mic tidak bisa dibuka - cek izin Windows Privacy')")
            time.sleep(3.0)
            return []

        frames = []
        pre_buffer = []
        pre_max = 15
        start_t = time.time()
        speech_started = False
        above_count = 0
        silence_count = 0
        silence_needed = int(SILENCE_DURATION * rate / CHUNK)
        min_frames = int(0.25 * rate / CHUNK)
        chunk_idx = 0

        try:
            while self._running:
                if abort and abort():
                    break

                elapsed = time.time() - start_t
                if elapsed > MAX_RECORD_DURATION:
                    break
                if not speech_started and elapsed > WAIT_SPEECH_TIMEOUT:
                    if send_levels:
                        print("[vad] timeout, no speech")
                    break

                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                except Exception as e:
                    print(f"[mic read] {e}")
                    break

                audio = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(audio ** 2)))

                chunk_idx += 1
                if send_levels and chunk_idx % 16 == 0 and not speech_started:
                    print(f"[audio] rms={rms:.0f} (speech need >{SPEECH_THRESHOLD})")

                # ---- spectrum ----
                if send_levels:
                    seg = max(1, len(audio) // 5)
                    levels = []
                    for i in range(5):
                        ch = audio[i * seg:(i + 1) * seg]
                        if len(ch) == 0:
                            levels.append(8)
                            continue
                        r = float(np.sqrt(np.mean(ch ** 2)))
                        lvl = min(84, 8 + np.sqrt(r) * 3.5)
                        levels.append(round(lvl, 1))
                    self._send_levels(levels)

                # ---- VAD ----
                if not speech_started:
                    pre_buffer.append(data)
                    if len(pre_buffer) > pre_max:
                        pre_buffer.pop(0)
                    if rms > SPEECH_THRESHOLD:
                        above_count += 1
                        if above_count >= 3:
                            speech_started = True
                            frames = list(pre_buffer)
                            pre_buffer = []
                            print(f"[vad] speech started at rms={rms:.0f}")
                    else:
                        above_count = 0
                else:
                    frames.append(data)
                    if rms < SILENCE_THRESHOLD:
                        silence_count += 1
                        if silence_count >= silence_needed:
                            print("[vad] silence detected, done")
                            break
                    else:
                        silence_count = 0
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass

        if not speech_started or len(frames) < min_frames:
            return []
        return frames

    # ---------------- Transkripsi ----------------
    def _transcribe(self, frames):
        try:
            with wave.open("temp.wav", "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(p.get_sample_size(FORMAT))
                wf.setframerate(RATE)
                wf.writeframes(b"".join(frames))
        except Exception as e:
            print(f"[wav] {e}")
            return ""

        for attempt in range(2):
            try:
                r = sr.Recognizer()
                with sr.AudioFile("temp.wav") as source:
                    audio = r.record(source)
                try:
                    return r.recognize_google(audio, language="id-ID")
                except Exception as e1:
                    print(f"[stt id] {e1}")
                    try:
                        return r.recognize_google(audio)
                    except Exception as e2:
                        print(f"[stt] {e2}")
            except Exception as e:
                print(f"[sr] {e}")
            if attempt == 0:
                time.sleep(0.5)
        return ""

    # ---------------- Streaming LLM + tools ----------------
    def _emit(self, text):
        if text:
            self._js(f"window.appendAnswer({json.dumps(text)})")

    def _messages_for(self, text):
        messages = [{"role": "system", "content": runner.system_prompt()}]
        messages.extend(self._history[-8:])
        messages.append({"role": "user", "content": text})
        return messages

    @staticmethod
    def _parse_action(text):
        raw = (text or "").strip()
        if not raw:
            return None
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw).strip()
        try:
            obj, _ = json.JSONDecoder().raw_decode(raw)
        except Exception:
            return None
        name = obj.get("tool") if isinstance(obj, dict) else None
        if isinstance(name, str):
            name = re.sub(r"\s*\([^)]*\)\s*$", "", name.strip())
        if isinstance(name, str) and name:
            args = obj.get("args")
            return {"tool": name, "args": args if isinstance(args, dict) else {}}
        return None

    def _request_once(self, messages):
        try:
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(
                    OLLAMA_URL,
                    headers=HEADERS,
                    json={
                        "model": OLLAMA_MODEL,
                        "messages": messages,
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[fallback] {e}")
            return None

    def _llm_round(self, messages):
        """Satu panggilan LLM. Return (teks_yang_sudah_diemit, action|None)."""
        emitted = []
        buffered = ""
        mode = None
        got_any = False

        def emit(chunk):
            if chunk:
                emitted.append(chunk)
                self._emit(chunk)

        def classify():
            nonlocal buffered, mode
            stripped = buffered.lstrip()
            if not stripped:
                return
            if stripped.startswith("```"):
                if "\n" in stripped:
                    first, rest = stripped.split("\n", 1)
                    info = first[3:].strip().lower()
                    if info in ("", "json") and rest.lstrip().startswith("{"):
                        mode = "action"
                    else:
                        mode = "text"
                        emit(buffered)
                        buffered = ""
                elif len(stripped) > 16:
                    mode = "text"
                    emit(buffered)
                    buffered = ""
            elif stripped.startswith("{"):
                # kandidat aksi; ditahan sampai JSON selesai
                mode = "action"
            else:
                mode = "text"
                emit(buffered)
                buffered = ""

        headers = {**HEADERS, "Accept": "text/event-stream"}
        try:
            with httpx.Client(timeout=120.0) as client:
                with client.stream(
                    "POST",
                    OLLAMA_URL,
                    headers=headers,
                    json={
                        "model": OLLAMA_MODEL,
                        "messages": messages,
                        "stream": True,
                    },
                ) as resp:
                    resp.raise_for_status()
                    for raw in resp.iter_lines():
                        if not self._running:
                            break
                        if not raw:
                            continue
                        line = raw.strip()
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            obj = json.loads(payload)
                            delta = obj["choices"][0]["delta"].get("content")
                        except Exception:
                            continue
                        if not delta:
                            continue

                        got_any = True
                        if mode is None:
                            buffered += delta
                            classify()
                        elif mode == "text":
                            emit(delta)
                        else:
                            buffered += delta
        except Exception as e:
            print(f"[stream] {e}")

        if got_any:
            if mode == "action":
                action = self._parse_action(buffered)
                if action:
                    return "".join(emitted), action
                emit(buffered)
            elif mode is None and buffered:
                action = self._parse_action(buffered)
                if action:
                    return "".join(emitted), action
                emit(buffered)
            return "".join(emitted), None

        # ---- fallback non-streaming ----
        print("[stream] fallback ke non-streaming")
        answer = self._request_once(messages)
        if answer is None:
            return "".join(emitted), None

        action = self._parse_action(answer)
        if action:
            return "", action
        emit(answer)
        return "".join(emitted), None

    def _stream_llm(self, message):
        if not OLLAMA_URL:
            self._emit("OLLAMA_URL belum diset di .env")
            return False

        messages = self._messages_for(message)
        emitted_any = False
        final_text = ""
        self._terminal_guard = False
        reset_cancel()
        self._current_task = self._task_engine.create(message)
        self._task_engine.set_plan(self._current_task.task_id, [])

        for step in range(TOOLS_MAX_STEPS + 1):
            if is_cancelled():
                msg = "Tugas dibatalkan."
                self._emit(msg)
                emitted_any = True
                final_text += msg
                if self._current_task is not None:
                    self._current_task.status = "cancelled"
                break
            emitted, action = self._llm_round(messages)
            if emitted:
                emitted_any = True
                final_text += emitted

            if action is None:
                break

            tool = action.get("tool")
            args = action.get("args") or {}

            if not TOOLS_ENABLED:
                msg = "Maaf, kontrol komputer sedang dimatikan (TOOLS_ENABLED=false)."
                self._emit(msg)
                emitted_any = True
                final_text += msg
                break

            if step >= TOOLS_MAX_STEPS:
                msg = "Maaf, langkahnya terlalu banyak. Coba satu per satu ya."
                self._emit(msg)
                emitted_any = True
                final_text += msg
                break

            icon, label = runner.status(tool, args)
            print(f"[tool] rencana: {tool} {json.dumps(args, ensure_ascii=False)[:200]}")
            self._js(f"window.showAction({json.dumps(icon)}, {json.dumps(label)})")

            tool_name = re.sub(r"\s*\([^)]*\)\s*$", "", str(tool or "").strip())

            if tool_name == "type_text" and self._terminal_guard:
                result = {
                    "ok": False,
                    "blocked": True,
                    "message": (
                        "terminal sudah dibuka pada permintaan ini; "
                        "gunakan run_command untuk perintah terminal"
                    ),
                }
            else:
                result = runner.run(tool, args)

            if (
                tool_name == "open_terminal"
                and result.get("ok")
                and "vscode" in str((args or {}).get("target") or "vscode").lower()
            ):
                self._terminal_guard = True

            if self._current_task is not None:
                if result.get("ok"):
                    self._task_engine.complete_step(self._current_task.task_id, result)
                else:
                    self._task_engine.fail(self._current_task.task_id, result)

            done_label = "Selesai"
            if not result.get("ok"):
                done_label = "Diblokir" if result.get("blocked") else "Gagal"
            self._js(
                f"window.finishAction({json.dumps(bool(result.get('ok')))}, "
                f"{json.dumps(done_label)})"
            )

            messages.append(
                {"role": "assistant", "content": json.dumps(action, ensure_ascii=False)}
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"[HASIL TOOL: {tool}]\n"
                        f"{json.dumps(result, ensure_ascii=False)}\n\n"
                        "Lanjutkan: kalau masih perlu aksi lain, balas JSON tool berikutnya. "
                        "Kalau sudah selesai, jawab user dengan bahasa Indonesia singkat. "
                        "Jangan tampilkan JSON ke user."
                    ),
                }
            )

        if not emitted_any:
            msg = "Maaf, tidak ada respons dari AI. Coba lagi ya."
            self._emit(msg)
            final_text = msg
            emitted_any = True

        if self._current_task is not None and self._current_task.status not in ("failed", "cancelled"):
            self._current_task.status = "completed" if emitted_any else "failed"

        self._history.append({"role": "user", "content": message})
        self._history.append({"role": "assistant", "content": final_text})
        self._history = self._history[-10:]
        return emitted_any


if __name__ == "__main__":
    api = Api()
    window = webview.create_window(
        "Nana",
        html=HTML,
        js_api=api,
        width=120,
        height=100,
        resizable=False,
        frameless=True,
        easy_drag=True,
        on_top=True,
        min_size=(SLEEP_WIN_W, SLEEP_WIN_H),
    )
    api.set_window(window)
    webview.start(lambda: api.start_auto())
    api.stop_auto()
    try:
        os.remove("temp.wav")
    except Exception:
        pass