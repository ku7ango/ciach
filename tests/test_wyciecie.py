"""Test backendu Wycięć (ADR 0002): Ciach z dziurami w obrazie i dźwięku, Zbliżenie przez szew,
Podkład z odcinkami (po Wycięciu na Podkładzie), mp3 bez strat, Mały Ciach, sklejanie z kawałkami
(dublowanie kopii, remap). Bez okna (atrapa `window` jak w test_sekwencja.py).

Użycie: venv/Scripts/python tests/test_wyciecie.py
"""
import os
import struct
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SP = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(SP)
sys.path.insert(0, PROJ)
sys.path.insert(0, SP)
import ciach  # noqa: E402
import test_sekwencja as ts  # noqa: E402
import test_zblizenie as tz  # noqa: E402

T = os.path.join(SP, "_ton_cisza_ton.mp3")  # 6 s: ton 1 kHz 0–2 s, cisza 2–4 s, ton 4–6 s
TEST_STEMS = ("_seq_a_ciach", "_zoom_src_ciach", "_ton_cisza_ton_ciach")


def gen_tct(path):
    if os.path.exists(path):
        return
    subprocess.run([ciach.FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=1000:duration=6",
                    "-af", "volume=enable='between(t,2,4)':volume=0", "-c:a", "libmp3lame", "-b:a", "128k", path],
                   check=True)


def clean():
    for f in os.listdir(PROJ):
        if f.startswith(TEST_STEMS):
            os.remove(os.path.join(PROJ, f))


def export(app, win, start, end, mode, mix, holes):
    r = app.start_export(start, end, mode, mix, holes)
    assert r["ok"], r
    ev = win.wait_for(lambda e: e["type"] == "export" and e["mode"] == mode and e["state"] in ("done", "error", "toobig", "toolong"), 600)
    assert ev["state"] == "done", ev
    return os.path.join(PROJ, ev["file"])


def load(app, win, path):
    app.load(path)
    ev = win.wait_for(lambda e: e["type"] == "loaded" and e["reason"] == "open")
    win.wait_for(lambda e: e["type"] == "frames" and e["gen"] == ev["info"]["gen"])
    return struct.unpack("<%dd" % (len(app.media.frames) // 8), app.media.frames)


def main():
    ts.gen(ts.A, 4.0)
    ts.gen(ts.B, 2.5)
    tz.gen_halves(tz.SRC, 4.0, "red", "blue")
    gen_tct(T)
    clean()
    app = ciach.App()
    win = ts.FakeWindow()
    app.window = win
    app.encoder = "x264"
    app.encoder_ready.set()

    # Fragment: dziury przycinane do zakresu, scalane, czas Sekwencji i odcinki
    fr = ciach.Fragment(1.0, 5.0, [[3.0, 3.5], [2.0, 3.0], [0.0, 1.2], [4.9, 9.0], [6, 7]])
    print("1 fragment:", fr.holes, fr.segments(), round(fr.dur, 3))
    assert fr.holes == [(1.0, 1.2), (2.0, 3.5), (4.9, 5.0)] and abs(fr.dur - 2.2) < 1e-9
    assert fr.segments() == [(1.2, 2.0), (3.5, 4.9)]
    assert abs(fr.seq(3.5) - 1.8) < 1e-9 and abs(fr.seq(2.5) - 1.8) < 1e-9 and abs(fr.seq(4.0) - 2.3) < 1e-9
    assert abs(ciach.App.file_time(fr, 1.8) - 3.5) < 1e-9 and abs(ciach.App.file_time(fr, 2.3) - 4.0) < 1e-9
    assert fr.pre == 0.0 and fr.graph(4.0) == fr.seq(4.0)
    assert ciach.Fragment(1.0, 2.0).cut_filters() == []
    f2 = ciach.Fragment(4.0, 6.0, [[4.5, 5.0]])
    assert f2.pre == 1.0 and f2.cut_filters() == ["select='between(t,2.999500,3.499500)+between(t,3.999500,4.999500)'",
                                                  "setpts='PTS-(gte(T,3.999500)*0.500000)/TB'"], f2.cut_filters()

    # Obraz: Ciach [0.5, 3.5) z dziurą [1.0, 2.0) → 60 klatek, oba strumienie od zera, długość 2,0 s,
    # dźwięk AAC (kopia 1:1 nie umie pominąć dziury)
    frames = load(app, win, ts.A)
    assert len(frames) == 120
    out = export(app, win, frames[15], frames[105], "full", None, [[frames[30], frames[60]]])
    nf, audio = ts.nb_frames(out)
    d = ts.probe(out, "stream=start_time:format=duration")
    print("2 hole:", os.path.basename(out), "frames", nf, "audio", [a["codec_name"] for a in audio],
          "dur", d["format"]["duration"], "start", [x["start_time"] for x in d["streams"]])
    assert nf == 60 and len(audio) == 1 and audio[0]["codec_name"] == "aac"
    assert abs(float(d["format"]["duration"]) - 2.0) < 0.05 and all(abs(float(x["start_time"])) < 0.002 for x in d["streams"])
    # bez dziur polecenie jest takie jak dawniej: kopia audio, bez filter_complex
    cmd = app.build_cmd(app.media, ciach.Fragment(frames[15], frames[105]), "x.mp4", "x264", None, False)
    assert "-filter_complex" not in cmd and "copy" in cmd

    # Dźwięk przez szew: Podkład (ton) zaczepiony za dziurą trzyma się swojej Klatki, więc w wyniku
    # zaczyna się w czasie Sekwencji 1,5 s (plik 2,5 s minus dziura 1 s) i trwa 1 s
    app.add_podklad(ts.P)
    pg = win.wait_for(lambda e: e["type"] == "podklad")["info"]["gen"]
    mix = {"gain": 1.0, "podklady": [{"gen": pg, "at": frames[75], "segs": [[0.0, 1.0]], "gain": 1.0}]}
    out = export(app, win, frames[0], app.media.duration, "full", mix, [[frames[30], frames[60]]])
    vols = [ts.mean_volume(out, 0.0, 1.4), ts.mean_volume(out, 1.6, 2.4), ts.mean_volume(out, 2.6, 3.0)]
    nf, audio = ts.nb_frames(out)
    print("3 podklad za dziura:", os.path.basename(out), "frames", nf, "vol", [round(v) for v in vols])
    assert nf == 90 and vols[0] < -60 and vols[1] > -25 and vols[2] < -60

    # Podkład z odcinkami (Wycięcie na Podkładzie): ton|cisza|ton, odcinki [1,2] i [4,5] → 2 s ciągłego tonu
    app.add_podklad(T)
    tg = win.wait_for(lambda e: e["type"] == "podklad")["info"]["gen"]
    mix = {"gain": 1.0, "podklady": [{"gen": tg, "at": frames[0], "segs": [[1.0, 2.0], [4.0, 5.0]], "gain": 1.0}]}
    out = export(app, win, frames[0], frames[90], "full", mix, None)
    vols = [ts.mean_volume(out, 0.1, 0.9), ts.mean_volume(out, 1.1, 1.9), ts.mean_volume(out, 2.1, 2.9)]
    print("4 podklad segs:", os.path.basename(out), "vol", [round(v) for v in vols])
    assert vols[0] > -25 and vols[1] > -25 and vols[2] < -60
    # Podkład zaczynający się przed `pre` traci początek odcinków, nie ich kolejność
    mix = {"gain": 1.0, "podklady": [{"gen": tg, "at": frames[0], "segs": [[1.0, 2.0], [4.0, 5.0]], "gain": 1.0}]}
    out = export(app, win, frames[105], app.media.duration, "full", mix, None)
    v = ts.mean_volume(out, 0.0, 0.4)
    print("   za pre:", os.path.basename(out), "vol", round(v))
    assert v < -60, "po 2 s odcinków Podkład milczy (3,5 s > 2 s)"
    app.remove_podklad(tg)

    # Zbliżenie przez szew: statyczne [1.0, 3.0) z dziurą [1.5, 2.5) w Ciachu [0.5, 3.5) → klatki 15..44
    # niebieskie (30 zachowanych z 60); przejazd niebieski → czerwony liniowy w czasie Sekwencji: bez skoku na szwie
    frames = load(app, win, tz.SRC)
    kadr = {"x": 0.5, "y": 0.0, "s": 0.5}
    red = {"x": 0.0, "y": 0.0, "s": 0.5}
    key = lambda t, k: {"t": t, **k}  # noqa: E731
    holes = [[frames[45], frames[75]]]
    mix = {"gain": 1.0, "podklady": [], "zblizenia": [{"at": frames[30], "end": frames[90], "rin": 0, "rout": 0, "keys": [key(frames[30], kadr)]}]}
    out = export(app, win, frames[15], frames[105], "full", mix, holes)
    vals = tz.uavg(out)
    print("5 zoom static przez szew:", os.path.basename(out), "frames", len(vals), "blue", tz.blue_frames(vals)[:1], tz.blue_frames(vals)[-1:])
    assert len(vals) == 60 and tz.blue_frames(vals) == list(range(15, 45)), tz.blue_frames(vals)
    mix = {"gain": 1.0, "podklady": [], "zblizenia": [{"at": frames[30], "end": frames[90], "rin": 0, "rout": 0,
                                                       "keys": [key(frames[30], kadr), key(frames[89], red)]}]}
    out = export(app, win, frames[15], frames[105], "full", mix, holes)
    vals = tz.uavg(out)
    mv = vals[15:45]
    steps = [mv[i] - mv[i + 1] for i in range(len(mv) - 1)]
    print("6 zoom przejazd przez szew:", os.path.basename(out), "U", [round(v) for v in mv[::5]], "max krok", round(max(steps), 1))
    assert all(st > 0 for st in steps), "przejazd ma być monotoniczny także przez szew"
    assert max(steps) < 2.5 * (sum(steps) / len(steps)), "na szwie nie ma skoku: Kadr liniowy w czasie Sekwencji"
    # Rampa liczona w czasie Sekwencji: 0,5 s Rampy wejścia z dziurą w środku
    mix = {"gain": 1.0, "podklady": [], "zblizenia": [{"at": frames[30], "end": frames[90], "rin": 1.0, "rout": 0, "keys": [key(frames[30], kadr)]}]}
    out = export(app, win, frames[15], frames[105], "full", mix, holes)
    vals = tz.uavg(out)
    rin = vals[15:45]
    print("7 rampa przez szew:", [round(v) for v in rin[::5]])
    assert all(rin[i] < rin[i + 1] for i in range(len(rin) - 1)) and rin[-1] > tz.BLUE and rin[0] < 175

    # Mały Ciach z dziurą: liczba klatek, jedna ścieżka AAC
    out = export(app, win, frames[15], frames[105], "small", None, holes)
    nf, audio = ts.nb_frames(out)
    print("8 maly:", os.path.basename(out), "frames", nf, "audio", [a["codec_name"] for a in audio], "size", os.path.getsize(out))
    assert nf == 60 and len(audio) == 1 and audio[0]["codec_name"] == "aac"
    assert app.export_tmp is None

    # mp3: dziura [2, 4) usuwa ciszę z ton|cisza|ton → 4 s ciągłego tonu, nadal mp3 (bez przekodowania)
    frames = load(app, win, T)
    i2, i4 = min(range(len(frames)), key=lambda i: abs(frames[i] - 2.0)), min(range(len(frames)), key=lambda i: abs(frames[i] - 4.0))
    out = export(app, win, frames[0], app.media.duration, "full", None, [[frames[i2], frames[i4]]])
    d = ts.probe(out, "stream=codec_name,bit_rate:format=duration")
    vols = [ts.mean_volume(out, 0.2, 1.8), ts.mean_volume(out, 2.2, 3.8)]
    print("9 mp3:", os.path.basename(out), d["streams"][0]["codec_name"], d["format"]["duration"], "vol", [round(v) for v in vols])
    assert d["streams"][0]["codec_name"] == "mp3" and abs(float(d["format"]["duration"]) - 4.0) < 0.1
    assert vols[0] > -25 and vols[1] > -25
    out = export(app, win, frames[0], app.media.duration, "small", None, [[frames[i2], frames[i4]]])
    d = ts.probe(out, "stream=codec_name:format=duration")
    print("   maly mp3:", os.path.basename(out), d["format"]["duration"])
    assert abs(float(d["format"]["duration"]) - 4.0) < 0.1 and app.export_tmp is None

    # Sklejanie z kawałkami: A pocięte na [0,1) i [2,4). B na koniec: sąsiednie kawałki tej samej
    # kopii idą do pliku raz (kopie A, B); B między kawałki: kopia A dublowana (A, B, A);
    # remap mówi UI, o ile przesunąć czasy starych kawałków
    load(app, win, ts.A)
    assert app.set_parts([{"src": 0, "in": 0.0, "out": 1.0}, {"src": 0, "in": 2.0, "out": 4.0}])["ok"]
    assert win.title.endswith("_seq_a.mp4 +1")
    app.join([ts.B], 2)
    ev = win.wait_for(lambda e: e["type"] == "join" and e["state"] == "done")
    lo = win.wait_for(lambda e: e["type"] == "loaded" and e["reason"] == "join")
    parts = lo["info"]["parts"]
    print("10 join na koniec:", [(p["name"], p["start"], p["in"], p["out"]) for p in parts], "remap", ev["remap"])
    assert [(p["name"], p["src"], p["in"], p["out"]) for p in parts] == [("_seq_a.mp4", 0, 0.0, 1.0), ("_seq_a.mp4", 0, 2.0, 4.0), ("_seq_b.mp4", 1, 0.0, 2.5)]
    assert len(app.media.copies) == 2 and ev["remap"] == [[0.0, 1.0, 0.0], [2.0, 4.0, 0.0]] and ev["inserted"] == [2, 2.5]
    assert abs(lo["info"]["duration"] - 6.5) < 0.1 and win.title.endswith("_seq_a.mp4 +2")
    # teraz B (kawałek 2) usunięte przez UI i nowe B wstawione między kawałki A
    assert app.set_parts([{"src": 0, "in": 0.0, "out": 1.0}, {"src": 0, "in": 2.0, "out": 4.0}])["ok"]
    app.join([ts.B], 1)
    ev = win.wait_for(lambda e: e["type"] == "join" and e["state"] == "done")
    lo = win.wait_for(lambda e: e["type"] == "loaded" and e["reason"] == "join")
    parts = lo["info"]["parts"]
    print("    join w środek:", [(p["name"], p["start"], p["in"], p["out"]) for p in parts], "remap", ev["remap"])
    assert [p["name"] for p in parts] == ["_seq_a.mp4", "_seq_b.mp4", "_seq_a.mp4"]
    assert [p["src"] for p in parts] == [0, 1, 2] and [round(p["start"], 2) for p in parts] == [0.0, 4.0, 6.5]
    assert [(p["in"], p["out"]) for p in parts] == [(0.0, 1.0), (0.0, 2.5), (2.0, 4.0)]
    assert ev["remap"] == [[0.0, 1.0, 0.0], [2.0, 4.0, 6.5]] and ev["inserted"] == [1, 2.5]
    assert abs(lo["info"]["duration"] - 10.5) < 0.1 and len(app.media.copies) == 3

    app.on_closing()
    clean()
    print("ALL OK")


if __name__ == "__main__":
    main()
