"""Ciach – jednoplikowy trimmer mp4/mp3.

Backend: pywebview (WebView2) + lokalny serwer HTTP (media z obsługą Range,
waveform, znaczniki klatek) + ffmpeg/ffprobe do analizy i eksportu.
"""
from __future__ import annotations

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

# Mały Ciach: limit rozmiaru (bajty), cele kolejnych prób, próg jakości i drabinka rozdzielczości
SMALL_LIMIT = 25_000_000
SMALL_FACTORS = [0.98, 0.92, 0.85]
SMALL_BPP = 0.05  # bity na piksel na klatkę, poniżej których schodzimy z fps / rozdzielczością
SMALL_HEIGHTS = [540, 360]
SMALL_MP3_RATES = [128_000, 96_000, 64_000]


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
        self.audio_streams = 0
        self.sample_rate = 0
        self.vbitrate = 0
        self.abitrate = 0
        self.frames: bytes | None = None
        self.wave: bytes | None = None
        self.procs: list[subprocess.Popen] = []
        self.dead = False

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
        self.duration = float(fmt.get("duration") or 0.0)
        self.start_time = max(0.0, float(fmt.get("start_time") or 0.0))
        if video and self.ext == ".mp4":
            v = video[0]
            self.kind = "video"
            self.vcodec = v.get("codec_name", "")
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
            spf = 1152 if self.sample_rate >= 32000 else 576
            self.frame_step = spf / self.sample_rate
            self.fps = 1.0 / self.frame_step
            if not self.duration:
                self.duration = float(a.get("duration") or 0.0)
        else:
            raise MediaError("Plik nie zawiera obrazu ani dźwięku.")
        if self.duration <= 0:
            raise MediaError("Nie udało się odczytać długości pliku.")

    def info(self) -> dict:
        return {
            "gen": self.gen,
            "name": self.name,
            "kind": self.kind,
            "duration": self.duration,
            "fps": self.fps,
            "frameStep": self.frame_step,
            "width": self.width,
            "height": self.height,
            "vcodec": self.vcodec,
            "audioStreams": self.audio_streams,
            "waveBinSec": WAVE_BIN / WAVE_RATE,
        }

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
    def load(self, path: str):
        path = os.path.abspath(path)
        ext = os.path.splitext(path)[1].lower()
        if ext not in ALLOWED_EXT:
            self.emit("reject", message="Obsługiwane są tylko pliki MP4 i MP3.")
            return
        if not os.path.isfile(path):
            self.emit("reject", message="Nie znaleziono pliku.")
            return
        with self.lock:
            if self.media:
                self.media.kill()
            self.gen += 1
            media = Media(path, self.gen)
            self.media = media
        try:
            media.probe()
        except MediaError as e:
            with self.lock:
                if self.media is media:
                    self.media = None
            self.emit("reject", message=str(e))
            return
        except Exception as e:  # noqa: BLE001
            with self.lock:
                if self.media is media:
                    self.media = None
            self.emit("reject", message=f"Nie udało się odczytać pliku: {e}")
            return
        self.set_title(f"{APP_NAME} – {media.name}")
        self.emit("loaded", info=media.info())
        threading.Thread(target=self.scan_frames, args=(media,), daemon=True).start()
        threading.Thread(target=self.scan_wave, args=(media,), daemon=True).start()

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
    def start_export(self, start: float, end: float, mode: str = "full") -> dict:
        with self.lock:
            if self.export_active:
                return {"ok": False, "message": "Eksport już trwa."}
            m = self.media
            if not m:
                return {"ok": False, "message": "Brak pliku."}
            if end <= start:
                return {"ok": False, "message": "Pusty zakres."}
            self.export_active = True
        target = self.run_small_export if mode == "small" else self.run_export
        threading.Thread(target=target, args=(m, float(start), float(end)), daemon=True).start()
        return {"ok": True}

    @staticmethod
    def unique_out(stem: str, ext: str, suffix: str = "_ciach") -> str:
        cand = os.path.join(OUT_DIR, f"{stem}{suffix}{ext}")
        i = 2
        while os.path.exists(cand):
            cand = os.path.join(OUT_DIR, f"{stem}{suffix} ({i}){ext}")
            i += 1
        return cand

    @staticmethod
    def seek_args(m: Media, start: float, end: float) -> list[str]:
        # Dwustopniowy seek (patrz agent_docs/export_pipeline.md)
        dur = end - start
        pre = max(0.0, start - 3.0)
        oss = max(0.0, start - pre - 0.0005)
        return ["-ss", f"{pre:.6f}", "-i", m.path, "-ss", f"{oss:.6f}", "-t", f"{dur:.6f}"]

    def build_small_cmd(self, m: Media, start: float, end: float, out: str, plan: dict,
                        pass_no: int, passlog: str) -> list[str]:
        cmd = [FFMPEG, "-y", "-hide_banner", "-v", "error", "-nostats", "-progress", "pipe:1",
               *self.seek_args(m, start, end)]
        filters: list[str] = []
        vf: list[str] = []
        if plan["fps_change"]:
            vf.append(f"fps={plan['fps']:g}")
        if plan["scale"]:
            vf.append(f"scale=-2:{plan['height']}")
        if vf:
            filters.append(f"[0:v:0]{','.join(vf)}[v]")
            vmap = "[v]"
        else:
            vmap = "0:v:0"
        amap = None
        audio_args: list[str] = ["-an"]
        if pass_no == 2 and plan["a_mode"] == "copy":
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
        cmd += ["-c:v", "libx264", "-preset", "slow", "-b:v", str(plan["v_rate"]),
                "-pix_fmt", "yuv420p", "-pass", str(pass_no), "-passlogfile", passlog]
        cmd += audio_args
        if pass_no == 1:
            cmd += ["-f", "null", os.devnull]
        else:
            cmd += ["-movflags", "+faststart", out]
        return cmd

    def build_small_mp3_cmd(self, m: Media, start: float, end: float, out: str, rate: int) -> list[str]:
        return [FFMPEG, "-y", "-hide_banner", "-v", "error", "-nostats", "-progress", "pipe:1",
                *self.seek_args(m, start, end), "-map", "0", "-c:v", "copy",
                "-c:a", "libmp3lame", "-b:a", str(rate), "-map_metadata", "0", "-id3v2_version", "3",
                "-avoid_negative_ts", "make_zero", out]

    def write_error_log(self, cmd: list[str], rc: int, err: str):
        try:
            with open(ERROR_LOG, "w", encoding="utf-8") as f:
                f.write(f"Ciach – błąd eksportu ({time.strftime('%Y-%m-%d %H:%M:%S')})\n")
                f.write("Polecenie:\n" + subprocess.list2cmdline(cmd) + "\n\n")
                f.write(f"Kod wyjścia: {rc}\n\nffmpeg stderr:\n{err}\n")
        except OSError:
            pass

    def run_small_export(self, m: Media, start: float, end: float):
        stem, ext = os.path.splitext(m.name)
        out = self.unique_out(stem, ext.lower(), "_ciach_maly")
        tmp = tempfile.mkdtemp(prefix="ciach_")
        self.export_out = out
        self.export_tmp = tmp
        dur = end - start
        state = {"attempt": 1}

        def progress(pct: float):
            self.emit("export", state="progress", mode="small", percent=round(pct), attempt=state["attempt"])
            self.set_title(f"{APP_NAME} – {round(pct)}% – {m.name}")

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
                for attempt, factor in enumerate(SMALL_FACTORS, 1):
                    state["attempt"] = attempt
                    plan = plan_small_video(dur, m.width, m.height, m.fps, m.vbitrate, m.abitrate,
                                            m.audio_streams, factor)
                    passlog = os.path.join(tmp, f"pass{attempt}")
                    for pass_no in (1, 2):
                        cmd = self.build_small_cmd(m, start, end, out, plan, pass_no, passlog)
                        base = 50.0 * (pass_no - 1)
                        rc, err = self.run_ffmpeg_export(cmd, dur, m, lambda p, b=base: progress(b + p / 2))
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
                cmd = self.build_cmd(m, start, end, out, "x264")
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
                    cmd = self.build_small_mp3_cmd(m, start, end, out, rate)
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
            if self.media is m:
                self.set_title(f"{APP_NAME} – {m.name}")

    @staticmethod
    def _remove(path: str):
        for _ in range(10):
            try:
                if os.path.exists(path):
                    os.remove(path)
                return
            except OSError:
                time.sleep(0.2)

    def build_cmd(self, m: Media, start: float, end: float, out: str, encoder: str) -> list[str]:
        # Dwustopniowy seek: wejściowy -ss do ~3 s przed cięciem (szybki skok do
        # klatki kluczowej), wyjściowy -ss dokładnie na cięcie. Dzięki temu
        # kopiowane strumienie (audio) też zaczynają się w miejscu cięcia, a nie
        # na klatce kluczowej sprzed niego. 0,5 ms zapasu gwarantuje, że klatka
        # o znaczniku `start` wejdzie, a klatka o znaczniku `end` już nie.
        base = [FFMPEG, "-y", "-hide_banner", "-v", "error", "-nostats", "-progress", "pipe:1",
                *self.seek_args(m, start, end)]
        if m.kind == "video":
            venc = NVENC_ARGS if encoder == "nvenc" else X264_ARGS
            return base + ["-map", "0:v:0", "-map", "0:a?", *venc, "-pix_fmt", "yuv420p",
                           "-c:a", "copy", "-movflags", "+faststart", out]
        return base + ["-map", "0", "-c", "copy", "-map_metadata", "0", "-id3v2_version", "3",
                       "-avoid_negative_ts", "make_zero", out]

    def run_ffmpeg_export(self, cmd: list[str], dur: float, m: Media, on_progress=None) -> tuple[int, str]:
        p = popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.export_proc = p
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
                    if on_progress:
                        on_progress(pct)
                    else:
                        self.emit("export", state="progress", mode="full", percent=round(pct))
                        self.set_title(f"{APP_NAME} – {round(pct)}% – {m.name}")
        p.wait()
        t.join(timeout=5)
        self.export_proc = None
        return p.returncode, b"".join(err_chunks).decode("utf-8", "replace")

    def run_export(self, m: Media, start: float, end: float):
        stem, ext = os.path.splitext(m.name)
        out = self.unique_out(stem, ext.lower())
        self.export_out = out
        self.emit("export", state="progress", mode="full", percent=0)
        self.set_title(f"{APP_NAME} – 0% – {m.name}")
        self.encoder_ready.wait(timeout=60)
        encoder = self.encoder or "x264"
        try:
            attempts = [encoder] if (m.kind != "video" or encoder == "x264") else ["nvenc", "x264"]
            rc, err, cmd = 1, "", []
            for enc in attempts:
                cmd = self.build_cmd(m, start, end, out, enc)
                rc, err = self.run_ffmpeg_export(cmd, end - start, m)
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
            with self.lock:
                self.export_active = False
                self.export_out = None
            if self.media is m:
                self.set_title(f"{APP_NAME} – {m.name}")

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

    # ---------- zdarzenia okna ----------
    def on_closing(self):
        self.cancel_export()
        if self.media:
            self.media.kill()
        return True

    def on_loaded(self):
        assert self.window is not None
        self.window.dom.document.events.drop += DOMEventHandler(self.on_drop, prevent_default=True)

    def on_drop(self, e):
        files = (e.get("dataTransfer") or {}).get("files") or []
        for f in files:
            path = f.get("pywebviewFullPath")
            if path:
                self.load(path)
                return
        self.emit("reject", message="Nie udało się odczytać ścieżki upuszczonego pliku.")

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

    def export(self, start, end, mode="full"):
        return self._app.start_export(float(start), float(end), str(mode))

    def set_title(self, title):
        self._app.set_title(str(title))
        return True

    def open_path(self, path):
        threading.Thread(target=self._app.load, args=(str(path),), daemon=True).start()
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
            m = app.media
            gen = int(q.get("gen", ["0"])[0] or 0)
            if not m or m.gen != gen:
                return self._not_found()
            data = getattr(m, attr)
            if data is None:
                return self._send_bytes(b"", "application/octet-stream", 204, head)
            self._send_bytes(data, "application/octet-stream", head=head)

        def _media(self, q, head: bool):
            m = app.media
            gen = int(q.get("gen", ["0"])[0] or 0)
            if not m or m.gen != gen:
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
