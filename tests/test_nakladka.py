"""Test backendu Nakładek: klucz w YUV pliku, Ciach z Nakładką (pozycja, skala, obrót), Nakładka przez
szew Wycięcia, Zbliżenie powiększające Nakładkę (ADR 0003), dźwięk Nakładki w miksie, Mały Ciach.
Bez okna (atrapa `window` jak w test_sekwencja.py).

Źródła: Sekwencja `_nak_base.mp4` (niebieska, cisza, 4 s) i Nakładka `_nak_src.mp4` (zielone tło 0x00B140
z czerwonym prostokątem 160x90 na środku, ton 1 kHz, 2 s). W wyniku czytamy kolor jednego wiersza albo
kolumny obrazu na każdej klatce: czerwony = Nakładka widoczna, niebieski = tło Sekwencji (zielone
tło Nakładki zniknęło), zielony = klucz nie zadziałał.

Użycie: venv/Scripts/python tests/test_nakladka.py
"""
import os
import struct
import subprocess
import sys

import numpy as np

SP = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(SP)
sys.path.insert(0, PROJ)
sys.path.insert(0, SP)
import ciach  # noqa: E402
import test_sekwencja as ts  # noqa: E402

BASE = os.path.join(SP, "_nak_base.mp4")  # 640x360, 30 fps, 4 s, niebieski, cisza
SRC = os.path.join(SP, "_nak_src.mp4")    # 320x180, 30 fps, 2 s, zielony z czerwonym środkiem, ton 1 kHz
KEY = [0, 177, 64]                        # 0x00B140, kolor tła Nakładki
TEST_STEMS = ("_nak_base_ciach",)


def gen():
    if not os.path.exists(BASE):
        subprocess.run([ciach.FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=30:d=4",
                        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "4", "-c:v", "libx264", "-preset", "veryfast",
                        "-g", "30", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", BASE], check=True)
    if not os.path.exists(SRC):
        subprocess.run([ciach.FFMPEG, "-v", "error", "-y", "-f", "lavfi",
                        "-i", "color=c=0x00B140:s=320x180:r=30:d=2,drawbox=x=80:y=45:w=160:h=90:color=red:t=fill",
                        "-f", "lavfi", "-i", "sine=frequency=1000:duration=2", "-c:v", "libx264", "-preset", "veryfast",
                        "-g", "30", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", SRC], check=True)


def clean():
    for f in os.listdir(PROJ):
        if f.startswith(TEST_STEMS):
            os.remove(os.path.join(PROJ, f))


def strip(path, crop):
    """Piksele RGB paska `crop` (w:h:x:y, jeden wiersz albo kolumna) na każdej klatce: [klatki, piksele, 3]."""
    w, h = (int(v) for v in crop.split(":")[:2])
    cp = subprocess.run([ciach.FFMPEG, "-v", "error", "-i", path, "-vf", f"format=rgb24,crop={crop}", "-f", "rawvideo",
                         "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
    return np.frombuffer(cp.stdout, dtype=np.uint8).reshape(-1, w * h, 3).astype(int)


def color(px) -> str:
    r, g, b = px
    if r > 150 and g < 90 and b < 90:
        return "R"
    if b > 150 and r < 90 and g < 90:
        return "B"
    if g > 110 and r < 90 and b < 110:
        return "G"
    return "?"


def frames_with(vals, c):
    return [i for i, v in enumerate(vals) if v == c]


def export(app, win, start, end, mode, mix, holes=None):
    r = app.start_export(start, end, mode, mix, holes)
    assert r["ok"], r
    ev = win.wait_for(lambda e: e["type"] == "export" and e["mode"] == mode and e["state"] in ("done", "error", "toobig", "toolong"), 600)
    assert ev["state"] == "done", ev
    return os.path.join(PROJ, ev["file"])


def nak(gen_, at, **kw):
    d = {"gen": gen_, "at": at, "segs": [[0.0, 2.0]], "gain": 1.0, "x": 0.5, "y": 0.5, "s": 0.5, "r": 0.0, "key": KEY}
    d.update(kw)
    return d


def main():
    gen()
    clean()

    # klucz: surowe YUV macierzą i zakresem pliku (chromakey sam liczyłby RGB zawsze jako BT.601)
    assert ciach.key_yuv([0, 255, 0], "bt709", False) == (173, 42, 26), ciach.key_yuv([0, 255, 0], "bt709", False)
    assert ciach.key_yuv([0, 255, 0], "bt601", False) == (145, 54, 34), ciach.key_yuv([0, 255, 0], "bt601", False)
    assert ciach.key_yuv([255, 255, 255], "bt709", True) == (255, 128, 128)

    app = ciach.App()
    win = ts.FakeWindow()
    app.window = win
    app.encoder = "x264"
    app.encoder_ready.set()

    app.add_nakladka(SRC)  # bez Sekwencji: odrzucona
    assert win.wait_for(lambda e: e["type"] == "reject")["message"].startswith("Nakładkę można dodać")
    app.load(BASE)
    ev = win.wait_for(lambda e: e["type"] == "loaded")
    win.wait_for(lambda e: e["type"] == "frames" and e["gen"] == ev["info"]["gen"])
    frames = struct.unpack("<%dd" % (len(app.media.frames) // 8), app.media.frames)
    assert len(frames) == 120
    app.add_nakladka(os.path.join(SP, "x.mp3"))
    assert win.wait_for(lambda e: e["type"] == "reject")["message"] == "Nakładką może być tylko plik MP4."
    app.add_nakladka(SRC, frames[30])
    ev = win.wait_for(lambda e: e["type"] == "nakladka")
    ng, info = ev["info"]["gen"], ev["info"]
    assert abs(ev["at"] - frames[30]) < 1e-9 and info["width"] == 320 and info["height"] == 180 and info["audioStreams"] == 1
    assert info["matrix"] == "bt601" and info["fullRange"] is False, info  # SD bez znacznika

    # tło Nakładki w YUV pliku = klucz przeliczony macierzą Nakładki (to porównuje chromakey)
    cp = subprocess.run([ciach.FFMPEG, "-v", "error", "-i", SRC, "-frames:v", "1", "-vf", "crop=8:8:0:0",
                         "-f", "rawvideo", "-pix_fmt", "yuv444p", "-"], capture_output=True, check=True)
    raw = np.frombuffer(cp.stdout, dtype=np.uint8).reshape(3, 64)
    yk, uk, vk = ciach.key_yuv(KEY, "bt601", False)
    assert abs(int(raw[1].mean()) - uk) <= 2 and abs(int(raw[2].mean()) - vk) <= 2, (raw[1].mean(), raw[2].mean(), uk, vk)

    # walidacja: nieznany gen, pusty odcinek, granice skali i obrotu
    r = app.resolve_naks(app.media, [nak(999, 0.0), nak(ng, 0.0, segs=[[1.0, 1.0]]), nak(ng, 0.0, s=9, r=270, x=-3)])
    assert len(r) == 1 and r[0]["s"] == ciach.NAK_MAX and r[0]["r"] == -90.0 and r[0]["x"] == 0.0, r
    assert r[0]["key"] == (yk, uk, vk)

    # 1. Ciach [0, 4): Nakładka od Klatki 30 przez 2 s, środek obrazu, szerokość 50 % (320 px, natywnie)
    out = export(app, win, 0.0, frames[119] + 1 / 30, "full", {"gain": 1.0, "podklady": [], "nakladki": [nak(ng, frames[30])]})
    row = strip(out, "640:1:0:180")
    centre = [color(p[320]) for p in row]
    keyed = [color(p[200]) for p in row]  # zielone tło Nakładki (x 160..240) → niebieskie
    print("1 Ciach:", os.path.basename(out), "klatek", len(row), "czerwone", frames_with(centre, "R")[:1], frames_with(centre, "R")[-1:])
    assert len(row) == 120 and frames_with(centre, "R") == list(range(30, 90)), centre
    assert set(keyed) == {"B"}, keyed
    # czerwony prostokąt 160 px szerokości wokół środka
    reds = [x for x in range(640) if color(row[45][x]) == "R"]
    assert abs(reds[0] - 240) <= 2 and abs(reds[-1] - 399) <= 2, (reds[0], reds[-1])
    vols = (ts.mean_volume(out, 1.2, 2.8), ts.mean_volume(out, 3.2, 3.9))
    print("  dźwięk Nakładki:", vols)
    assert vols[0] > -40 and vols[1] < -60, vols
    os.remove(out)

    # 2. pozycja, skala i obrót 90°: prostokąt 160x90 staje pionowo (90x160), w lewej górnej ćwiartce
    spec = nak(ng, frames[0], x=0.25, y=0.5, s=0.5, r=90.0, gain=0.0)
    out = export(app, win, 0.0, 1.0, "full", {"gain": 1.0, "podklady": [], "nakladki": [spec]})
    col = strip(out, "1:360:160:0")[10]
    row = strip(out, "640:1:0:180")[10]
    ys = [y for y in range(360) if color(col[y]) == "R"]
    xs = [x for x in range(640) if color(row[x]) == "R"]
    print("2 obrót: czerwone y", ys[:1], ys[-1:], "x", xs[:1], xs[-1:])
    assert abs(ys[0] - 100) <= 3 and abs(ys[-1] - 259) <= 3, ys
    assert abs(xs[0] - 115) <= 3 and abs(xs[-1] - 204) <= 3, xs
    assert color(row[230]) == "B"  # zielone tło obróconej Nakładki obok prostokąta: przezroczyste
    os.remove(out)

    # 3. Wycięcie [2,0; 2,5) Sekwencji: Nakładka gra dalej w czasie Sekwencji (60 klatek bez przerwy)
    hole = [[frames[60], frames[75]]]
    out = export(app, win, 0.0, frames[119] + 1 / 30, "full", {"gain": 1.0, "podklady": [], "nakladki": [nak(ng, frames[30])]}, hole)
    centre = [color(p[320]) for p in strip(out, "640:1:0:180")]
    print("3 szew: klatek", len(centre), "czerwone", frames_with(centre, "R")[:1], frames_with(centre, "R")[-1:])
    assert len(centre) == 105 and frames_with(centre, "R") == list(range(30, 90)), centre
    os.remove(out)

    # 4. Zbliżenie 2× na środek w Klatkach 45..60 powiększa też Nakładkę: czerwony od x≈160 zamiast 240
    zoom = {"at": frames[45], "end": frames[60], "rin": 0, "rout": 0, "keys": [{"t": frames[45], "x": 0.25, "y": 0.25, "s": 0.5}]}
    out = export(app, win, frames[30], frames[90], "full",
                 {"gain": 1.0, "podklady": [], "zblizenia": [zoom], "nakladki": [nak(ng, frames[30], gain=0.0)]})
    row = strip(out, "640:1:0:180")
    left = [color(p[180]) for p in row]
    print("4 Zbliżenie: czerwone w x=180", frames_with(left, "R")[:1], frames_with(left, "R")[-1:])
    assert frames_with(left, "R") == list(range(15, 30)), left
    os.remove(out)

    # 5. odcinki Nakładki (Wycięcie na Nakładce, 1 s) i dwie warstwy: wyższa (128x72, klucz magenta, więc
    # z tłem, które despill przyciemnia do ~(0, 32, 64)) przykrywa środek niższej, a niższa wystaje po bokach
    spec_a = nak(ng, frames[0], segs=[[0.0, 0.5], [1.5, 2.0]], gain=0.0)
    spec_b = nak(ng, frames[0], x=0.5, y=0.5, s=0.2, gain=0.0, key=[255, 0, 255])
    cmd = app.build_cmd(app.media, ciach.Fragment(0.0, 2.0), "x.mp4", "x264", None, False,
                        app.resolve_naks(app.media, [spec_a, spec_b]))
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "split=2" in fc and "concat=n=2:v=1:a=0" in fc and fc.count("overlay=") == 2, fc
    out = export(app, win, 0.0, 2.0, "full", {"gain": 1.0, "podklady": [], "nakladki": [spec_a, spec_b]})
    row = strip(out, "640:1:0:180")
    print("5 odcinki: klatek", len(row))
    assert len(row) == 60
    f10 = [color(p) for p in row[10]]
    assert f10[245] == "R" and f10[270] == "?" and f10[320] == "R" and f10[390] == "R", "".join(f10[230:410])
    assert abs(row[10][270][1] - 32) <= 12 and abs(row[10][270][2] - 64) <= 12, row[10][270]  # despill: g = (r + b) / 2
    assert color(row[40][245]) == "B" and color(row[40][270]) == "?"  # niższa skończyła się po 1 s
    os.remove(out)

    # 6. Mały Ciach z Nakładką i jej dźwiękiem (oba przebiegi z overlay)
    out = export(app, win, 0.0, frames[119] + 1 / 30, "small", {"gain": 1.0, "podklady": [], "nakladki": [nak(ng, frames[30])]})
    centre = [color(p[320]) for p in strip(out, "640:1:0:180")]
    print("6 Mały Ciach:", os.path.basename(out), "czerwone", len(frames_with(centre, "R")))
    assert frames_with(centre, "R") == list(range(30, 90)), centre
    assert ts.mean_volume(out, 1.2, 2.8) > -40
    os.remove(out)

    # bez Nakładek polecenie jak dawniej
    cmd = app.build_cmd(app.media, ciach.Fragment(1.0, 2.0), "x.mp4", "x264", None, False, [])
    assert "-filter_complex" not in cmd and "copy" in cmd

    app.load(BASE)  # podmiana sesji czyści Nakładki
    win.wait_for(lambda e: e["type"] == "loaded")
    assert not app.nakladki
    app.on_closing()
    clean()
    print("ALL OK")


if __name__ == "__main__":
    main()
