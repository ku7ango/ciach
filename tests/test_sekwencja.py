"""Test backendu Sekwencji i Podkładów: sklejenie dwóch Nagrań, Ciach z miksem Podkładu,
Mały Ciach z miksem, usunięcie Nagrania. Bez okna: `app.window` to atrapa zbierająca zdarzenia.

Użycie: venv/Scripts/python tests/test_sekwencja.py
Pliki testowe (syntetyczne) powstają w tests/, wyniki eksportu w folderze projektu
i są kasowane po dokładnych nazwach (TEST_STEMS), nigdy wzorcem.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time

SP = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(SP)
sys.path.insert(0, PROJ)
import ciach  # noqa: E402

A = os.path.join(SP, "_seq_a.mp4")   # 4,0 s, cisza
B = os.path.join(SP, "_seq_b.mp4")   # 2,5 s, cisza
C = os.path.join(SP, "_seq_c.mp4")   # 2 s, 60 fps: skleja się (Sekwencja zmiennoklatkowa)
D = os.path.join(SP, "_seq_d.mp4")   # inne parametry (640x360) → odrzucenie
P = os.path.join(SP, "_podklad.mp3")  # 6 s, ton 1 kHz
Q = os.path.join(SP, "_seq_q.mp3")    # 3 s, ton 500 Hz (Sekwencja mp3+mp3)
TEST_STEMS = ("_seq_a_ciach", "_seq_b_ciach", "_podklad_ciach")


def gen(path, dur, fps=30, tone=None, size="1280x720"):
    if os.path.exists(path):
        return
    src = f"sine=frequency={tone}:duration={dur}" if tone else f"anullsrc=r=48000:cl=stereo"
    cmd = [ciach.FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}:duration={dur}",
           "-f", "lavfi", "-i", src, "-t", str(dur), "-c:v", "libx264", "-preset", "veryfast", "-g", "60",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path]
    subprocess.run(cmd, check=True)


def gen_mp3(path, dur, tone):
    if os.path.exists(path):
        return
    subprocess.run([ciach.FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={tone}:duration={dur}",
                    "-c:a", "libmp3lame", "-b:a", "128k", path], check=True)


def probe(path, entries):
    cp = subprocess.run([ciach.FFPROBE, "-v", "error", "-show_entries", entries, "-of", "json", path],
                        capture_output=True, text=True, check=True)
    return json.loads(cp.stdout)


def mean_volume(path, t0, t1):
    cp = subprocess.run([ciach.FFMPEG, "-v", "info", "-ss", str(t0), "-t", str(t1 - t0), "-i", path, "-map", "0:a:0",
                         "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"mean_volume: (-?[\d.]+) dB", cp.stderr)
    return float(m.group(1)) if m else -91.0


def nb_frames(path):
    d = probe(path, "stream=codec_type,nb_frames,codec_name")
    v = [s for s in d["streams"] if s["codec_type"] == "video"]
    a = [s for s in d["streams"] if s["codec_type"] == "audio"]
    return int(v[0]["nb_frames"]), a


class FakeWindow:
    def __init__(self):
        self.events = []
        self.cv = threading.Condition()

    def run_js(self, code):
        m = re.search(r"window.ciachEvent\((.*)\);$", code, re.S)
        ev = json.loads(m.group(1))
        with self.cv:
            self.events.append(ev)
            self.cv.notify_all()

    def set_title(self, t):
        self.title = t

    def wait_for(self, pred, timeout=120):
        """Pierwsze pasujące zdarzenie po ostatnio dopasowanym (kursor), żeby powtórzone
        scenariusze nie trafiały w stare `loaded` z poprzednich kroków."""
        t0 = time.time()
        with self.cv:
            while True:
                for i in range(getattr(self, "cursor", 0), len(self.events)):
                    ev = self.events[i]
                    if pred(ev):
                        self.cursor = i + 1
                        return ev
                left = timeout - (time.time() - t0)
                if left <= 0:
                    raise SystemExit("TIMEOUT: " + repr(self.events[-3:]))
                self.cv.wait(left)


def clean():
    for f in os.listdir(PROJ):
        if f.startswith(TEST_STEMS):
            os.remove(os.path.join(PROJ, f))


def main():
    gen(A, 4.0)
    gen(B, 2.5)
    gen(C, 2.0, fps=60)
    gen(D, 2.0, size="640x360")
    gen_mp3(P, 6.0, 1000)
    clean()
    app = ciach.App()
    win = FakeWindow()
    app.window = win
    app.encoder = "x264"
    app.encoder_ready.set()

    app.load(A)
    ev = win.wait_for(lambda e: e["type"] == "loaded")
    assert ev["reason"] == "open" and len(ev["info"]["parts"]) == 1
    print("1 loaded", ev["info"]["name"], ev["info"]["duration"])

    # niezgodne parametry → reject, Sekwencja bez zmian
    app.join([D], 1)
    ev = win.wait_for(lambda e: e["type"] == "join" and e["state"] == "error")
    print("2 reject:", ev["message"])
    assert "inne parametry" in ev["message"] and len(app.media.parts) == 1

    # sklejenie: B na koniec
    n0 = len(win.events)
    app.join([B], 1)
    ev = win.wait_for(lambda e: e["type"] == "loaded" and e["reason"] == "join")
    info = ev["info"]
    print("3 joined:", info["name"], info["duration"], [(p["name"], p["start"]) for p in info["parts"]])
    assert info["name"] == "_seq_a.mp4" and len(info["parts"]) == 2
    assert abs(info["parts"][1]["start"] - 4.0) < 0.01 and abs(info["duration"] - 6.5) < 0.1
    assert app.is_temp(app.media.path)
    assert any(e["type"] == "join" and e["state"] == "done" for e in win.events[n0:])
    assert win.title.endswith("_seq_a.mp4 +1")
    win.wait_for(lambda e: e["type"] == "frames" and e["gen"] == info["gen"])
    assert app.media.frames is not None and len(app.media.frames) // 8 == 195
    import struct
    frames = struct.unpack("<%dd" % (len(app.media.frames) // 8), app.media.frames)

    # Podkład
    app.add_podklad(P)
    ev = win.wait_for(lambda e: e["type"] == "podklad")
    pg = ev["info"]["gen"]
    print("4 podklad:", ev["info"]["name"], ev["info"]["duration"])
    win.wait_for(lambda e: e["type"] == "wave" and e["gen"] == pg)
    assert app.podklady[pg].wave

    # Ciach [1.0, 5.0) z Podkładem od 2,0 s (mp3 0,5–2,5 s) → ton słychać w [1,3) s wyniku
    mix = {"gain": 1.0, "podklady": [{"gen": pg, "at": 2.0, "tin": 0.5, "tout": 2.5, "gain": 1.0}]}
    # zakres jak z UI: pts klatek (lewa włącznie, prawa wyłącznie)
    r = app.start_export(frames[30], frames[150], "full", mix)
    assert r["ok"], r
    ev = win.wait_for(lambda e: e["type"] == "export" and e["state"] in ("done", "error"), 300)
    assert ev["state"] == "done", ev
    out = os.path.join(PROJ, ev["file"])
    nf, audio = nb_frames(out)
    vols = [mean_volume(out, 0, 0.9), mean_volume(out, 1.1, 2.9), mean_volume(out, 3.1, 4.0)]
    print("5 ciach:", ev["file"], "frames", nf, "audio", [a["codec_name"] for a in audio], "vol", vols)
    assert nf == 120 and len(audio) == 1 and audio[0]["codec_name"] == "aac"
    assert vols[0] < -60 and vols[1] > -25 and vols[2] < -60

    # Głośność Sekwencji 100 % bez Podkładów → kopia audio (brak miksu)
    assert app.resolve_mix(app.media, {"gain": 1.0, "podklady": []}) is None
    assert app.resolve_mix(app.media, {"gain": 0.5, "podklady": []}) is not None

    # Mały Ciach z miksem: jedna ścieżka AAC, < 25 MB
    r = app.start_export(frames[15], frames[105], "small", mix)
    assert r["ok"], r
    ev = win.wait_for(lambda e: e["type"] == "export" and e["mode"] == "small" and e["state"] in ("done", "error", "toobig"), 600)
    assert ev["state"] == "done", ev
    out2 = os.path.join(PROJ, ev["file"])
    nf, audio = nb_frames(out2)
    print("6 maly:", ev["file"], "frames", nf, "audio", [a["codec_name"] for a in audio], "size", ev["size"])
    assert nf == 90 and len(audio) == 1 and audio[0]["codec_name"] == "aac"
    assert mean_volume(out2, 1.6, 2.9) > -25 and mean_volume(out2, 0, 1.4) < -60

    # Usunięcie Nagrania: UI robi to Wycięciem i przysyła nowy skład kawałków (`set_parts`);
    # plik tymczasowy zostaje, a Ciach dostaje dziurę. Tu: samo B, tytuł bez „+1”.
    tmp_path = app.media.path
    r = app.set_parts([{"src": 1, "in": 0.0, "out": 2.5}])
    assert r["ok"], r
    assert len(app.media.parts) == 1 and app.media.path == tmp_path and win.title.endswith("_seq_a.mp4")
    assert app.media.piece_range(app.media.parts[0]) == (4.0, 6.5)
    assert not app.set_parts([{"src": 5, "in": 0, "out": 1}])["ok"] and not app.set_parts([])["ok"]
    # Ciach [1.0, 5.0) z dziurą [2.0, 4.0): 30 klatek A + 30 klatek B, dźwięk przez tor miksu (AAC)
    r = app.start_export(frames[30], frames[150], "full", None, [[frames[60], frames[120]]])
    assert r["ok"], r
    ev = win.wait_for(lambda e: e["type"] == "export" and e["state"] in ("done", "error"), 300)
    assert ev["state"] == "done", ev
    nf, audio = nb_frames(os.path.join(PROJ, ev["file"]))
    d = probe(os.path.join(PROJ, ev["file"]), "stream=start_time:format=duration")
    print("7 hole:", ev["file"], "frames", nf, "audio", [a["codec_name"] for a in audio], "dur", d["format"]["duration"],
          "start", [x["start_time"] for x in d["streams"]])
    assert nf == 60 and len(audio) == 1 and audio[0]["codec_name"] == "aac"
    assert abs(float(d["format"]["duration"]) - 2.0) < 0.05
    assert all(abs(float(x["start_time"])) < 0.002 for x in d["streams"])
    # przywrócenie A (Cofnięcie w UI) to znów tylko set_parts
    assert app.set_parts([{"src": 0, "in": 0.0, "out": 4.0}, {"src": 1, "in": 0.0, "out": 2.5}])["ok"]
    assert win.title.endswith("_seq_a.mp4 +1")

    # Sekwencja mp3 + mp3: to samo sklejanie, wynik kopia 1:1; Podkład pod nią odrzucony
    gen_mp3(Q, 3.0, 500)
    app.load(P)
    win.wait_for(lambda e: e["type"] == "loaded" and e["reason"] == "open" and e["info"]["name"] == "_podklad.mp3")
    app.join([Q], 1)
    ev = win.wait_for(lambda e: e["type"] == "loaded" and e["reason"] == "join" and e["info"]["kind"] == "audio")
    print("8 mp3 seq:", ev["info"]["name"], ev["info"]["duration"], [p["start"] for p in ev["info"]["parts"]])
    assert abs(ev["info"]["duration"] - 9.0) < 0.1 and abs(ev["info"]["parts"][1]["start"] - 6.0) < 0.05
    app.add_podklad(Q)
    ev = win.wait_for(lambda e: e["type"] == "reject")
    assert "tylko pod Sekwencję wideo" in ev["message"], ev
    r = app.start_export(5.0, 8.0, "full", {"gain": 0.5, "podklady": []})
    assert r["ok"], r
    ev = win.wait_for(lambda e: e["type"] == "export" and e["state"] in ("done", "error") and e["file"].endswith(".mp3"), 120)
    assert ev["state"] == "done", ev
    d = probe(os.path.join(PROJ, ev["file"]), "stream=codec_name:format=duration")
    print("   mp3 out:", ev["file"], d["streams"][0]["codec_name"], d["format"]["duration"])
    assert d["streams"][0]["codec_name"] == "mp3" and abs(float(d["format"]["duration"]) - 3.0) < 0.1
    assert mean_volume(os.path.join(PROJ, ev["file"]), 0.2, 0.8) > -30, "ton z Podkładu (cz. 1) do 6 s"
    assert mean_volume(os.path.join(PROJ, ev["file"]), 1.5, 2.8) > -30, "ton 500 Hz z Q po Styku"

    # trzeci plik na Sekwencję z dwóch części: sygnatura z pierwszego Nagrania, nie z pliku
    # tymczasowego (jego średni fps to 29,95 i kiedyś to odrzucało wszystko)
    app.load(A)
    win.wait_for(lambda e: e["type"] == "loaded" and e["reason"] == "open" and e["info"]["name"] == "_seq_a.mp4")
    app.join([B], 1)
    win.wait_for(lambda e: e["type"] == "loaded" and e["reason"] == "join" and len(e["info"]["parts"]) == 2)
    # sygnatura sklejki = sygnatura pierwszego Nagrania (plik tymczasowy jej nie nadpisuje)
    first = ciach.Media(A, 0)
    first.probe()
    assert app.media.sig == first.signature() == app.media.signature()
    app.join([A], 1)
    ev = win.wait_for(lambda e: e["type"] == "loaded" and e["reason"] == "join" and len(e["info"]["parts"]) == 3)
    print("9 three parts:", [(p["name"], round(p["start"], 2)) for p in ev["info"]["parts"]])
    assert [p["name"] for p in ev["info"]["parts"]] == ["_seq_a.mp4", "_seq_a.mp4", "_seq_b.mp4"]

    # 30 fps + 60 fps: skleja się, Ciach przez Styk zachowuje wszystkie klatki obu części
    app.load(A)
    win.wait_for(lambda e: e["type"] == "loaded" and e["reason"] == "open" and len(e["info"]["parts"]) == 1)
    app.join([C], 1)
    ev = win.wait_for(lambda e: e["type"] == "loaded" and e["reason"] == "join" and len(e["info"]["parts"]) == 2)
    win.wait_for(lambda e: e["type"] == "frames" and e["gen"] == ev["info"]["gen"])
    frames = struct.unpack("<%dd" % (len(app.media.frames) // 8), app.media.frames)
    assert len(frames) == 240, len(frames)
    i0, i1 = 90, 180  # 30 klatek z A (1 s) + 60 z C (1 s)
    r = app.start_export(frames[i0], frames[i1], "full")
    assert r["ok"], r
    ev = win.wait_for(lambda e: e["type"] == "export" and e["state"] in ("done", "error") and e["file"].endswith(".mp4"), 300)
    assert ev["state"] == "done", ev
    nf, audio = nb_frames(os.path.join(PROJ, ev["file"]))
    print("10 mixed fps:", ev["file"], "frames", nf)
    assert nf == i1 - i0, nf

    # podmiana sesji czyści Podkłady
    app.load(A)
    win.wait_for(lambda e: e["type"] == "loaded" and e["reason"] == "open" and e["info"]["name"] == "_seq_a.mp4")
    assert not app.podklady
    app.on_closing()
    assert app.seq_dir is None or not os.path.isdir(app.seq_dir)
    clean()
    print("ALL OK")


if __name__ == "__main__":
    main()
