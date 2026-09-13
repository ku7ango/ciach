"""Ciach – jednoplikowy trimmer mp4/mp3.

Backend: pywebview (WebView2) + lokalny serwer HTTP (media z obsługą Range,
waveform, znaczniki klatek) + ffmpeg/ffprobe do analizy i eksportu.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import tempfile
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np
import webview
from webview.dom import DOMEventHandler

APP_NAME = "Ciach"
FROZEN = getattr(sys, "frozen", False)
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(BASE_DIR, "ui")
EXE_DIR = (
    os.path.dirname(os.path.abspath(sys.executable))
    if FROZEN
    else os.path.dirname(os.path.abspath(__file__))
)
OUT_DIR = EXE_DIR
ERROR_LOG = os.path.join(OUT_DIR, "Ciach_error.log")
ALLOWED_EXT = {".mp4", ".mp3"}
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
DEBUG = os.environ.get("CIACH_DEBUG") == "1"

WAVE_RATE = 8000  # Hz po zmiksowaniu do mono
WAVE_BIN = 40  # próbek na bin = 5 ms
NVENC_ARGS = ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "16", "-b:v", "0"]
X264_ARGS = ["-c:v", "libx264", "-preset", "medium", "-crf", "16"]
MIX_AUDIO_RATE = 192_000  # AAC, gdy Ciach musi miksować (Podkłady albo Głośność inna niż 100 %)
# Baza czasu kodera z kontenera, nie z fps: sklejka 30 + 60 fps (zmiennoklatkowa) nie gubi klatek.
VIDEO_TB = ["-enc_time_base:v", "demux"]

# Mały Ciach: limit rozmiaru (bajty), cele kolejnych prób, próg jakości i drabinka rozdzielczości
SMALL_LIMIT = 25_000_000
SMALL_FACTORS = [0.98, 0.92, 0.85]
SMALL_BPP = 0.05  # bity na piksel na klatkę, poniżej których schodzimy z fps / rozdzielczością
SMALL_HEIGHTS = [540, 360]
SMALL_MP3_RATES = [128_000, 96_000, 64_000]
KADR_MIN = 0.2  # najmniejszy Kadr: 20 % obrazu (5×)
ZOOM_CMD = "zoom.cmd"  # plik poleceń sendcmd w katalogu tymczasowym eksportu (ffmpeg dostaje cwd)
ZOOM_EPS = 0.0005  # zapas jak przy cięciu: klatka o znaczniku `at` wchodzi do przedziału


def find_tool(name: str) -> str:
    for d in (BASE_DIR, EXE_DIR):
        p = os.path.join(d, name + ".exe")
        if os.path.isfile(p):
            return p
    return shutil.which(name) or name


FFMPEG = find_tool("ffmpeg")
FFPROBE = find_tool("ffprobe")


def popen(cmd, **kw):
    kw.setdefault("creationflags", CREATE_NO_WINDOW)
    kw.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.Popen(cmd, **kw)


def run(cmd, timeout=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        creationflags=CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL,
        timeout=timeout,
    )


def parse_rate(s: str | None) -> float:
    if not s or s in ("0/0", "N/A"):
        return 0.0
    if "/" in s:
        a, b = s.split("/", 1)
        try:
            return float(a) / float(b) if float(b) else 0.0
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


class MediaError(Exception):
    pass


def plan_small_video(dur: float, width: int, height: int, fps: float, vbitrate: int, abitrate: int,
                     audio_streams: int, factor: float, limit: int = SMALL_LIMIT) -> dict:
    """Plan Małego Ciachu dla wideo: audio wg długości, bitrate wideo z budżetu,
    potem drabinka: najpierw 60→30 fps, potem 720→540→360p, aż bpp >= SMALL_BPP."""
    if audio_streams == 0:
        a_mode, a_rate, mono = "none", 0, False
    elif dur <= 90:
        if audio_streams == 1:
            a_mode, a_rate, mono = "copy", (abitrate or 160_000), False
        else:
            a_mode, a_rate, mono = "aac", 160_000, False
    elif dur <= 180:
        a_mode, a_rate, mono = "aac", 128_000, False
    elif dur <= 360:
        a_mode, a_rate, mono = "aac", 96_000, False
    else:
        a_mode, a_rate, mono = "aac", 64_000, True
    budget_bits = limit * factor * 8 * 0.985  # ~1,5 % na kontener mp4
    v_rate = max(80_000.0, (budget_bits - a_rate * dur) / dur)
    if vbitrate > 0:
        v_rate = min(v_rate, float(vbitrate))
    out_fps = fps
    out_h = height

    def bpp() -> float:
        pixels = (width * out_h / height) * out_h
        return v_rate / (pixels * out_fps)

    if out_fps > 30.5 and bpp() < SMALL_BPP:
        out_fps = 30.0
    for h in SMALL_HEIGHTS:
        if bpp() >= SMALL_BPP:
            break
        if h < out_h:
            out_h = h
    return {
        "a_mode": a_mode, "a_rate": a_rate, "mono": mono,
        "v_rate": int(v_rate), "fps": out_fps, "height": out_h,
        "scale": out_h != height, "fps_change": out_fps != fps,
    }

class Fragment:
    """Zakres Ciachu w czasie pliku: [start, end) bez `holes`, czyli wykonanych Wycięć (ADR 0002).
    Czas Sekwencji (`seq`) to czas pliku minus dziury przed nim; czas w grafie ffmpeg (`graph`)
    to czas Sekwencji minus wejściowy -ss (`pre`)."""

    def __init__(self, start: float, end: float, holes=None):
        self.start = float(start)
        self.end = float(end)
        hs: list[tuple[float, float]] = []
        for h in holes or []:
            try:
                a, b = max(self.start, float(h[0])), min(self.end, float(h[1]))
            except (TypeError, ValueError, IndexError):
                continue
            if b - a > 1e-6:
                hs.append((a, b))
        hs.sort()
        merged: list[tuple[float, float]] = []
        for a, b in hs:
            if merged and a <= merged[-1][1] + 1e-6:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        self.holes = merged
        self.pre = max(0.0, self.start - 3.0)

    @property
    def dur(self) -> float:
        return self.end - self.start - sum(b - a for a, b in self.holes)

    def segments(self) -> list[tuple[float, float]]:
        """Zachowane odcinki [a, b) pliku wewnątrz Fragmentu, po kolei."""
        out: list[tuple[float, float]] = []
        t = self.start
        for a, b in self.holes:
            if a - t > 1e-6:
                out.append((t, a))
            t = b
        if self.end - t > 1e-6:
            out.append((t, self.end))
        return out

    def seq(self, t: float) -> float:
        s = t
        for a, b in self.holes:
            if t >= b:
                s -= b - a
            elif t > a:
                s -= t - a
        return s

    def graph(self, t: float) -> float:
        return self.seq(t) - self.pre

    def cut_filters(self) -> list[str]:
        """Obraz: `select` zostawia tylko klatki z zachowanych odcinków (ten sam zapas 0,5 ms co
        cięcie: klatka o znaczniku `a` wchodzi, `b` nie), `setpts` dosuwa klatki za każdą dziurą
        o jej długość, żeby znaczniki były ciągłe (inaczej vfr zostawiłby zamrożony obraz)."""
        if not self.holes:
            return []
        eps = 0.0005
        sel = "+".join(f"between(t,{a - self.pre - eps:.6f},{b - self.pre - eps:.6f})" for a, b in self.segments())
        shift = "+".join(f"gte(T,{b - self.pre - eps:.6f})*{b - a:.6f}" for a, b in self.holes)
        return [f"select='{sel}'", f"setpts='PTS-({shift})/TB'"]


class Media:
    """Stan jednego wczytanego pliku. `gen` odróżnia kolejne pliki."""

    def __init__(self, path: str, gen: int):
        self.path = path
        self.gen = gen
        self.name = os.path.basename(path)
        self.ext = os.path.splitext(path)[1].lower()
        self.size = os.path.getsize(path)
        self.mime = "video/mp4" if self.ext == ".mp4" else "audio/mpeg"
        self.kind = "video"
        self.duration = 0.0
        self.start_time = 0.0
        self.fps = 0.0
        self.frame_step = 0.0
        self.width = 0
        self.height = 0
        self.vcodec = ""
        self.pix_fmt = ""
        self.acodec = ""
        self.audio_streams = 0
        self.sample_rate = 0
        self.channels = 0
        self.sig: tuple | None = None  # sygnatura pierwszego Nagrania Sekwencji (patrz signature)
        self.vbitrate = 0
        self.abitrate = 0
        self.frames: bytes | None = None
        self.wave: bytes | None = None
        self.procs: list[subprocess.Popen] = []
        self.dead = False
        # Sekwencja (ADR 0002): `copies` to pliki źródłowe sklejone w tym pliku, po kolei
        # ({"path", "name", "duration", "start"}; `start` = gdzie kopia zaczyna się w tym pliku),
        # a `parts` to Nagrania: ciągłe kawałki kopii ({"src": indeks kopii, "in", "out"} w sekundach
        # pliku źródłowego). Wycięcie dzieli kawałek na dwa; to, czego nie ma w `parts`, jest dziurą,
        # której timeline, odtwarzanie i Ciach nie pokazują. Zwykłe Nagranie = jedna kopia, jeden
        # kawałek. `display_name` to nazwa pierwszego Nagrania (tytuł okna, nazwa wyniku).
        self.copies: list[dict] = [{"path": path, "name": self.name, "duration": 0.0, "start": 0.0}]
        self.parts: list[dict] = [{"src": 0, "in": 0.0, "out": 0.0}]
        self.display_name = self.name

    def probe(self):
        cp = run([FFPROBE, "-v", "error", "-show_format", "-show_streams", "-of", "json", self.path])
        if cp.returncode != 0:
            raise MediaError("ffprobe: " + cp.stderr.decode("utf-8", "replace").strip()[:300])
        data = json.loads(cp.stdout.decode("utf-8", "replace") or "{}")
        streams = data.get("streams", [])
        fmt = data.get("format", {})
        video = [
            s
            for s in streams
            if s.get("codec_type") == "video"
            and not int((s.get("disposition") or {}).get("attached_pic", 0) or 0)
        ]
        audio = [s for s in streams if s.get("codec_type") == "audio"]
        self.audio_streams = len(audio)
        self.abitrate = int(float((audio[0].get("bit_rate") if audio else 0) or 0))
        self.acodec = (audio[0].get("codec_name") if audio else "") or ""
        self.sample_rate = int((audio[0].get("sample_rate") if audio else 0) or 0)
        self.channels = int((audio[0].get("channels") if audio else 0) or 0)
        self.duration = float(fmt.get("duration") or 0.0)
        self.start_time = max(0.0, float(fmt.get("start_time") or 0.0))
        if video and self.ext == ".mp4":
            v = video[0]
            self.kind = "video"
            self.vcodec = v.get("codec_name", "")
            self.pix_fmt = v.get("pix_fmt", "") or ""
            self.width = int(v.get("width") or 0)
            self.height = int(v.get("height") or 0)
            fps = parse_rate(v.get("avg_frame_rate")) or parse_rate(v.get("r_frame_rate"))
            if fps <= 0:
                fps = 30.0
            self.fps = fps
            self.frame_step = 1.0 / fps
            self.vbitrate = int(float(v.get("bit_rate") or 0))
            if not self.vbitrate:
                self.vbitrate = max(0, int(float(fmt.get("bit_rate") or 0)) - self.abitrate)
            if not self.duration:
                self.duration = float(v.get("duration") or 0.0)
        elif audio:
            a = audio[0]
            self.kind = "audio"
            self.sample_rate = int(a.get("sample_rate") or 44100)
            self.width = self.height = 0
            spf = 1152 if self.sample_rate >= 32000 else 576
            self.frame_step = spf / self.sample_rate
            self.fps = 1.0 / self.frame_step
            if not self.duration:
                self.duration = float(a.get("duration") or 0.0)
        else:
            raise MediaError("Plik nie zawiera obrazu ani dźwięku.")
        if self.duration <= 0:
            raise MediaError("Nie udało się odczytać długości pliku.")
        self.copies[0]["duration"] = self.duration
        self.parts[0]["out"] = self.duration

    def signature(self) -> tuple:
        """Parametry, które muszą się zgadzać, żeby Nagrania dało się skleić bez przekodowania.
        Bez fps: concat kopiuje pakiety z ich czasami, a eksport trzyma bazę czasu z kontenera
        (`-enc_time_base demux`), więc sklejka 30 + 60 fps jest po prostu zmiennoklatkowa.
        Dla Sekwencji sygnatura pochodzi z pierwszego Nagrania (`sig`), nie z pliku tymczasowego,
        którego wyliczane pola (np. średni fps) różnią się od źródeł."""
        if self.sig:
            return self.sig
        return (self.kind, self.ext, self.vcodec, self.width, self.height, self.pix_fmt,
                self.audio_streams, self.acodec, self.sample_rate, self.channels)

    def describe(self) -> str:
        kind, ext, vcodec, w, h, pix, n_a, acodec, sr, ch = self.signature()
        audio = f"{n_a}x {acodec} {sr} Hz {ch} kan." if n_a else "bez audio"
        if kind == "video":
            return f"{w}x{h} {vcodec} {pix}, {audio}"
        return audio

    def info(self) -> dict:
        return {
            "gen": self.gen,
            "name": self.display_name,
            "kind": self.kind,
            "duration": self.duration,
            "fps": self.fps,
            "frameStep": self.frame_step,
            "width": self.width,
            "height": self.height,
            "vcodec": self.vcodec,
            "audioStreams": self.audio_streams,
            "waveBinSec": WAVE_BIN / WAVE_RATE,
            "parts": [{"name": self.copies[p["src"]]["name"], "duration": self.copies[p["src"]]["duration"],
                       "start": self.copies[p["src"]]["start"], "src": p["src"], "in": p["in"], "out": p["out"]}
                      for p in self.parts],
        }

    def piece_range(self, p: dict) -> tuple[float, float]:
        """Zakres kawałka w czasie tego pliku: [początek, koniec)."""
        c = self.copies[p["src"]]
        return c["start"] + p["in"], c["start"] + p["out"]

    def kill(self):
        self.dead = True
        for p in self.procs:
            try:
                p.kill()
            except Exception:
                pass


class App:
    def __init__(self):
        self.window: webview.Window | None = None
        self.lock = threading.Lock()
        self.media: Media | None = None
        self.gen = 0
        self.port = 0
        self.encoder: str | None = None  # 'nvenc' | 'x264'
        self.encoder_ready = threading.Event()
        self.export_proc: subprocess.Popen | None = None
        self.export_out: str | None = None
        self.export_tmp: str | None = None
        self.export_active = False
        self.ui_ready = False
        self.pending_path: str | None = None
        # Podkłady: osobne Media (mp3) pod Sekwencją, po gen. Sklejanie Sekwencji: pliki
        # tymczasowe w `seq_dir`, proces ffmpeg w `join_proc`, blokada `joining`.
        self.podklady: dict[int, Media] = {}
        self.seq_dir: str | None = None
        self.join_proc: subprocess.Popen | None = None
        self.joining = False

    def find_media(self, gen: int) -> Media | None:
        m = self.media
        if m and m.gen == gen:
            return m
        return self.podklady.get(gen)

    # ---------- komunikacja z JS ----------
    def emit(self, event: str, **data):
        if not self.window:
            return
        payload = json.dumps({"type": event, **data}, ensure_ascii=False)
        try:
            self.window.run_js(f"window.ciachEvent && window.ciachEvent({payload});")
        except Exception:
            pass

    def set_title(self, title: str):
        if self.window:
            try:
                self.window.set_title(title)
            except Exception:
                pass

    # ---------- wczytywanie ----------
    @staticmethod
    def check_path(path: str) -> str | None:
        ext = os.path.splitext(path)[1].lower()
        if ext not in ALLOWED_EXT:
            return "Obsługiwane są tylko pliki MP4 i MP3."
        if not os.path.isfile(path):
            return "Nie znaleziono pliku."
        return None

    def probe_new(self, path: str) -> Media:
        """Nowe Media z kolejnym gen, sprobowane. Rzuca MediaError."""
        path = os.path.abspath(path)
        err = self.check_path(path)
        if err:
            raise MediaError(err)
        with self.lock:
            self.gen += 1
            media = Media(path, self.gen)
        try:
            media.probe()
        except MediaError:
            raise
        except Exception as e:  # noqa: BLE001
            raise MediaError(f"Nie udało się odczytać pliku: {e}") from e
        return media

    def title_for(self, m: Media) -> str:
        extra = f" +{len(m.parts) - 1}" if len(m.parts) > 1 else ""
        return f"{APP_NAME} – {m.display_name}{extra}"

    def load(self, path: str):
        """Podmiana całej sesji: nowe Nagranie, bez Podkładów i bez Sekwencji."""
        if self.joining:
            self.emit("reject", message="Poczekaj na sklejanie.")
            return
        try:
            media = self.probe_new(path)
        except MediaError as e:
            self.emit("reject", message=str(e))
            return
        self.clear_podklady()
        self.install_media(media, reason="open")

    def install_media(self, media: Media, reason: str):
        """Ustawia `media` jako bieżącą Sekwencję i uruchamia skany. `reason`: open | join | remove."""
        with self.lock:
            old = self.media
            self.media = media
        if old:
            old.kill()
        self.set_title(self.title_for(media))
        self.emit("loaded", info=media.info(), reason=reason)
        threading.Thread(target=self.scan_frames, args=(media,), daemon=True).start()
        threading.Thread(target=self.scan_wave, args=(media,), daemon=True).start()
        if old:
            self.drop_temp(old)

    # ---------- Sekwencja ----------
    def temp_dir(self) -> str:
        if not self.seq_dir or not os.path.isdir(self.seq_dir):
            self.seq_dir = tempfile.mkdtemp(prefix="ciach_seq_")
        return self.seq_dir

    def is_temp(self, path: str) -> bool:
        return bool(self.seq_dir) and os.path.dirname(os.path.abspath(path)) == self.seq_dir

    def drop_temp(self, m: Media):
        if self.is_temp(m.path):
            threading.Thread(target=self._remove, args=(m.path,), daemon=True).start()

    def join(self, paths: list[str], index: int):
        """Wstawia Nagrania `paths` do Sekwencji przed kawałek `index` (0 = na początek,
        len(parts) = na koniec) i skleja całość bez przekodowania do pliku tymczasowego.
        Kawałki zostają kawałkami: sąsiednie kawałki tej samej kopii idą do pliku jako jedna
        kopia, a wstawienie między dwa kawałki jednej kopii dubluje ją (ADR 0002)."""
        base = self.media
        if not base:
            self.load(paths[0])
            return
        if self.joining or self.export_active:
            self.emit("reject", message="Poczekaj na zakończenie bieżącej operacji.")
            return
        self.joining = True
        try:
            new: list[Media] = []
            for p in paths:
                m = self.probe_new(p)
                if m.signature() != base.signature():
                    raise MediaError(f"{m.name}: inne parametry ({m.describe()}) niż Sekwencja ({base.describe()}).")
                new.append(m)
            with self.lock:
                pieces = [dict(p) for p in base.parts]
                old_copies = base.copies
            index = max(0, min(int(index), len(pieces)))
            entries: list[dict] = []  # {"copy", "src", "pieces"}

            def add_new():
                for m in new:
                    entries.append({"copy": {"path": m.path, "name": m.name, "duration": m.duration, "start": 0.0},
                                    "src": None, "pieces": [{"in": 0.0, "out": m.duration, "old": None}]})

            for i, pc in enumerate(pieces):
                if i == index:
                    add_new()
                piece = {"in": pc["in"], "out": pc["out"], "old": i}
                if entries and entries[-1]["src"] is not None and entries[-1]["src"] == pc["src"]:
                    entries[-1]["pieces"].append(piece)
                else:
                    entries.append({"copy": dict(old_copies[pc["src"]]), "src": pc["src"], "pieces": [piece]})
            if index == len(pieces):
                add_new()
            copies: list[dict] = []
            parts: list[dict] = []
            remap: list[list[float]] = []
            t = 0.0
            for e_i, e in enumerate(entries):
                c = e["copy"]
                c["start"] = t
                copies.append(c)
                for piece in e["pieces"]:
                    parts.append({"src": e_i, "in": piece["in"], "out": piece["out"]})
                    if piece["old"] is not None:
                        old_start = old_copies[pieces[piece["old"]]["src"]]["start"]
                        remap.append([old_start + piece["in"], old_start + piece["out"], t - old_start])
                t += c["duration"]
            self.build_sequence(base, copies, parts, reason="join",
                                inserted=(index, sum(m.duration for m in new)), remap=remap)
        except MediaError as e:
            self.emit("join", state="error", message=str(e))
        finally:
            self.joining = False

    def set_parts(self, parts) -> dict:
        """Nowy skład Nagrań z UI (po Wycięciu, usunięciu Nagrania albo Cofnięciu): lista
        {"src", "in", "out"} po kolei. Plik tymczasowy zostaje, zmienia się tylko lista kawałków."""
        with self.lock:
            m = self.media
            if not m or not isinstance(parts, list):
                return {"ok": False, "message": "Brak Sekwencji."}
            clean: list[dict] = []
            prev_end = -1.0
            for p in parts:
                try:
                    src = int(p["src"])
                    a, b = float(p["in"]), float(p["out"])
                except (KeyError, TypeError, ValueError):
                    return {"ok": False, "message": "Zły opis Nagrania."}
                if not (0 <= src < len(m.copies)):
                    return {"ok": False, "message": "Zły opis Nagrania."}
                c = m.copies[src]
                a = max(0.0, min(a, c["duration"]))
                b = max(a, min(b, c["duration"]))
                if b - a <= 0 or c["start"] + a < prev_end - 1e-6:
                    return {"ok": False, "message": "Nagrania nachodzą na siebie."}
                prev_end = c["start"] + b
                clean.append({"src": src, "in": a, "out": b})
            if not clean:
                return {"ok": False, "message": "Sekwencja nie może być pusta."}
            m.parts = clean
        self.set_title(self.title_for(m))
        return {"ok": True}

    def build_sequence(self, base: Media, copies: list[dict], parts: list[dict], reason: str, **extra):
        t = 0.0
        for c in copies:
            c["start"] = t
            t += c["duration"]
        total = t
        if len(copies) == 1:
            media = self.probe_new(copies[0]["path"])
        else:
            with self.lock:
                self.gen += 1
                gen = self.gen
            out = os.path.join(self.temp_dir(), f"seq_{gen}{base.ext}")
            lst = os.path.join(self.temp_dir(), f"seq_{gen}.txt")
            with open(lst, "w", encoding="utf-8") as f:
                for c in copies:
                    f.write("file '" + c["path"].replace("'", r"'\''") + "'\n")
            cmd = [FFMPEG, "-y", "-hide_banner", "-v", "error", "-nostats", "-progress", "pipe:1",
                   "-f", "concat", "-safe", "0", "-i", lst, "-map", "0", "-c", "copy"]
            if base.ext == ".mp4":
                cmd += ["-movflags", "+faststart"]
            else:
                cmd += ["-map_metadata", "0", "-id3v2_version", "3"]
            cmd.append(out)
            self.emit("join", state="progress", percent=0)
            rc, err = self.run_ffmpeg(cmd, total, lambda pct: self.emit("join", state="progress", percent=round(pct)),
                                      attr="join_proc")
            self._remove(lst)
            if rc != 0 or not os.path.isfile(out):
                self._remove(out)
                self.write_error_log(cmd, rc, err)
                msg = (err.strip().splitlines() or ["ffmpeg zakończył się błędem"])[-1][:200]
                raise MediaError("Sklejanie nie powiodło się: " + msg)
            media = Media(out, gen)
            try:
                media.probe()
            except Exception as e:  # noqa: BLE001
                self._remove(out)
                raise MediaError(f"Sklejony plik jest uszkodzony: {e}") from e
        media.copies = copies
        media.parts = parts
        media.display_name = copies[0]["name"]
        media.sig = base.signature()
        self.emit("join", state="done", reason=reason, **extra)
        self.install_media(media, reason=reason)

    # ---------- Podkłady ----------
    def add_podklad(self, path: str):
        base = self.media
        if not base or base.kind != "video":
            self.emit("reject", message="Podkład można dodać tylko pod Sekwencję wideo.")
            return
        if os.path.splitext(path)[1].lower() != ".mp3":
            self.emit("reject", message="Podkładem może być tylko plik MP3.")
            return
        try:
            m = self.probe_new(path)
        except MediaError as e:
            self.emit("reject", message=str(e))
            return
        if m.kind != "audio" or m.audio_streams == 0:
            self.emit("reject", message="Podkład nie zawiera dźwięku.")
            return
        with self.lock:
            self.podklady[m.gen] = m
        self.emit("podklad", info=m.info())
        threading.Thread(target=self.scan_wave, args=(m,), daemon=True).start()

    def remove_podklad(self, gen: int):
        with self.lock:
            m = self.podklady.pop(int(gen), None)
        if m:
            m.kill()

    def clear_podklady(self):
        with self.lock:
            olds = list(self.podklady.values())
            self.podklady.clear()
        for m in olds:
            m.kill()

    def scan_frames(self, m: Media):
        sel = "v:0" if m.kind == "video" else "a:0"
        cmd = [FFPROBE, "-v", "error", "-select_streams", sel,
               "-show_entries", "packet=pts_time", "-of", "csv=p=0", m.path]
        try:
            p = popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            return
        m.procs.append(p)
        vals = []
        assert p.stdout is not None
        for line in p.stdout:
            s = line.strip()
            if not s or s == b"N/A":
                continue
            try:
                vals.append(float(s))
            except ValueError:
                pass
        p.wait()
        if m.dead or p.returncode != 0 or len(vals) < 2:
            return
        arr = np.unique(np.asarray(vals, dtype=np.float64)) - m.start_time
        arr = arr[arr >= -1e-6]
        arr[arr < 0] = 0.0
        arr = arr[arr < m.duration + 1e-6]
        if len(arr) < 2:
            return
        m.frames = arr.astype("<f8").tobytes()
        if not m.dead:
            self.emit("frames", gen=m.gen, count=len(arr))

    def scan_wave(self, m: Media):
        n = m.audio_streams
        if n == 0:
            m.wave = b""
            self.emit("wave", gen=m.gen)
            return
        cmd = [FFMPEG, "-v", "error", "-i", m.path]
        if n > 1:
            inputs = "".join(f"[0:a:{i}]" for i in range(n))
            cmd += ["-filter_complex", f"{inputs}amix=inputs={n}:normalize=0[m]", "-map", "[m]"]
        else:
            cmd += ["-map", "0:a:0"]
        cmd += ["-ac", "1", "-ar", str(WAVE_RATE), "-f", "s16le", "-"]
        try:
            p = popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            return
        m.procs.append(p)
        assert p.stdout is not None
        chunk_bytes = WAVE_BIN * 2 * 8000  # 8000 binów = 40 s na porcję
        peaks: list[np.ndarray] = []
        rmss: list[np.ndarray] = []
        rest = b""
        while True:
            buf = p.stdout.read(chunk_bytes)
            if not buf:
                break
            buf = rest + buf
            usable = len(buf) - (len(buf) % (WAVE_BIN * 2))
            rest = buf[usable:]
            if usable:
                a = np.frombuffer(buf[:usable], dtype="<i2").astype(np.float32) / 32768.0
                a = a.reshape(-1, WAVE_BIN)
                peaks.append(np.abs(a).max(axis=1))
                rmss.append(np.sqrt((a * a).mean(axis=1)))
            if m.dead:
                break
        p.wait()
        if m.dead:
            return
        if rest:
            a = np.frombuffer(rest[: len(rest) - len(rest) % 2], dtype="<i2").astype(np.float32) / 32768.0
            if len(a):
                peaks.append(np.array([np.abs(a).max()], dtype=np.float32))
                rmss.append(np.array([np.sqrt((a * a).mean())], dtype=np.float32))
        if not peaks:
            m.wave = b""
        else:
            pk = np.concatenate(peaks)
            rm = np.concatenate(rmss)
            out = np.empty(len(pk) * 2, dtype=np.uint8)
            out[0::2] = np.clip(pk * 255.0, 0, 255).astype(np.uint8)
            out[1::2] = np.clip(rm * 255.0, 0, 255).astype(np.uint8)
            m.wave = out.tobytes()
        self.emit("wave", gen=m.gen)

    # ---------- enkoder ----------
    def detect_encoder(self):
        enc = "x264"
        try:
            cp = run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:r=30:d=0.2",
                      *NVENC_ARGS, "-f", "null", "-"], timeout=30)
            if cp.returncode == 0:
                enc = "nvenc"
        except Exception:
            pass
        self.encoder = enc
        self.encoder_ready.set()

    # ---------- eksport ----------
    def start_export(self, start: float, end: float, mode: str = "full", mix: dict | None = None,
                     holes=None) -> dict:
        """`mix`: {"gain": Głośność Sekwencji 0..1, "podklady": [{"gen", "at", "segs" | "tin"/"tout", "gain"}],
        "zblizenia": [...]}. `at` = czas pliku, w którym zaczyna się Podkład; `segs` = odcinki mp3 grane
        po kolei. `holes`: [[a, b], ...] wykonane Wycięcia w czasie pliku wewnątrz [start, end)."""
        with self.lock:
            if self.export_active:
                return {"ok": False, "message": "Eksport już trwa."}
            if self.joining:
                return {"ok": False, "message": "Poczekaj na sklejanie."}
            m = self.media
            if not m:
                return {"ok": False, "message": "Brak pliku."}
            fr = Fragment(start, end, holes)
            if fr.dur <= 0:
                return {"ok": False, "message": "Pusty zakres."}
            zooms = self.resolve_zoom(m, (mix or {}).get("zblizenia"), fr)
            mix = self.resolve_mix(m, mix or {})
            if fr.holes and mix is None and m.kind == "video":
                # dziury w dźwięku da się wyciąć tylko filtrem, więc idzie przez tor miksu (jedna ścieżka AAC)
                mix = {"gain": 1.0, "podklady": []}
            self.export_active = True
        target = self.run_small_export if mode == "small" else self.run_export
        threading.Thread(target=target, args=(m, fr, mix, zooms), daemon=True).start()
        return {"ok": True}

    @staticmethod
    def kadr(k) -> dict:
        """Kadr: prostokąt w proporcjach obrazu, jako ułamki szerokości/wysokości (x, y, s)."""
        k = k if isinstance(k, dict) else {}
        s_ = max(KADR_MIN, min(1.0, float(k.get("s", 1.0))))
        x = max(0.0, min(1.0 - s_, float(k.get("x", 0.0))))
        y = max(0.0, min(1.0 - s_, float(k.get("y", 0.0))))
        return {"x": x, "y": y, "s": s_}

    def resolve_zoom(self, m: Media, spec, fr: "Fragment | None" = None) -> list[dict]:
        """Zbliżenia z UI: [{at, end, rin, rout, keys: [{t, x, y, s}]}]; `at`, `end`, `t` w sekundach pliku
        (pts Klatek), Rampy w sekundach Sekwencji; `keys` to pozycje Kadru zapamiętane na Klatkach.
        Odrzuca puste i porządkuje po czasie; nachodzące na siebie UI nie wysyła, ale na wszelki
        wypadek późniejsze z nachodzącej pary jest pomijane."""
        out: list[dict] = []
        if m.kind != "video" or not m.width or not isinstance(spec, list):
            return out
        seq = fr.seq if fr else (lambda t: t)
        for z in spec:
            try:
                at, end = float(z["at"]), float(z["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if end - at <= 0:
                continue
            rin = max(0.0, float(z.get("rin", 0.0) or 0.0))
            rout = max(0.0, float(z.get("rout", 0.0) or 0.0))
            length = seq(end) - seq(at)
            if rin + rout > length:
                k = length / (rin + rout) if rin + rout > 0 else 0.0
                rin, rout = rin * k, rout * k
            keys: dict[float, dict] = {}
            for q in z.get("keys") or []:
                try:
                    t = max(at, min(end, float(q["t"])))
                except (KeyError, TypeError, ValueError):
                    continue
                keys[round(t, 6)] = self.kadr(q)
            if not keys:
                continue
            out.append({"at": at, "end": end, "rin": rin, "rout": rout,
                        "keys": [{"t": t, "k": keys[t]} for t in sorted(keys)]})
        out.sort(key=lambda z: z["at"])
        clean: list[dict] = []
        for z in out:
            if clean and z["at"] < clean[-1]["end"] - 1e-6:
                continue
            clean.append(z)
        return clean

    @staticmethod
    def kadr_keys(z: dict, t: float, seq=None) -> dict:
        """Kadr z zapamiętanych pozycji: przed pierwszą i za ostatnią stoi, między dwiema liniowo
        w czasie Sekwencji (`seq`: czas pliku → czas Sekwencji; dziury po Wycięciach nie liczą się)."""
        ks = z["keys"]
        if t <= ks[0]["t"] + 1e-9:
            return ks[0]["k"]
        if t >= ks[-1]["t"] - 1e-9:
            return ks[-1]["k"]
        i = 0
        while i + 1 < len(ks) and ks[i + 1]["t"] <= t + 1e-9:
            i += 1
        a, b = ks[i], ks[i + 1]
        s_ = seq or (lambda x: x)
        span = s_(b["t"]) - s_(a["t"])
        f = (s_(t) - s_(a["t"])) / span if span > 1e-9 else 1.0
        f = max(0.0, min(1.0, f))
        return {q: a["k"][q] + (b["k"][q] - a["k"][q]) * f for q in ("x", "y", "s")}

    @staticmethod
    def ramp_factor(z: dict, t: float, seq=None) -> float:
        s_ = seq or (lambda x: x)
        L, u = s_(z["end"]) - s_(z["at"]), s_(t) - s_(z["at"])
        if z["rin"] > 0 and u < z["rin"]:
            return max(0.0, min(1.0, u / z["rin"]))
        if z["rout"] > 0 and u > L - z["rout"]:
            return max(0.0, min(1.0, (L - u) / z["rout"]))
        return 1.0

    @staticmethod
    def file_time(fr: "Fragment", s: float) -> float:
        """Odwrotność Fragment.seq: czas pliku dla czasu Sekwencji (na szwie: za dziurą)."""
        t = s
        for a, b in fr.holes:
            if t >= a - 1e-9:
                t += b - a
        return t

    @classmethod
    def zoom_commands(cls, zooms: list[dict], pre: float, width: int, height: int,
                      fr: "Fragment | None" = None) -> str:
        """Plik dla filtra sendcmd: odcinki Zbliżeń jako polecenia dla `crop` (patrz
        agent_docs/export_pipeline.md). Czas w grafie to czas pliku minus `pre` (wejściowy
        -ss; sendcmd stoi przed `select`, więc dziury Wycięć są jeszcze na osi), z tym samym
        zapasem 0,5 ms co przy cięciu. Odcinek ze stałym Kadrem to jedno polecenie `[enter]`,
        odcinek z ruchem to `[expr]` liczone dla każdej klatki z TI (0..1 w obrębie odcinka).
        Kadr między pozycjami i współczynnik Rampy są liniowe w czasie Sekwencji, a w odcinku
        bez dziury czas Sekwencji jest liniowy w TI, więc ich złożenie jest kwadratowe:
        `c0+c1*TI+c2*TI*TI`; granice dziur są punktami podziału. Bez przecinków w wyrażeniach:
        przecinek rozdziela polecenia."""
        full = (float(width), float(height), 0.0, 0.0)
        seq = fr.seq if fr else None

        def px(k):
            return (width * k["s"], height * k["s"], width * k["x"], height * k["y"])

        def seen(z, t):
            """(w, h, x, y) widziane w chwili t: Kadr z pozycji rozciągnięty Rampą w stronę całości."""
            b = px(cls.kadr_keys(z, t, seq))
            f = cls.ramp_factor(z, t, seq)
            return tuple(fv + (bv - fv) * f for fv, bv in zip(full, b))

        def seg(t0, t1, v0, v1, mid):
            if t1 - t0 <= 1e-9:
                return None
            a, b = f"{t0 - pre - ZOOM_EPS:.6f}", f"{t1 - pre - ZOOM_EPS:.6f}"
            names = ("w", "h", "x", "y")
            if all(abs(p - q) < 1e-6 and abs(p - r) < 1e-6 for p, q, r in zip(v0, v1, mid)):
                return f"{a}-{b} " + ", ".join(f"[enter] crop {n} {v:.2f}" for n, v in zip(names, v0)) + ";"
            parts = []
            for n, p0, p1, pm in zip(names, v0, v1, mid):
                # kwadrat przez trzy punkty TI = 0, 0.5, 1
                c2 = 2 * (p1 - 2 * pm + p0)
                c1 = p1 - p0 - c2
                parts.append(f"[expr] crop {n} '{p0:.2f}+{c1:.2f}*TI+{c2:.2f}*TI*TI'")
            return f"{a}-{b} " + ", ".join(parts) + ";"

        lines: list[str] = []
        for i, z in enumerate(zooms):
            at, end = z["at"], z["end"]
            pts = {at, end}
            pts |= {q["t"] for q in z["keys"] if at < q["t"] < end}
            if fr:
                for a, b in fr.holes:
                    pts |= {x for x in (a, b) if at < x < end}
                # końce Ramp w czasie pliku: tyle sekund Sekwencji od Krawędzi, dziury pominięte
                pts |= {x for x in (cls.file_time(fr, fr.seq(at) + z["rin"]),
                                    cls.file_time(fr, fr.seq(end) - z["rout"])) if at < x < end}
            else:
                pts |= {x for x in (at + z["rin"], end - z["rout"]) if at < x < end}
            pts_s = sorted(pts)
            for t0, t1 in zip(pts_s, pts_s[1:]):
                part = seg(t0, t1, seen(z, t0), seen(z, t1), seen(z, (t0 + t1) / 2))
                if part:
                    lines.append(part)
            nxt = zooms[i + 1]["at"] if i + 1 < len(zooms) else end + 1e9
            if nxt - end > 1e-6:
                lines.append(seg(end, nxt, full, full, full))
        return "\n".join(lines) + "\n"

    def write_zoom_file(self, tmp: str, zooms: list[dict], m: Media, fr: "Fragment") -> str:
        path = os.path.join(tmp, ZOOM_CMD)
        with open(path, "w", encoding="ascii") as f:
            f.write(self.zoom_commands(zooms, fr.pre, m.width, m.height, fr))
        return path

    @staticmethod
    def zoom_chain(out_w: int, out_h: int) -> list[str]:
        """Łańcuch wideo Zbliżenia: sendcmd steruje crop per klatka, scale wyrównuje do stałego
        rozmiaru wyjścia (scale jako jedyny filtr przyjmuje zmienny rozmiar klatek wejściowych)."""
        return [f"sendcmd=f={ZOOM_CMD}", "crop=w=iw:h=ih:x=0:y=0", f"scale={out_w}:{out_h}"]

    def resolve_mix(self, m: Media, mix: dict) -> dict | None:
        """Zamienia gen Podkładów na ścieżki i odrzuca miks, który nic nie zmienia (kopia 1:1).
        Podkład ma `segs` (odcinki mp3 grane po kolei, po Wycięciach) albo starsze `tin`/`tout`."""
        gain = float(mix.get("gain", 1.0))
        gain = max(0.0, min(1.0, gain))
        pods = []
        for p in mix.get("podklady") or []:
            pm = self.podklady.get(int(p.get("gen", 0)))
            if not pm:
                continue
            raw = p.get("segs")
            if not isinstance(raw, list):
                raw = [[p.get("tin", 0.0), p.get("tout", pm.duration)]]
            segs: list[tuple[float, float]] = []
            for sg in raw:
                try:
                    tin, tout = float(sg[0]), float(sg[1])
                except (TypeError, ValueError, IndexError):
                    continue
                tin = max(0.0, min(tin, pm.duration))
                tout = max(tin, min(tout, pm.duration))
                if tout - tin > 0:
                    segs.append((tin, tout))
            if not segs:
                continue
            pods.append({"path": pm.path, "at": float(p.get("at", 0.0)), "segs": segs,
                         "gain": max(0.0, min(1.0, float(p.get("gain", 1.0))))})
        if m.kind != "video" or (abs(gain - 1.0) < 1e-6 and not pods):
            return None
        return {"gain": gain, "podklady": pods}

    @staticmethod
    def mix_filters(m: Media, fr: "Fragment", mix: dict) -> tuple[list[str], list[str], str]:
        """Graf miksu: dźwięk Sekwencji (wejście 0, przesunięte o `pre` przez wejściowy -ss) plus
        Podkłady jako kolejne wejścia. Z dziurami dźwięk Sekwencji to odcinki `atrim` sklejone
        `concat` (próbka po próbce; pierwszy odcinek zaczyna się w `pre`, żeby wyjściowy -ss
        ciął dźwięk i obraz w tym samym miejscu). Zwraca (argumenty wejść, filtry, etykietę)."""
        inputs: list[str] = []
        filters: list[str] = []
        chains: list[str] = []
        pre = fr.pre
        n = m.audio_streams
        if n > 0:
            src = "".join(f"[0:a:{i}]" for i in range(n))
            f = f"amix=inputs={n}:normalize=0," if n > 1 else ""
            segs = fr.segments() if fr.holes else []
            if len(segs) > 1:
                K = len(segs)
                filters.append(f"{src}{f}asplit={K}" + "".join(f"[c{k}]" for k in range(K)))
                for k, (a, b) in enumerate(segs):
                    t0 = 0.0 if k == 0 else a - pre
                    filters.append(f"[c{k}]atrim=start={t0:.6f}:end={b - pre:.6f},asetpts=PTS-STARTPTS[d{k}]")
                filters.append("".join(f"[d{k}]" for k in range(K)) + f"concat=n={K}:v=0:a=1,volume={mix['gain']:.4f}[a0]")
            else:
                filters.append(f"{src}{f}volume={mix['gain']:.4f}[a0]")
            chains.append("[a0]")
        idx = 1
        s_start, s_end = fr.seq(fr.start), fr.seq(fr.end)
        for p in mix["podklady"]:
            # Czas pliku `at` odpowiada w grafie czasowi Sekwencji minus `pre` (wejście 0 zaczyna
            # się w `pre`, dziury są już wycięte). Podkład gra ciągle także przez szwy Wycięć.
            at = fr.graph(p["at"])
            segs = [list(sg) for sg in p["segs"]]
            total = sum(b - a for a, b in segs)
            if at < 0:
                skip = -at
                while segs and skip > 0:
                    ln = segs[0][1] - segs[0][0]
                    if ln <= skip:
                        skip -= ln
                        segs.pop(0)
                    else:
                        segs[0][0] += skip
                        skip = 0
                at = 0.0
            if not segs or fr.seq(p["at"]) >= s_end or fr.seq(p["at"]) + total <= s_start:
                continue
            inputs += ["-i", p["path"]]
            delay = int(round(at * 1000))
            tail = f"adelay={delay}|{delay},volume={p['gain']:.4f}[a{idx}]"
            if len(segs) == 1:
                tin, tout = segs[0]
                filters.append(f"[{idx}:a:0]atrim=start={tin:.6f}:end={tout:.6f},asetpts=PTS-STARTPTS,{tail}")
            else:
                K = len(segs)
                filters.append(f"[{idx}:a:0]asplit={K}" + "".join(f"[p{idx}_{k}]" for k in range(K)))
                for k, (tin, tout) in enumerate(segs):
                    filters.append(f"[p{idx}_{k}]atrim=start={tin:.6f}:end={tout:.6f},asetpts=PTS-STARTPTS[q{idx}_{k}]")
                filters.append("".join(f"[q{idx}_{k}]" for k in range(K)) + f"concat=n={K}:v=0:a=1,{tail}")
            chains.append(f"[a{idx}]")
            idx += 1
        if not chains:
            filters.append("anullsrc=r=48000:cl=stereo[a]")
        elif len(chains) == 1:
            filters[-1] = filters[-1][: -len(chains[0])] + "[a]"
        else:
            dur = "first" if n > 0 else "longest"
            filters.append(f"{''.join(chains)}amix=inputs={len(chains)}:normalize=0:duration={dur}[a]")
        return inputs, filters, "[a]"

    @staticmethod
    def unique_out(stem: str, ext: str, suffix: str = "_ciach") -> str:
        cand = os.path.join(OUT_DIR, f"{stem}{suffix}{ext}")
        i = 2
        while os.path.exists(cand):
            cand = os.path.join(OUT_DIR, f"{stem}{suffix} ({i}){ext}")
            i += 1
        return cand

    @staticmethod
    def seek_args(m: Media, fr: "Fragment", extra_inputs: list[str] | None = None) -> list[str]:
        # Dwustopniowy seek (patrz agent_docs/export_pipeline.md). Wejścia Podkładów idą po
        # wejściu 0, a wyjściowy -ss/-t tnie wszystkie strumienie wyjściowe, także zmiksowane.
        # `-t` to długość bez dziur: za dziurami znaczniki są już dosunięte (setpts / concat).
        pre = fr.pre
        oss = max(0.0, fr.start - pre - 0.0005)
        return ["-ss", f"{pre:.6f}", "-i", m.path, *(extra_inputs or []), "-ss", f"{oss:.6f}", "-t", f"{fr.dur:.6f}"]

    def build_small_cmd(self, m: Media, fr: "Fragment", out: str, plan: dict,
                        pass_no: int, passlog: str, mix: dict | None = None, zoom: bool = False) -> list[str]:
        extra_inputs: list[str] = []
        mix_filters: list[str] = []
        mix_label = ""
        if mix and pass_no == 2:
            extra_inputs, mix_filters, mix_label = self.mix_filters(m, fr, mix)
        cmd = [FFMPEG, "-y", "-hide_banner", "-v", "error", "-nostats", "-progress", "pipe:1",
               *self.seek_args(m, fr, extra_inputs)]
        filters: list[str] = []
        vf: list[str] = []
        if zoom:
            # Zbliżenie skaluje od razu do rozmiaru z planu: crop daje klatki o zmiennym rozmiarze,
            # a `-2:h` liczyłoby szerokość dla każdej z osobna (raz 960, raz 958).
            oh = plan["height"] if plan["scale"] else m.height
            ow = int(round(m.width * oh / m.height / 2)) * 2
            vf += self.zoom_chain(ow, oh)
        vf += fr.cut_filters()
        if plan["fps_change"]:
            vf.append(f"fps={plan['fps']:g}")
        if plan["scale"] and not zoom:
            vf.append(f"scale=-2:{plan['height']}")
        if vf:
            filters.append(f"[0:v:0]{','.join(vf)}[v]")
            vmap = "[v]"
        else:
            vmap = "0:v:0"
        amap = None
        audio_args: list[str] = ["-an"]
        if pass_no == 2 and mix_label:
            filters += mix_filters
            amap = mix_label
            audio_args = ["-c:a", "aac", "-b:a", str(plan["a_rate"] or 160_000)]
            if plan["mono"]:
                audio_args += ["-ac", "1"]
        elif pass_no == 2 and plan["a_mode"] == "copy":
            amap, audio_args = "0:a:0", ["-c:a", "copy"]
        elif pass_no == 2 and plan["a_mode"] == "aac":
            n = m.audio_streams
            if n > 1:
                inputs = "".join(f"[0:a:{i}]" for i in range(n))
                filters.append(f"{inputs}amix=inputs={n}:normalize=0[a]")
                amap = "[a]"
            else:
                amap = "0:a:0"
            audio_args = ["-c:a", "aac", "-b:a", str(plan["a_rate"])]
            if plan["mono"]:
                audio_args += ["-ac", "1"]
        if filters:
            cmd += ["-filter_complex", ";".join(filters)]
        cmd += ["-map", vmap]
        if amap:
            cmd += ["-map", amap]
        cmd += ["-c:v", "libx264", "-preset", "slow", "-b:v", str(plan["v_rate"]), *VIDEO_TB,
                "-pix_fmt", "yuv420p", "-pass", str(pass_no), "-passlogfile", passlog]
        cmd += audio_args
        if pass_no == 1:
            cmd += ["-f", "null", os.devnull]
        else:
            cmd += ["-movflags", "+faststart", out]
        return cmd

    def build_small_mp3_cmd(self, m: Media, fr: "Fragment", out: str, rate: int) -> list[str]:
        return [FFMPEG, "-y", "-hide_banner", "-v", "error", "-nostats", "-progress", "pipe:1",
                *self.seek_args(m, fr), "-map", "0", "-c:v", "copy",
                "-c:a", "libmp3lame", "-b:a", str(rate), "-map_metadata", "0", "-id3v2_version", "3",
                "-avoid_negative_ts", "make_zero", out]

    def cut_mp3(self, m: Media, fr: "Fragment", tmp: str) -> tuple[Media, "Fragment"]:
        """Mp3 z Wycięciami: każdy zachowany odcinek kopiowany osobno (ten sam dwustopniowy seek co
        Ciach, ramka mp3 = Klatka, bez strat), potem sklejone concat demuxerem w `tmp/cut.mp3`
        z tagami z oryginału. Zwraca (Media wskazujące na sklejkę, Fragment 0..długość), na których
        działa zwykły tor mp3. Rzuca MediaError."""
        segs = fr.segments()
        names: list[str] = []
        for k, (a, b) in enumerate(segs):
            seg = os.path.join(tmp, f"seg{k}.mp3")
            cmd = [FFMPEG, "-y", "-hide_banner", "-v", "error", "-nostats", "-progress", "pipe:1",
                   *self.seek_args(m, Fragment(a, b)), "-map", "0:a:0", "-c", "copy", "-write_xing", "0",
                   "-avoid_negative_ts", "make_zero", seg]
            rc, err = self.run_ffmpeg_export(cmd, b - a, m, lambda pct: None)
            if self.export_out is None:
                raise MediaError("anulowano")
            if rc != 0 or not os.path.isfile(seg):
                self.write_error_log(cmd, rc, err)
                raise MediaError("Wycięcie mp3 nie powiodło się: " + (err.strip().splitlines() or ["ffmpeg"])[-1][:200])
            names.append(seg)
        lst = os.path.join(tmp, "cut.txt")
        with open(lst, "w", encoding="utf-8") as f:
            for p in names:
                f.write("file '" + p.replace("'", r"'\''") + "'\n")
        out = os.path.join(tmp, "cut.mp3")
        cmd = [FFMPEG, "-y", "-hide_banner", "-v", "error", "-nostats", "-progress", "pipe:1",
               "-f", "concat", "-safe", "0", "-i", lst, "-i", m.path, "-map", "0", "-map_metadata", "1",
               "-c", "copy", "-id3v2_version", "3", out]
        rc, err = self.run_ffmpeg_export(cmd, fr.dur, m, lambda pct: None)
        if self.export_out is None:
            raise MediaError("anulowano")
        if rc != 0 or not os.path.isfile(out):
            self.write_error_log(cmd, rc, err)
            raise MediaError("Sklejenie mp3 nie powiodło się: " + (err.strip().splitlines() or ["ffmpeg"])[-1][:200])
        m2 = copy.copy(m)
        m2.path = out
        return m2, Fragment(0.0, fr.dur)

    def write_error_log(self, cmd: list[str], rc: int, err: str):
        try:
            with open(ERROR_LOG, "w", encoding="utf-8") as f:
                f.write(f"Ciach – błąd eksportu ({time.strftime('%Y-%m-%d %H:%M:%S')})\n")
                f.write("Polecenie:\n" + subprocess.list2cmdline(cmd) + "\n\n")
                f.write(f"Kod wyjścia: {rc}\n\nffmpeg stderr:\n{err}\n")
        except OSError:
            pass

    def run_small_export(self, m: Media, fr: "Fragment", mix: dict | None = None,
                         zooms: list[dict] | None = None):
        stem, ext = os.path.splitext(m.display_name)
        out = self.unique_out(stem, ext.lower(), "_ciach_maly")
        tmp = tempfile.mkdtemp(prefix="ciach_")
        self.export_out = out
        self.export_tmp = tmp
        dur = fr.dur
        state = {"attempt": 1}
        zoom = bool(zooms) and m.kind == "video"
        if zoom:
            self.write_zoom_file(tmp, zooms, m, fr)

        def progress(pct: float):
            self.emit("export", state="progress", mode="small", percent=round(pct), attempt=state["attempt"])
            self.set_title(f"{APP_NAME} – {round(pct)}% – {m.display_name}")

        def cancelled() -> bool:
            return self.export_out is None

        def fail(cmd, rc, err):
            self.write_error_log(cmd, rc, err)
            self._remove(out)
            msg = (err.strip().splitlines() or ["ffmpeg zakończył się błędem"])[-1][:200]
            self.emit("export", state="error", mode="small", message=msg)

        progress(0)
        try:
            if m.kind == "video":
                size = 0
                # Z miksem (Podkłady, Głośność albo Wycięcia) audio zawsze idzie przez AAC, więc plan
                # dostaje co najmniej jedną ścieżkę i nigdy nie wybiera kopii.
                streams = m.audio_streams if not mix else max(2, m.audio_streams)
                for attempt, factor in enumerate(SMALL_FACTORS, 1):
                    state["attempt"] = attempt
                    plan = plan_small_video(dur, m.width, m.height, m.fps, m.vbitrate, m.abitrate,
                                            streams, factor)
                    passlog = os.path.join(tmp, f"pass{attempt}")
                    for pass_no in (1, 2):
                        cmd = self.build_small_cmd(m, fr, out, plan, pass_no, passlog, mix, zoom)
                        base = 50.0 * (pass_no - 1)
                        rc, err = self.run_ffmpeg_export(cmd, dur, m, lambda p, b=base: progress(b + p / 2), cwd=tmp)
                        if cancelled():
                            return
                        if rc != 0:
                            fail(cmd, rc, err)
                            return
                    size = os.path.getsize(out) if os.path.isfile(out) else 0
                    if 0 < size <= SMALL_LIMIT:
                        self.emit("export", state="done", mode="small", file=os.path.basename(out),
                                  size=size, percent=100, attempt=attempt)
                        return
                self.emit("export", state="toobig", mode="small", file=os.path.basename(out), size=size)
            else:
                if fr.holes:
                    try:
                        m, fr = self.cut_mp3(m, fr, tmp)
                    except MediaError as e:
                        if cancelled():
                            return
                        self.emit("export", state="error", mode="small", message=str(e)[:200])
                        return
                cmd = self.build_cmd(m, fr, out, "x264")
                rc, err = self.run_ffmpeg_export(cmd, dur, m, progress)
                if cancelled():
                    return
                if rc != 0:
                    fail(cmd, rc, err)
                    return
                size = os.path.getsize(out)
                attempt = 1
                for rate in SMALL_MP3_RATES:
                    if size <= SMALL_LIMIT:
                        break
                    attempt += 1
                    state["attempt"] = attempt
                    cmd = self.build_small_mp3_cmd(m, fr, out, rate)
                    rc, err = self.run_ffmpeg_export(cmd, dur, m, progress)
                    if cancelled():
                        return
                    if rc != 0:
                        fail(cmd, rc, err)
                        return
                    size = os.path.getsize(out)
                if size <= SMALL_LIMIT:
                    self.emit("export", state="done", mode="small", file=os.path.basename(out),
                              size=size, percent=100, attempt=attempt)
                else:
                    self._remove(out)
                    self.emit("export", state="toolong", mode="small", size=size)
        except Exception as e:  # noqa: BLE001
            self.write_error_log([], -1, repr(e))
            self._remove(out)
            self.emit("export", state="error", mode="small", message=str(e)[:200])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            with self.lock:
                self.export_active = False
                self.export_out = None
                self.export_tmp = None
            if self.media is m or (self.media and self.media.gen == m.gen):
                self.set_title(self.title_for(self.media))

    @staticmethod
    def _remove(path: str):
        for _ in range(10):
            try:
                if os.path.exists(path):
                    os.remove(path)
                return
            except OSError:
                time.sleep(0.2)

    def build_cmd(self, m: Media, fr: "Fragment", out: str, encoder: str,
                  mix: dict | None = None, zoom: bool = False) -> list[str]:
        # Dwustopniowy seek: wejściowy -ss do ~3 s przed cięciem (szybki skok do
        # klatki kluczowej), wyjściowy -ss dokładnie na cięcie. Dzięki temu
        # kopiowane strumienie (audio) też zaczynają się w miejscu cięcia, a nie
        # na klatce kluczowej sprzed niego. 0,5 ms zapasu gwarantuje, że klatka
        # o znaczniku `start` wejdzie, a klatka o znaczniku `end` już nie.
        # Wycięcia (dziury): obraz przez select/setpts, dźwięk przez tor miksu (ADR 0002).
        head = [FFMPEG, "-y", "-hide_banner", "-v", "error", "-nostats", "-progress", "pipe:1"]
        if m.kind == "video":
            venc = NVENC_ARGS if encoder == "nvenc" else X264_ARGS
            vf = (self.zoom_chain(m.width, m.height) if zoom else []) + fr.cut_filters()
            vfilters = [f"[0:v:0]{','.join(vf)}[v]"] if vf else []
            vmap = "[v]" if vf else "0:v:0"
            if mix:
                # Podkłady, Głośność albo Wycięcia: jedna ścieżka AAC z miksu (patrz export_pipeline.md).
                inputs, filters, label = self.mix_filters(m, fr, mix)
                return head + [*self.seek_args(m, fr, inputs), "-filter_complex", ";".join(vfilters + filters),
                               "-map", vmap, "-map", label, *venc, *VIDEO_TB, "-pix_fmt", "yuv420p",
                               "-c:a", "aac", "-b:a", str(MIX_AUDIO_RATE), "-movflags", "+faststart", out]
            fc = ["-filter_complex", ";".join(vfilters)] if vfilters else []
            return head + [*self.seek_args(m, fr), *fc, "-map", vmap, "-map", "0:a?", *venc, *VIDEO_TB,
                           "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out]
        return head + [*self.seek_args(m, fr), "-map", "0", "-c", "copy", "-map_metadata", "0",
                       "-id3v2_version", "3", "-avoid_negative_ts", "make_zero", out]

    def run_ffmpeg_export(self, cmd: list[str], dur: float, m: Media, on_progress=None,
                          cwd: str | None = None) -> tuple[int, str]:
        if on_progress is None:
            def on_progress(pct: float):
                self.emit("export", state="progress", mode="full", percent=round(pct))
                self.set_title(f"{APP_NAME} – {round(pct)}% – {m.display_name}")
        return self.run_ffmpeg(cmd, dur, on_progress, attr="export_proc", cwd=cwd)

    def run_ffmpeg(self, cmd: list[str], dur: float, on_progress, attr: str, cwd: str | None = None) -> tuple[int, str]:
        """Uruchamia ffmpeg z `-progress pipe:1`, woła on_progress(procent) co ~0,2 s.
        Uchwyt procesu trzymany w `self.<attr>`, żeby dało się go zabić przy zamykaniu.
        `cwd`: katalog z plikiem poleceń Zbliżenia (ścieżka względna omija escapowanie w filtergraph)."""
        p = popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
        setattr(self, attr, p)
        err_chunks: list[bytes] = []

        def drain():
            assert p.stderr is not None
            err_chunks.append(p.stderr.read())

        t = threading.Thread(target=drain, daemon=True)
        t.start()
        assert p.stdout is not None
        last = 0.0
        for line in p.stdout:
            if line.startswith(b"out_time_us=") or line.startswith(b"out_time_ms="):
                try:
                    us = int(line.split(b"=", 1)[1].strip())
                except ValueError:
                    continue
                pct = max(0.0, min(99.0, us / 1e6 / dur * 100.0)) if dur > 0 else 0.0
                now = time.time()
                if now - last >= 0.2:
                    last = now
                    on_progress(pct)
        p.wait()
        t.join(timeout=5)
        setattr(self, attr, None)
        return p.returncode, b"".join(err_chunks).decode("utf-8", "replace")

    def run_export(self, m: Media, fr: "Fragment", mix: dict | None = None,
                   zooms: list[dict] | None = None):
        stem, ext = os.path.splitext(m.display_name)
        out = self.unique_out(stem, ext.lower())
        self.export_out = out
        self.emit("export", state="progress", mode="full", percent=0)
        self.set_title(f"{APP_NAME} – 0% – {m.display_name}")
        self.encoder_ready.wait(timeout=60)
        encoder = self.encoder or "x264"
        zoom = bool(zooms) and m.kind == "video"
        tmp = None
        try:
            if zoom or (m.kind != "video" and fr.holes):
                tmp = tempfile.mkdtemp(prefix="ciach_")
                self.export_tmp = tmp
            if zoom:
                self.write_zoom_file(tmp, zooms, m, fr)
            if m.kind != "video" and fr.holes:
                m, fr = self.cut_mp3(m, fr, tmp)
            attempts = [encoder] if (m.kind != "video" or encoder == "x264") else ["nvenc", "x264"]
            rc, err, cmd = 1, "", []
            for enc in attempts:
                cmd = self.build_cmd(m, fr, out, enc, mix, zoom)
                rc, err = self.run_ffmpeg_export(cmd, fr.dur, m, cwd=tmp)
                if rc == 0:
                    break
                if enc == "nvenc":
                    self.encoder = "x264"
                if self.export_out is None:  # anulowano przy zamykaniu
                    return
            if rc == 0 and os.path.isfile(out) and os.path.getsize(out) > 0:
                self.emit("export", state="done", mode="full", file=os.path.basename(out), percent=100)
            else:
                try:
                    if os.path.exists(out):
                        os.remove(out)
                except OSError:
                    pass
                msg = (err.strip().splitlines() or ["ffmpeg zakończył się błędem"])[-1][:200]
                self.write_error_log(cmd, rc, err)
                self.emit("export", state="error", mode="full", message=msg)
        except MediaError as e:
            if self.export_out is not None:
                self._remove(out)
                self.emit("export", state="error", mode="full", message=str(e)[:200])
        except Exception as e:  # noqa: BLE001
            try:
                with open(ERROR_LOG, "w", encoding="utf-8") as f:
                    f.write(f"Ciach – błąd eksportu: {e!r}\n")
            except OSError:
                pass
            try:
                if os.path.exists(out):
                    os.remove(out)
            except OSError:
                pass
            self.emit("export", state="error", mode="full", message=str(e)[:200])
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
            with self.lock:
                self.export_active = False
                self.export_out = None
                self.export_tmp = None
            if self.media and self.media.gen == m.gen:
                self.set_title(self.title_for(self.media))

    def cancel_export(self):
        p = self.export_proc
        out = self.export_out
        tmp = self.export_tmp
        self.export_out = None
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        if p:
            try:
                p.kill()
                p.wait(timeout=5)
            except Exception:
                pass
        if out:
            for _ in range(10):
                try:
                    if os.path.exists(out):
                        os.remove(out)
                    break
                except OSError:
                    time.sleep(0.2)

    def cleanup_temp(self):
        """Pliki tymczasowe Sekwencji: własny katalog i osierocone katalogi po poprzednich sesjach."""
        p = self.join_proc
        if p:
            try:
                p.kill()
                p.wait(timeout=5)
            except Exception:
                pass
        if self.seq_dir:
            shutil.rmtree(self.seq_dir, ignore_errors=True)
        try:
            root = tempfile.gettempdir()
            for name in os.listdir(root):
                d = os.path.join(root, name)
                if name.startswith("ciach_seq_") and os.path.isdir(d) and d != self.seq_dir:
                    if time.time() - os.path.getmtime(d) > 3600:
                        shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass

    # ---------- zdarzenia okna ----------
    def on_closing(self):
        self.cancel_export()
        if self.media:
            self.media.kill()
        self.clear_podklady()
        self.cleanup_temp()
        return True

    def on_loaded(self):
        assert self.window is not None
        self.window.dom.document.events.drop += DOMEventHandler(self.on_drop, prevent_default=True)

    def on_drop(self, e):
        # Ścieżki zna tylko Python (pywebview dokleja je natywnie), a gdzie upuszczono, wie
        # UI: oddajemy mu ścieżki i współrzędne, a routing (podgląd / Gniazdo / pasek Podkładu)
        # robi `dropFiles` w app.js, ten sam, którego używają testy.
        files = (e.get("dataTransfer") or {}).get("files") or []
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if not paths:
            self.emit("reject", message="Nie udało się odczytać ścieżki upuszczonego pliku.")
            return
        self.emit("dropped", paths=paths, x=e.get("clientX"), y=e.get("clientY"))

    def ui_ready_cb(self):
        self.ui_ready = True
        if self.pending_path:
            p, self.pending_path = self.pending_path, None
            threading.Thread(target=self.load, args=(p,), daemon=True).start()


class Api:
    """Metody dostępne z JS przez window.pywebview.api."""

    def __init__(self, app: App):
        self._app = app

    def ready(self):
        self._app.ui_ready_cb()
        return {"port": self._app.port}

    def export(self, start, end, mode="full", mix=None, holes=None):
        return self._app.start_export(float(start), float(end), str(mode), mix if isinstance(mix, dict) else None,
                                      holes if isinstance(holes, list) else None)

    def set_title(self, title):
        self._app.set_title(str(title))
        return True

    def open_path(self, path):
        threading.Thread(target=self._app.load, args=(str(path),), daemon=True).start()
        return True

    def join(self, paths, index):
        paths = [str(p) for p in (paths if isinstance(paths, list) else [paths])]
        threading.Thread(target=self._app.join, args=(paths, int(index)), daemon=True).start()
        return True

    def set_parts(self, parts):
        return self._app.set_parts(parts)

    def add_podklad(self, path):
        threading.Thread(target=self._app.add_podklad, args=(str(path),), daemon=True).start()
        return True

    def remove_podklad(self, gen):
        self._app.remove_podklad(int(gen))
        return True


# ---------- serwer HTTP ----------
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # cisza
            pass

        def _send_bytes(self, data: bytes, ctype: str, status: int = 200, head=False):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if not head:
                self.wfile.write(data)

        def _not_found(self):
            self._send_bytes(b"not found", "text/plain", 404)

        def do_HEAD(self):
            self._handle(head=True)

        def do_GET(self):
            self._handle(head=False)

        def _handle(self, head: bool):
            try:
                u = urlparse(self.path)
                q = parse_qs(u.query)
                path = u.path
                if path == "/":
                    return self._static("index.html", head)
                if path.startswith("/ui/"):
                    return self._static(path[4:], head)
                if path == "/media":
                    return self._media(q, head)
                if path == "/api/wave":
                    return self._blob(q, "wave", head)
                if path == "/api/frames":
                    return self._blob(q, "frames", head)
                self._not_found()
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass
            except Exception:  # noqa: BLE001
                try:
                    self._send_bytes(b"error", "text/plain", 500)
                except Exception:
                    pass

        def do_POST(self):
            # Hak testowy: wykonuje JS w oknie. Aktywny wyłącznie przy CIACH_DEBUG=1.
            try:
                if not DEBUG or urlparse(self.path).path != "/debug/js" or not app.window:
                    return self._not_found()
                n = int(self.headers.get("Content-Length") or 0)
                code = self.rfile.read(n).decode("utf-8")
                result = app.window.evaluate_js(code)
                self._send_bytes(json.dumps(result, ensure_ascii=False, default=str).encode("utf-8"),
                                 "application/json; charset=utf-8")
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass
            except Exception:  # noqa: BLE001
                try:
                    self._send_bytes(b"error", "text/plain", 500)
                except Exception:
                    pass

        def _static(self, rel: str, head: bool):
            rel = rel.replace("\\", "/")
            if ".." in rel:
                return self._not_found()
            fp = os.path.normpath(os.path.join(UI_DIR, rel))
            if not fp.startswith(os.path.normpath(UI_DIR)) or not os.path.isfile(fp):
                return self._not_found()
            with open(fp, "rb") as f:
                data = f.read()
            ctype = CONTENT_TYPES.get(os.path.splitext(fp)[1].lower(), "application/octet-stream")
            self._send_bytes(data, ctype, head=head)

        def _blob(self, q, attr: str, head: bool):
            gen = int(q.get("gen", ["0"])[0] or 0)
            m = app.find_media(gen)
            if not m:
                return self._not_found()
            data = getattr(m, attr)
            if data is None:
                return self._send_bytes(b"", "application/octet-stream", 204, head)
            self._send_bytes(data, "application/octet-stream", head=head)

        def _media(self, q, head: bool):
            gen = int(q.get("gen", ["0"])[0] or 0)
            m = app.find_media(gen)
            if not m:
                return self._not_found()
            size = m.size
            rng = self.headers.get("Range")
            start, end = 0, size - 1
            status = 200
            if rng:
                mo = re.match(r"bytes=(\d*)-(\d*)", rng.strip())
                if mo:
                    a, b = mo.group(1), mo.group(2)
                    if a:
                        start = int(a)
                        end = int(b) if b else size - 1
                    elif b:
                        start = max(0, size - int(b))
                        end = size - 1
                    if start >= size or start > end:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    end = min(end, size - 1)
                    status = 206
            length = end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", m.mime)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if head:
                return
            with open(m.path, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(1 << 18, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)

    return Handler


def start_server(app: App) -> int:
    class QuietServer(ThreadingHTTPServer):
        def handle_error(self, request, client_address):  # zerwane połączenia to norma przy <video>
            pass

    srv = QuietServer(("127.0.0.1", 0), make_handler(app))
    srv.daemon_threads = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return port


def main():
    app = App()
    app.port = start_server(app)
    if DEBUG:
        print(f"CIACH_PORT={app.port}", flush=True)
        portfile = os.environ.get("CIACH_PORTFILE")
        if portfile:
            with open(portfile, "w", encoding="utf-8") as f:
                f.write(str(app.port))
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        app.pending_path = sys.argv[1]
    threading.Thread(target=app.detect_encoder, daemon=True).start()

    api = Api(app)
    window = webview.create_window(
        APP_NAME,
        url=f"http://127.0.0.1:{app.port}/",
        js_api=api,
        width=1100,
        height=700,
        min_size=(640, 400),
        background_color="#151517",
        text_select=False,
    )
    app.window = window
    window.events.closing += app.on_closing
    window.events.loaded += app.on_loaded
    webview.start(gui="edgechromium", private_mode=True, http_server=False)


if __name__ == "__main__":
    main()
