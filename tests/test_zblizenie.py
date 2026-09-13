"""Test backendu Zbliżeń: Ciach i Mały Ciach z Kadrem stojącym, z Rampami i przejazdem między
pozycjami, z trzema pozycjami (postój, przejazd, postój), w sklejonej Sekwencji i razem z miksem. Bez okna (atrapa `window` jak w test_sekwencja.py).

Źródło testowe: lewa połowa obrazu czerwona, prawa niebieska. Kadr w prawej połowie daje
klatkę w całości niebieską, więc `signalstats` (średnia chrominancji U per klatka) mówi
co do klatki, gdzie Zbliżenie działa: połówki ≈ 165, sam niebieski ≈ 240.

Użycie: venv/Scripts/python tests/test_zblizenie.py
"""
import os
import re
import struct
import subprocess
import sys

SP = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(SP)
sys.path.insert(0, PROJ)
sys.path.insert(0, SP)
import ciach  # noqa: E402
import test_sekwencja as ts  # noqa: E402

SRC = os.path.join(SP, "_zoom_src.mp4")  # 4 s, 30 fps, czerwony | niebieski
PRE = os.path.join(SP, "_zoom_pre.mp4")  # 2 s, zielony (do sklejenia przed SRC)
TEST_STEMS = ("_zoom_src_ciach", "_zoom_pre_ciach")
BLUE = 200   # UAVG powyżej: klatka cała niebieska
HALF = (120, 200)


def gen_halves(path, dur, left, right):
    if os.path.exists(path):
        return
    cmd = [ciach.FFMPEG, "-v", "error", "-y",
           "-f", "lavfi", "-i", f"color={left}:s=640x720:r=30:d={dur}",
           "-f", "lavfi", "-i", f"color={right}:s=640x720:r=30:d={dur}",
           "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
           "-filter_complex", "[0:v][1:v]hstack[v]", "-map", "[v]", "-map", "2:a",
           "-c:v", "libx264", "-preset", "veryfast", "-g", "30", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path]
    subprocess.run(cmd, check=True)


def uavg(path):
    cp = subprocess.run([ciach.FFMPEG, "-v", "info", "-i", path, "-vf",
                         "signalstats,metadata=print:key=lavfi.signalstats.UAVG:file=-", "-f", "null", "-"],
                        capture_output=True, text=True)
    return [float(m) for m in re.findall(r"lavfi.signalstats.UAVG=([\d.]+)", cp.stdout)]


def blue_frames(vals):
    return [i for i, v in enumerate(vals) if v > BLUE]


def clean():
    for f in os.listdir(PROJ):
        if f.startswith(TEST_STEMS):
            os.remove(os.path.join(PROJ, f))


def export(app, win, start, end, mode, mix):
    r = app.start_export(start, end, mode, mix)
    assert r["ok"], r
    ev = win.wait_for(lambda e: e["type"] == "export" and e["mode"] == mode and e["state"] in ("done", "error", "toobig"), 600)
    assert ev["state"] == "done", ev
    return os.path.join(PROJ, ev["file"])


def main():
    gen_halves(SRC, 4.0, "red", "blue")
    gen_halves(PRE, 2.0, "green", "green")
    clean()
    app = ciach.App()
    win = ts.FakeWindow()
    app.window = win
    app.encoder = "x264"
    app.encoder_ready.set()

    # plik poleceń: stały Kadr = [enter], ruch = [expr] z TI, przerwy resetują do całości
    m = ciach.Media(SRC, 0)
    m.probe()
    assert app.resolve_zoom(m, None) == [] and app.resolve_zoom(m, [{"at": 1, "end": 1}]) == []
    spec = [{"at": 1.0, "end": 2.0, "rin": 0.25, "rout": 0,
             "keys": [{"t": 1.0, "x": 0.5, "y": 0, "s": 0.5}, {"t": 2.0, "x": 0.5, "y": 0.5, "s": 0.5}]},
            {"at": 2.7, "end": 3.2, "keys": [{"t": 2.7}]},  # nachodzi na wcześniejsze (po sortowaniu) → odrzucone
            {"at": 2.5, "end": 3.0, "keys": [{"t": 2.5, "x": 0.9, "y": 0.9, "s": 0.05}]},  # za mały Kadr: 20 % i w obrazie
            {"at": 3.5, "end": 3.8, "keys": []}]  # bez pozycji → odrzucone
    z = app.resolve_zoom(m, spec)
    assert [round(q["at"], 2) for q in z] == [1.0, 2.5], z
    assert z[1]["keys"][0]["k"] == {"x": 0.8, "y": 0.8, "s": 0.2}, z[1]
    cmds = app.zoom_commands(z[:1], 0.0, 1280, 720)
    print("1 cmd:\n" + cmds)
    lines = cmds.strip().splitlines()
    # Rampa wejścia [1,1.25): Kadr rusza się i Rampa rośnie → wyrażenie kwadratowe; potem sam przejazd (liniowy)
    assert lines[0].startswith("0.999500-1.249500 [expr] crop w '1280.00+") and "*TI*TI'" in lines[0]
    assert lines[1].startswith("1.249500-1.999500 [expr] crop w '640.00+0.00*TI+0.00*TI*TI'") and "crop y '90.00+270.00*TI+0.00*TI*TI'" in lines[1]
    assert lines[2].startswith("1.999500-") and "[enter] crop w 1280.00" in lines[2]
    assert "," not in cmds.replace(", [", "")  # przecinek tylko między poleceniami
    # zaczyna od całości (w=1280), w połowie Rampy Kadr jest w połowie drogi do pozycji
    assert abs(app.kadr_keys(z[0], 1.5)["y"] - 0.25) < 1e-9 and app.ramp_factor(z[0], 1.125) == 0.5

    app.load(SRC)
    ev = win.wait_for(lambda e: e["type"] == "loaded")
    gen = ev["info"]["gen"]
    win.wait_for(lambda e: e["type"] == "frames" and e["gen"] == gen)
    frames = struct.unpack("<%dd" % (len(app.media.frames) // 8), app.media.frames)
    assert len(frames) == 120

    # Ciach [0.5, 2.5) ze statycznym Zbliżeniem [1.0, 2.0) na prawą górną ćwiartkę → klatki 15..44 niebieskie
    kadr = {"x": 0.5, "y": 0.0, "s": 0.5}
    key = lambda t, k: {"t": t, **k}  # noqa: E731
    mix = {"gain": 1.0, "podklady": [], "zblizenia": [{"at": frames[30], "end": frames[60], "rin": 0, "rout": 0, "keys": [key(frames[30], kadr)]}]}
    out = export(app, win, frames[15], frames[75], "full", mix)
    nf, audio = ts.nb_frames(out)
    vals = uavg(out)
    print("2 static:", os.path.basename(out), "frames", nf, "blue", blue_frames(vals)[:1], blue_frames(vals)[-1:], len(blue_frames(vals)),
          "audio", [a["codec_name"] for a in audio])
    assert nf == 60 and len(vals) == 60
    assert blue_frames(vals) == list(range(15, 45)), blue_frames(vals)
    assert all(HALF[0] < v < HALF[1] for v in vals[:15] + vals[45:])
    assert audio and audio[0]["codec_name"] == "aac"
    d = ts.probe(out, "stream=width,height")
    assert d["streams"][0]["width"] == 1280 and d["streams"][0]["height"] == 720

    # Rampy i przejazd: Zbliżenie [1.0, 3.0), Rampa wejścia 0,5 s, wyjścia 0,5 s, pozycje: prawa górna na
    # starcie → prawa dolna na końcu (obie niebieskie). U rośnie w Rampie wejścia, jest niebieskie w
    # środku, maleje w Rampie wyjścia.
    mix = {"gain": 1.0, "podklady": [], "zblizenia": [{"at": frames[30], "end": frames[90], "rin": 0.5, "rout": 0.5,
                                                       "keys": [key(frames[30], kadr), key(frames[89], {"x": 0.5, "y": 0.5, "s": 0.5})]}]}
    out = export(app, win, frames[15], frames[105], "full", mix)
    vals = uavg(out)
    print("3 ramps:", os.path.basename(out), "frames", len(vals), "ramp in", [round(v) for v in vals[15:31:3]],
          "core", round(min(vals[31:59])), "ramp out", [round(v) for v in vals[60:76:3]])
    assert len(vals) == 90
    rin = vals[15:30]
    assert all(rin[i] < rin[i + 1] for i in range(len(rin) - 1)), "Rampa wejścia powinna rosnąć monotonicznie"
    assert all(HALF[0] < v < HALF[1] for v in vals[:15]) and rin[0] < 175 and rin[-1] > 220
    assert min(vals[31:59]) > BLUE, "między Rampami cały czas niebiesko"
    rout = vals[60:75]
    assert all(rout[i] > rout[i + 1] for i in range(len(rout) - 1)), "Rampa wyjścia powinna maleć"
    assert all(HALF[0] < v < HALF[1] for v in vals[75:])

    # Trzy pozycje: postój (prawa górna, niebieska) 1,0–1,5, przejazd do lewej górnej (czerwona) 1,5–2,0,
    # postój na czerwonej do końca 2,5. Ciach [0.5, 2.5): klatki 15..29 niebieskie, 30..44 U maleje, 45..59 czerwone.
    red = {"x": 0.0, "y": 0.0, "s": 0.5}
    mix3 = {"gain": 1.0, "podklady": [], "zblizenia": [{"at": frames[30], "end": frames[75], "rin": 0, "rout": 0,
                                                        "keys": [key(frames[30], kadr), key(frames[45], kadr), key(frames[60], red)]}]}
    out = export(app, win, frames[15], frames[75], "full", mix3)
    vals = uavg(out)
    print("3b keys:", os.path.basename(out), "hold blue", round(min(vals[15:30])), "move", [round(v) for v in vals[30:46:3]],
          "hold red", round(max(vals[45:])))
    assert len(vals) == 60 and all(HALF[0] < v < HALF[1] for v in vals[:15])
    assert min(vals[15:30]) > BLUE and max(vals[45:]) < HALF[0]
    mv = vals[30:46]
    assert all(mv[i] > mv[i + 1] for i in range(len(mv) - 1)), "przejazd niebieski → czerwony ma być monotoniczny"

    # Mały Ciach ze Zbliżeniem i miksem (Głośność 50 %): ten sam obraz, jedna ścieżka AAC
    mix["gain"] = 0.5
    out = export(app, win, frames[15], frames[105], "small", mix)
    vals = uavg(out)
    nf, audio = ts.nb_frames(out)
    print("4 small:", os.path.basename(out), "frames", nf, "core min", round(min(vals[31:59])), "size", os.path.getsize(out))
    assert nf == 90 and min(vals[31:59]) > BLUE and all(HALF[0] < v < HALF[1] for v in vals[:15])
    assert len(audio) == 1 and audio[0]["codec_name"] == "aac"
    assert app.export_tmp is None and not os.path.exists(os.path.join(os.path.dirname(out), ciach.ZOOM_CMD))

    # Sekwencja: PRE (2 s, zielony) przed SRC. Zbliżenie w drugiej części [3.0, 4.0) czasu Sekwencji,
    # Ciach [2.5, 4.5): plik tymczasowy concat ma inne pts niż źródło, a klatki 15..44 mają być niebieskie.
    app.join([PRE], 0)
    ev = win.wait_for(lambda e: e["type"] == "loaded" and e["reason"] == "join")
    assert len(ev["info"]["parts"]) == 2 and abs(ev["info"]["parts"][1]["start"] - 2.0) < 0.01
    win.wait_for(lambda e: e["type"] == "frames" and e["gen"] == ev["info"]["gen"])
    frames = struct.unpack("<%dd" % (len(app.media.frames) // 8), app.media.frames)
    assert len(frames) == 180, len(frames)
    mix = {"gain": 1.0, "podklady": [], "zblizenia": [{"at": frames[90], "end": frames[120], "rin": 0, "rout": 0, "keys": [key(frames[90], kadr)]}]}
    out = export(app, win, frames[75], frames[135], "full", mix)
    vals = uavg(out)
    print("5 sekwencja:", os.path.basename(out), "frames", len(vals), "blue", blue_frames(vals)[:1], blue_frames(vals)[-1:], len(blue_frames(vals)))
    assert len(vals) == 60 and blue_frames(vals) == list(range(15, 45)), blue_frames(vals)

    # bez Zbliżeń polecenie jest takie jak dawniej (bez filter_complex, kopia audio)
    cmd = app.build_cmd(app.media, ciach.Fragment(1.0, 2.0), "x.mp4", "x264", None, False)
    assert "-filter_complex" not in cmd and "copy" in cmd
    cmd = app.build_cmd(app.media, ciach.Fragment(1.0, 2.0), "x.mp4", "x264", None, True)
    assert "-filter_complex" in cmd and "[0:v:0]sendcmd=f=zoom.cmd,crop=w=iw:h=ih:x=0:y=0,scale=1280:720[v]" in cmd

    app.on_closing()
    clean()
    print("ALL OK")


if __name__ == "__main__":
    main()
