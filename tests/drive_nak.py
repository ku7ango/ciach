"""Test UI Nakładek. Steruje oknem przez endpoint debugowy (CIACH_DEBUG=1), zrzuty przez PrintWindow
po PID własnego procesu, bez SendKeys i bez zabierania fokusu. Mysz na podglądzie i timeline to
syntetyczne PointerEvent; obraz Nakładki sprawdza `__ciach.nakPixel` (piksel płótna WebGL zaraz po
narysowaniu), więc test widzi to, co policzył shader klucza.

Użycie:  venv/Scripts/python tests/drive_nak.py [--exe]
Pliki testowe `_nak_base.mp4` (niebieski) i `_nak_src.mp4` (zielone tło, czerwony środek) generuje
test_nakladka.py.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

SP = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(SP)
sys.path.insert(0, SP)
import test_nakladka as tn  # noqa: E402
import test_sekwencja as ts  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

tn.gen()
TEST_STEMS = tn.TEST_STEMS
USE_EXE = "--exe" in sys.argv
PORTFILE = os.path.join(SP, "_port_nak.txt")
if os.path.exists(PORTFILE):
    os.remove(PORTFILE)
env = dict(os.environ, CIACH_DEBUG="1", CIACH_PORTFILE=PORTFILE, PYTHONIOENCODING="utf-8")
log = open(os.path.join(SP, "_app_nak.log"), "w", encoding="utf-8")
tn.clean()
cmd = [os.path.join(PROJ, "Ciach.exe"), tn.BASE] if USE_EXE else [sys.executable, os.path.join(PROJ, "ciach.py"), tn.BASE]
proc = subprocess.Popen(cmd, cwd=PROJ, env=env, stdout=subprocess.DEVNULL, stderr=log)
while not os.path.exists(PORTFILE):
    if proc.poll() is not None:
        raise SystemExit("app exited early rc=%s" % proc.returncode)
    time.sleep(0.1)
port = int(open(PORTFILE).read().strip())


def js(code, timeout=30):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/debug/js", data=code.encode("utf-8"), method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"))


def wait(code, timeout=60, msg=""):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if js(code):
                return True
        except Exception:
            pass
        time.sleep(0.25)
    raise SystemExit("TIMEOUT waiting: " + (msg or code))


def shot(name):
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        os.path.join(SP, "shot_window.ps1"), "-Out", os.path.join(SP, name), "-ProcId", str(proc.pid)],
                       capture_output=True, text=True)
    print("  shot:", r.stdout.strip() or r.stderr.strip())


def close_app():
    """Zamyka wyłącznie okno procesu uruchomionego przez test (po PID, nigdy po tytule)."""
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "$ids=@(%d)+@(Get-CimInstance Win32_Process -Filter 'ParentProcessId = %d' | %%{ $_.ProcessId });"
                    "Get-Process | ? { $ids -contains $_.Id -and $_.MainWindowHandle -ne 0 } | %%{ $_.CloseMainWindow() | Out-Null }"
                    % (proc.pid, proc.pid)], capture_output=True)


def keydown(code, shift=False, ctrl=False):
    js("window.dispatchEvent(new KeyboardEvent('keydown',{code:'%s',shiftKey:%s,ctrlKey:%s,bubbles:true,cancelable:true})); true"
       % (code, str(shift).lower(), str(ctrl).lower()))


def keyup(code):
    js("window.dispatchEvent(new KeyboardEvent('keyup',{code:'%s',bubbles:true})); true" % code)


def key(code, shift=False, ctrl=False):
    keydown(code, shift, ctrl)
    keyup(code)


def pointer(el, kind, x, y, ctrl=False):
    js("(()=>{const c=document.getElementById('%s');const r=c.getBoundingClientRect();"
       "c.dispatchEvent(new PointerEvent('%s',{clientX:r.left+%s,clientY:r.top+%s,button:0,buttons:1,pointerId:1,ctrlKey:%s,bubbles:true}));return true})()"
       % (el, kind, x, y, str(ctrl).lower()))


def drag(el, pts, ctrl=False):
    pointer(el, "pointerdown", *pts[0], ctrl)
    for p in pts[1:]:
        pointer(el, "pointermove", *p, ctrl)
    pointer(el, "pointerup", *pts[-1], ctrl)
    time.sleep(0.2)


def click(el, x, y):
    pointer(el, "pointerdown", x, y)
    pointer(el, "pointerup", x, y)
    time.sleep(0.15)


def x_of_s(s):
    return js("(()=>{const S=window.__ciach.S;const W=document.getElementById('tl').clientWidth;"
              "return (%r - S.view.start)/(S.view.end-S.view.start)*W})()" % s)


def frame_ts(i):
    return js("window.__ciach.frameTs(%d)" % i)


def seq_ts(i):
    return js("window.__ciach.S.seqs[%d]" % i)


def seek_frame(i):
    js("window.__ciach.video.currentTime = window.__ciach.frameTs(%d) + 0.001; true" % i)
    time.sleep(0.4)
    wait("(()=>{const n=window.__ciach.S.naks[0];return !n||!n.audio.seeking})()", 10, "nak seek")
    time.sleep(0.15)


def vrect():
    return json.loads(js("JSON.stringify(window.__ciach.videoRect())"))


def px(R, fx, fy):
    return R["x"] + fx * R["w"], R["y"] + fy * R["h"]


def pixel(R, fx, fy):
    return js("window.__ciach.nakPixel(%r, %r)" % px(R, fx, fy))


def state():
    return js("(()=>{const S=window.__ciach.S;const st=document.getElementById('status');"
              "return {N:S.N,sel:S.sel,gKey:S.gKey,cut:S.cut,undo:S.undo.length,tlH:document.getElementById('tl').clientHeight,"
              "naks:S.naks.map(n=>({gen:n.gen,at:n.at,segs:n.segs,gain:n.gain,pos:n.pos,key:n.key,want:n.want,ready:n.ready,"
              "start:window.__ciach.podStart(n),len:window.__ciach.podLen(n),vol:n.audio.volume})),"
              "status:st.hidden?null:st.textContent,cursor:document.getElementById('ov').style.cursor,"
              "vt:window.__ciach.video.style.transform,nt:window.__ciach.nk.style.transform}})()")


def is_red(p):
    return p and p[3] > 200 and p[0] > 150 and p[1] < 90 and p[2] < 90


def is_clear(p):
    return p and p[3] < 20


def finish():
    """Zamyka okno testu także po błędzie asercji, żeby nie zostawić osieroconego procesu."""
    close_app()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


NAK_Y = 22 + 15  # wiersz jedynej Nakładki: tuż pod paskiem etykiet

main_ok = False
try:
    wait("!!(window.__ciach && window.__ciach.S.loaded && window.__ciach.S.scanned)", 60, "loaded")
    s = state()
    print("1 loaded: N", s["N"], "tlH", s["tlH"])
    assert s["N"] == 120 and s["tlH"] == 110
    js("window.__ciach.video.muted=true; true")

    # drop MP3 na Gniazdo Nakładki: odrzucony; MP4 w x Klatki 30: Nakładka zaczyna się w tej Klatce
    L = js("window.__ciach.layout(true)")
    def drop(path, s_):
        return js("(()=>{const r=document.getElementById('tl').getBoundingClientRect();"
                  "return window.__ciach.dropFiles([%s], r.left+%r, r.top+%r)})()" % (json.dumps(path), x_of_s(s_), L["nakStripTop"] + 5))
    assert drop(os.path.join(SP, "_podklad.mp3"), 1.0) == "reject" and "MP4" in state()["status"]
    assert drop(tn.SRC, seq_ts(30)) == "nakladka"
    wait("window.__ciach.S.naks.length===1 && window.__ciach.S.naks[0].ready", 30, "nakladka")
    s = state()
    n = s["naks"][0]
    print("2 nakladka:", {k: n[k] for k in ("at", "segs", "pos", "key")}, "sel", s["sel"], "tlH", s["tlH"])
    assert abs(n["at"] - frame_ts(30)) < 1e-6 and s["sel"] == {"nak": n["gen"], "edge": None} and s["tlH"] == 140
    assert abs(n["pos"]["s"] - 1) < 1e-6 and abs(n["pos"]["x"] - 0.5) < 1e-6 and abs(n["pos"]["y"] - 0.5) < 1e-6
    assert all(abs(a - b) <= 10 for a, b in zip(n["key"], tn.KEY)), n["key"]

    # podgląd: w Klatce 20 Nakładki nie ma, w 45 środek czerwony, zielone tło przezroczyste
    R = vrect()
    seek_frame(20)
    assert state()["naks"][0]["want"] is None and is_clear(pixel(R, 0.5, 0.5))
    seek_frame(45)
    p_red, p_bg = pixel(R, 0.5, 0.5), pixel(R, 0.1, 0.5)
    print("3 podgląd: środek", p_red, "tło", p_bg)
    assert is_red(p_red) and is_clear(p_bg), (p_red, p_bg)
    shot("n1_nakladka.png")

    # G: zaznaczona Nakładka bez klucza (surowe zielone tło), kursor pipety; G + klik pobiera kolor
    keydown("KeyG")
    s = state()
    p_raw = pixel(R, 0.1, 0.5)
    print("4 G:", s["gKey"], "tło", p_raw, "kursor", s["cursor"][:20] if s["cursor"] else None)
    assert s["gKey"] and p_raw[3] == 255 and p_raw[1] > 120 and p_raw[0] < 60, p_raw
    pointer("ov", "pointermove", *px(R, 0.1, 0.5))
    assert "data:image/svg" in state()["cursor"]
    shot("n2_surowe_tlo.png")
    click("ov", *px(R, 0.1, 0.5))
    keyup("KeyG")
    s = state()
    print("   klucz:", s["naks"][0]["key"], s["status"])
    assert not s["gKey"] and "Kolor klucza" in s["status"] and all(abs(a - b) <= 10 for a, b in zip(s["naks"][0]["key"], tn.KEY))
    assert is_clear(pixel(R, 0.1, 0.5))

    # róg: skalowanie z przeciwległym rogiem w miejscu (Nakładka 16:9 wypełnia obraz)
    drag("ov", [px(R, 1, 1), px(R, 0.9, 0.9), px(R, 0.75, 0.75)])
    pos = state()["naks"][0]["pos"]
    print("5 skala:", pos)
    assert abs(pos["s"] - 0.75) < 0.01 and abs(pos["x"] - 0.375) < 0.01 and abs(pos["y"] - 0.375) < 0.01
    # pas przy rogu: obrót o ~88° przyciąga się do 90°
    import math
    cx, cy = px(R, 0.375, 0.375)
    sx, sy = px(R, 0.75, 0.75)
    p0 = (sx - 13, sy - 13)
    pointer("ov", "pointermove", *p0)
    assert "data:image/svg" in state()["cursor"]  # półkole
    vx, vy = p0[0] - cx, p0[1] - cy
    a = math.radians(88)
    p1 = (cx + vx * math.cos(a) - vy * math.sin(a), cy + vx * math.sin(a) + vy * math.cos(a))
    mid = (cx + vx * math.cos(a / 2) - vy * math.sin(a / 2), cy + vx * math.sin(a / 2) + vy * math.cos(a / 2))
    drag("ov", [p0, mid, p1])
    pos = state()["naks"][0]["pos"]
    print("6 obrót:", pos)
    assert pos["r"] == 90, pos
    # Ctrl wyłącza Przyciąganie obrotu
    drag("ov", [p1, (p1[0] + 1, p1[1] + 6)], ctrl=True)
    r_free = state()["naks"][0]["pos"]["r"]
    assert r_free != 90 and abs(r_free - 90) < 5, r_free
    drag("ov", [(p1[0] + 1, p1[1] + 6), p1])
    assert state()["naks"][0]["pos"]["r"] == 90
    # środek czerwonego prostokąta = środek Nakładki, w (0,375; 0,375)
    assert is_red(pixel(R, 0.375, 0.375)) and is_clear(pixel(R, 0.53, 0.375))  # zielone tło obok prostokąta
    shot("n3_obrot.png")
    # środek: przesuwanie (bez zmian, przesunięcie tam i z powrotem)
    drag("ov", [(cx, cy), (cx + 30, cy + 10)])
    pos = state()["naks"][0]["pos"]
    assert abs(pos["x"] - (0.375 + 30 / R["w"])) < 0.005 and abs(pos["y"] - (0.375 + 10 / R["h"])) < 0.005, pos
    drag("ov", [(cx + 30, cy + 10), (cx, cy)])

    # timeline: ←/→ przesuwa o Klatkę, ↑/↓ Głośność
    key("ArrowRight")
    key("ArrowDown")
    key("ArrowDown")
    s = state()
    n = s["naks"][0]
    print("7 strzałki: at", n["at"], "gain", n["gain"], "vol", n["vol"])
    assert abs(n["at"] - frame_ts(31)) < 1e-6 and abs(n["gain"] - 0.9) < 1e-6 and abs(n["vol"] - 0.9) < 1e-6
    # prawa Krawędź na timeline: przycięcie do Klatki 75 (z Ctrl, bez Przyciągania)
    drag("tl", [(x_of_s(n["start"] + n["len"]), NAK_Y), (x_of_s(seq_ts(75)), NAK_Y)], ctrl=True)
    n = state()["naks"][0]
    print("8 krawędź: len", n["len"], "segs", n["segs"])
    assert abs(n["start"] + n["len"] - seq_ts(75)) < 0.02, n

    # Wycięcie na Nakładce: C w Klatce 40 i 50, Delete → dwa odcinki, reszta dosunięta
    seek_frame(40)
    key("KeyC")
    seek_frame(50)
    key("KeyC")
    s = state()
    assert s["cut"]["pod"] == n["gen"] and s["cut"]["a"] == 40 and s["cut"]["b"] == 50, s["cut"]
    shot("n4_wyciecie.png")
    key("Delete")
    n = state()["naks"][0]
    print("9 wycięcie:", n["segs"], "len", n["len"])
    assert len(n["segs"]) == 2 and abs(n["len"] - (seq_ts(75) - seq_ts(31) - (seq_ts(50) - seq_ts(40)))) < 0.02

    # Delete usuwa Nakładkę, Ctrl+Z przywraca ją z Kadrem i kluczem
    before = state()["naks"][0]
    key("Delete")
    wait("document.getElementById('tl').clientHeight===110", 5, "timeline bez wiersza")  # przerysowanie w następnej klatce
    s = state()
    assert not s["naks"] and s["tlH"] == 110 and s["sel"] is None, (len(s["naks"]), s["tlH"], s["sel"], s["cut"], s["status"])
    key("KeyZ", ctrl=True)
    s = state()
    print("10 cofnięcie:", len(s["naks"]), s["status"])
    assert len(s["naks"]) == 1 and s["naks"][0]["pos"] == before["pos"] and s["naks"][0]["segs"] == before["segs"]

    # Zbliżenie w trakcie odtwarzania powiększa też Nakładki: ten sam transform na #nk
    seek_frame(35)
    js("(()=>{const c=window.__ciach;c.commitKadr({x:0.25,y:0.25,s:0.5});const z=c.S.zooms[0];z.end=c.frameTs(110);return true})()")
    js("window.__ciach.S.sel=null; true")
    key("Space")
    time.sleep(0.6)
    s = state()
    print("11 zbliżenie:", s["vt"], "|", s["nt"])
    assert s["vt"] and s["vt"] == s["nt"]
    key("Space")
    js("(()=>{const S=window.__ciach.S;S.zooms=[];S.sel=null;return true})()")

    # Ciach całości: czerwony środek Nakładki (240, 135) dokładnie tam, gdzie gra Nakładka (34 Klatki od 31)
    js("(()=>{const S=window.__ciach.S;S.left=0;S.right=S.N;return true})()")
    key("Enter")
    wait("(document.getElementById('status').textContent||'').startsWith('Gotowe')", 300, "export done")
    outs = [f for f in os.listdir(PROJ) if f.startswith(TEST_STEMS[0]) and f.endswith("_ciach.mp4")]
    assert outs, "brak wyniku"
    out = os.path.join(PROJ, outs[0])
    col = tn.strip(out, "1:360:240:0")
    reds = [i for i, f in enumerate(col) if tn.color(f[135]) == "R"]
    vol = ts.mean_volume(out, frame_ts(33), frame_ts(60))
    print("12 Ciach:", outs[0], "klatek", len(col), "czerwone", reds[:1], reds[-1:], len(reds), "dźwięk", vol)
    assert len(col) == 120 and reds == list(range(31, 65)), reds
    assert tn.color(col[45][10]) == "B"  # nad obróconą Nakładką: tło Sekwencji
    assert vol > -45
    shot("n5_koniec.png")

    main_ok = True
finally:
    finish()
if main_ok:
    tn.clean()
    print("ALL OK")
