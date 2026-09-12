"""Test UI Zbliżeń. Steruje oknem przez endpoint debugowy (CIACH_DEBUG=1), zrzuty przez
PrintWindow po PID własnego procesu, bez SendKeys i bez zabierania fokusu. Kadry rysuje
syntetycznymi PointerEvent na nakładce `#ov`, Zbliżenia na timeline na `#tl`.

Użycie:  venv/Scripts/python tests/drive_zoom.py [--exe]
Plik testowy `_zoom_src.mp4` (czerwony | niebieski) generuje test_zblizenie.py.
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
import test_zblizenie as tz  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SRC = tz.SRC
tz.gen_halves(SRC, 4.0, "red", "blue")
TEST_STEMS = tz.TEST_STEMS
USE_EXE = "--exe" in sys.argv
PORTFILE = os.path.join(SP, "_port_zoom.txt")
if os.path.exists(PORTFILE):
    os.remove(PORTFILE)
env = dict(os.environ, CIACH_DEBUG="1", CIACH_PORTFILE=PORTFILE, PYTHONIOENCODING="utf-8")
log = open(os.path.join(SP, "_app_zoom.log"), "w", encoding="utf-8")
tz.clean()
cmd = [os.path.join(PROJ, "Ciach.exe"), SRC] if USE_EXE else [sys.executable, os.path.join(PROJ, "ciach.py"), SRC]
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


def drag(el, x0, y0, x1, y1, ctrl=False):
    pointer(el, "pointerdown", x0, y0, ctrl)
    pointer(el, "pointermove", (x0 + x1) / 2, (y0 + y1) / 2, ctrl)
    pointer(el, "pointermove", x1, y1, ctrl)
    pointer(el, "pointerup", x1, y1, ctrl)
    time.sleep(0.2)


def click(el, x, y):
    pointer(el, "pointerdown", x, y)
    pointer(el, "pointerup", x, y)
    time.sleep(0.15)


def x_of(t):
    return js("(()=>{const S=window.__ciach.S;const W=document.getElementById('tl').clientWidth;"
              "return (%r - S.view.start)/(S.view.end-S.view.start)*W})()" % t)


def frame_ts(i):
    return js("window.__ciach.frameTs(%d)" % i)


def seek_frame(i):
    js("window.__ciach.video.currentTime = window.__ciach.frameTs(%d) + 0.001; true" % i)
    time.sleep(0.3)


def vrect():
    return js("JSON.stringify(window.__ciach.videoRect())") and json.loads(js("JSON.stringify(window.__ciach.videoRect())"))


def state():
    return js("(()=>{const S=window.__ciach.S;const v=window.__ciach.video;const st=document.getElementById('status');"
              "return {loaded:S.loaded,N:S.N,frames:!!S.frames,left:S.left,right:S.right,sel:S.sel,dur:S.duration,"
              "zooms:S.zooms.map(z=>({id:z.id,at:z.at,end:z.end,rin:z.rin,rout:z.rout,keys:z.keys})),zKey:S.zKey,"
              "t:v.currentTime,paused:v.paused,transform:v.style.transform,tlH:document.getElementById('tl').clientHeight,"
              "status:st.hidden?null:st.textContent,cursor:document.getElementById('ov').style.cursor}})()")


def px(R, fx, fy):
    return R["x"] + fx * R["w"], R["y"] + fy * R["h"]


ZOOM_Y_TOP = 22 + 68 + 5    # górna połowa wiersza Zbliżeń: rogi Ramp
ZOOM_Y_LOW = 22 + 68 + 24   # dolna połowa: Krawędzie i środek


def finish():
    """Zamyka okno testu także po błędzie asercji, żeby nie zostawić osieroconego procesu."""
    close_app()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


main_ok = False
try:
    wait("!!(window.__ciach && window.__ciach.S.loaded && window.__ciach.S.frames)", 60, "loaded")
    s = state()
    print("1 loaded: N", s["N"], "tlH", s["tlH"])
    assert s["N"] == 120 and s["tlH"] == 110
    js("window.__ciach.video.muted=true; true")

    # Kadr na klatce 30: Z + przeciągnięcie na podglądzie (prawa górna ćwiartka, gest 45 % szerokości i wysokości)
    # → Zbliżenie o długości jednej Klatki, od razu zaznaczone
    seek_frame(30)
    R = vrect()
    keydown("KeyZ")
    assert state()["zKey"] is True
    drag("ov", *px(R, 0.5, 0.1), *px(R, 0.95, 0.55))
    keyup("KeyZ")
    s = state()
    print("2 drawn:", s["zooms"], "tlH", s["tlH"], "status", s["status"])
    assert len(s["zooms"]) == 1 and s["tlH"] == 140
    z = s["zooms"][0]
    k0 = z["keys"][0]
    assert abs(z["at"] - frame_ts(30)) < 1e-6 and abs(z["end"] - frame_ts(31)) < 1e-6 and len(z["keys"]) == 1
    assert abs(k0["k"]["x"] - 0.5) < 0.02 and abs(k0["k"]["y"] - 0.1) < 0.02 and abs(k0["k"]["s"] - 0.45) < 0.02
    assert s["sel"] == {"zoom": z["id"], "part": None} and "Zbliżenie" in (s["status"] or "")
    R = vrect()  # wiersz Zbliżeń zmniejszył podgląd

    # Z + klik bez przeciągania: nic
    keydown("KeyZ")
    click("ov", *px(R, 0.2, 0.8))
    keyup("KeyZ")
    assert len(state()["zooms"]) == 1 and len(state()["zooms"][0]["keys"]) == 1

    # klatka 60: poza przedziałem widać Cień (zaznaczone Zbliżenie); złapanie go wydłuża przedział i zapisuje pozycję
    seek_frame(60)
    vis = js("JSON.stringify(window.__ciach.visibleKadry())")
    vis = json.loads(vis)
    print("3 ghost:", vis)
    assert len(vis) == 1 and vis[0]["tag"] == "Cień" and vis[0]["target"]["extend"] == "out"
    k = vis[0]["k"]
    cx, cy = px(R, k["x"] + k["s"] / 2, k["y"] + k["s"] / 2)
    drag("ov", cx, cy, cx - 0.2 * R["w"], cy + 0.1 * R["h"])
    z = state()["zooms"][0]
    print("   extended:", z["at"], z["end"], [(round(q["t"], 3), round(q["k"]["x"], 2), round(q["k"]["y"], 2)) for q in z["keys"]])
    assert abs(z["end"] - frame_ts(61)) < 1e-6 and len(z["keys"]) == 2
    assert abs(z["keys"][1]["t"] - frame_ts(60)) < 1e-6 and abs(z["keys"][1]["k"]["x"] - 0.3) < 0.02 and abs(z["keys"][1]["k"]["y"] - 0.2) < 0.02
    shot("z1_kadr.png")

    # klatka 45: Kadr przejeżdża (przerywany); złapanie rogu zapisuje pozycję w tej Klatce (od teraz stoi)
    seek_frame(45)
    vis = json.loads(js("JSON.stringify(window.__ciach.visibleKadry())"))
    assert vis[0]["dashed"] is True and abs(vis[0]["k"]["x"] - 0.4) < 0.02, vis
    k = vis[0]["k"]
    sx, sy = px(R, k["x"] + k["s"], k["y"] + k["s"])
    drag("ov", sx, sy, sx - 0.15 * R["w"], sy - 0.15 * R["h"])
    z = state()["zooms"][0]
    vis = json.loads(js("JSON.stringify(window.__ciach.visibleKadry())"))
    print("4 key at 45:", [(round(q["t"], 3), round(q["k"]["s"], 2)) for q in z["keys"]], "dashed", vis[0]["dashed"])
    assert len(z["keys"]) == 3 and abs(z["keys"][1]["k"]["s"] - (k["s"] - 0.15)) < 0.02 and vis[0]["dashed"] is False
    shot("z2_pozycje.png")
    pointer("ov", "pointermove", *px(R, z["keys"][1]["k"]["x"] + 0.1, z["keys"][1]["k"]["y"] + 0.1))
    assert state()["cursor"] == "move"

    # Z + przeciągnięcie na klatce 50 wewnątrz Zbliżenia: rozcięcie, nowe Zbliżenie [50, 61) z nowym Kadrem
    seek_frame(50)
    keydown("KeyZ")
    drag("ov", *px(R, 0.55, 0.5), *px(R, 0.95, 0.9))
    keyup("KeyZ")
    s = state()
    print("5 split:", [(round(q["at"], 3), round(q["end"], 3), len(q["keys"])) for q in s["zooms"]], "sel", s["sel"])
    assert len(s["zooms"]) == 2
    z1, z2 = s["zooms"]
    assert abs(z1["end"] - frame_ts(50)) < 1e-6 and abs(z2["at"] - frame_ts(50)) < 1e-6 and abs(z2["end"] - frame_ts(61)) < 1e-6
    assert s["sel"] == {"zoom": z2["id"], "part": None} and len(z2["keys"]) == 1
    # stare Zbliżenie: pozycja z klatki 60 przepadła, na ostatniej klatce (49) została ta, którą tam pokazywało
    assert all(q["t"] < frame_ts(50) for q in z1["keys"]) and len(z1["keys"]) == 3
    # Delete usuwa nowe (zaznaczone); zostaje stare [30, 50)
    key("Delete")
    time.sleep(0.2)
    s = state()
    assert len(s["zooms"]) == 1 and abs(s["zooms"][0]["end"] - frame_ts(50)) < 1e-6 and s["sel"] is None

    # timeline: klik w środek zaznacza; przesunięcie z Ctrl (bez Przyciągania) o ok. 1 s w prawo, liczba Klatek bez zmian
    z = s["zooms"][0]
    n = 20
    drag("tl", x_of(frame_ts(40)), ZOOM_Y_LOW, x_of(frame_ts(70)), ZOOM_Y_LOW, ctrl=True)
    z = state()["zooms"][0]
    print("6 moved:", z["at"], z["end"], [round(q["t"], 3) for q in z["keys"]])
    assert abs(z["at"] - frame_ts(60)) < 1e-6 and abs(z["end"] - frame_ts(60 + n)) < 1e-6
    assert abs(z["keys"][1]["t"] - frame_ts(75)) < 1e-6, "pozycje jadą razem ze Zbliżeniem"

    # Przyciąganie lewej Krawędzi do lewego Suwaka (klatka 45) z odległości ~5 px; pozycje zostają na swoich Klatkach
    js("window.__ciach.S.left = 45; true")
    drag("tl", x_of(z["at"]), ZOOM_Y_LOW, x_of(frame_ts(45)) + 5, ZOOM_Y_LOW)
    s = state()
    z = s["zooms"][0]
    print("7 edge in snapped:", z["at"], z["end"], "sel", s["sel"], [round(q["t"], 3) for q in z["keys"]])
    assert abs(z["at"] - frame_ts(45)) < 1e-6 and abs(z["end"] - frame_ts(80)) < 1e-6 and s["sel"]["part"] == "in"
    assert abs(z["keys"][0]["t"] - frame_ts(60)) < 1e-6 and len(z["keys"]) == 3, "pozycje zostają na swoich Klatkach, przed pierwszą Kadr stoi"

    # skrócenie prawą Krawędzią poniżej ostatniej pozycji (klatka 75): pozycja przepada, na końcu zostaje to, co Kadr pokazywał
    drag("tl", x_of(z["end"]), ZOOM_Y_LOW, x_of(frame_ts(70)), ZOOM_Y_LOW, ctrl=True)
    z = state()["zooms"][0]
    print("8 edge out:", z["end"], [round(q["t"], 3) for q in z["keys"]])
    assert abs(z["end"] - frame_ts(70)) < 1e-6 and abs(z["keys"][-1]["t"] - frame_ts(69)) < 1e-6 and len(z["keys"]) == 2

    # Rampa wejścia: górny lewy róg przeciągnięty w prawo o ok. 0,5 s
    drag("tl", x_of(z["at"]), ZOOM_Y_TOP, x_of(z["at"] + 0.5), ZOOM_Y_TOP, ctrl=True)
    s = state()
    z = s["zooms"][0]
    print("9 ramp in:", z["rin"], "sel", s["sel"])
    assert abs(z["rin"] - 0.5) < 0.04 and s["sel"]["part"] == "rin"
    key("ArrowRight", ctrl=True)
    time.sleep(0.2)
    z2 = state()["zooms"][0]
    assert abs(z2["rin"] - z["rin"] - 1 / 30) < 1e-3, (z2["rin"], z["rin"])
    # zwykłe strzałki przy zaznaczonym Zbliżeniu chodzą po Klatkach, Zbliżenie stoi
    seek_frame(50)
    key("ArrowRight")
    time.sleep(0.2)
    s = state()
    assert abs(s["t"] - frame_ts(51)) < 0.02 and abs(s["zooms"][0]["rin"] - z2["rin"]) < 1e-6 and s["sel"]["part"] == "rin", s["t"]
    shot("z3_rampa.png")
    key("Delete")
    time.sleep(0.2)
    s = state()
    assert len(s["zooms"]) == 1 and s["zooms"][0]["rin"] == 0

    # środek: klik zaznacza całość, ←/→ przesuwa o Klatkę, End dosuwa do końca Sekwencji
    click("tl", x_of(z["at"] + 0.4), ZOOM_Y_LOW)
    assert state()["sel"]["part"] is None
    key("ArrowLeft", ctrl=True)
    time.sleep(0.2)
    z = state()["zooms"][0]
    assert abs(z["at"] - frame_ts(44)) < 1e-6
    key("End")
    time.sleep(0.2)
    s = state()
    print("10 end:", s["t"], "zoom", s["zooms"][0]["at"])
    assert abs(s["t"] - frame_ts(119)) < 0.02 and abs(s["zooms"][0]["at"] - frame_ts(44)) < 1e-6, "End przenosi playhead, nie Zbliżenie"
    # Ctrl+Shift+→ przesuwa Zbliżenie o 1 s; dosunięcie do końca Sekwencji przez powtórzenia
    for _ in range(4):
        key("ArrowRight", ctrl=True, shift=True)
    time.sleep(0.2)
    z = state()["zooms"][0]
    assert abs(z["end"] - state()["dur"]) < 1e-6 and abs(z["at"] - frame_ts(120 - 25)) < 1e-6, z

    # odtwarzanie w Zbliżeniu: wideo dostaje transform; pauza go zdejmuje
    seek_frame(100)
    key("Space")
    time.sleep(0.6)
    s = state()
    print("11 playing:", s["t"], "paused", s["paused"], "transform", s["transform"][:40])
    if not s["paused"]:
        assert s["transform"].startswith("translate("), "w trakcie odtwarzania Zbliżenie ma być widoczne w podglądzie"
    key("Space")
    time.sleep(0.3)
    assert state()["transform"] == ""

    # Esc zdejmuje zaznaczenie: poza przedziałem nie ma Cienia
    key("Escape")
    seek_frame(80)
    assert state()["sel"] is None and json.loads(js("JSON.stringify(window.__ciach.visibleKadry())")) == []

    # Ciach: nowe Zbliżenie w niebieskiej połowie od klatki 60, prawą Krawędzią do końca; Fragment [60, 120) → 60 niebieskich klatek
    click("tl", x_of(frame_ts(100)), ZOOM_Y_LOW)
    key("Delete")
    time.sleep(0.2)
    assert not state()["zooms"] and state()["tlH"] == 110
    seek_frame(60)
    R = vrect()
    keydown("KeyZ")
    drag("ov", *px(R, 0.55, 0.1), *px(R, 0.95, 0.5))
    keyup("KeyZ")
    z = state()["zooms"][0]
    assert z["keys"][0]["k"]["x"] > 0.5
    drag("tl", x_of(z["end"]), ZOOM_Y_LOW, x_of(state()["dur"]) - 3, ZOOM_Y_LOW)
    z = state()["zooms"][0]
    assert abs(z["end"] - state()["dur"]) < 1e-6, z
    js("(()=>{const S=window.__ciach.S;S.left=60;S.right=120;S.sel=null;return true})()")
    key("Enter")
    wait("(document.getElementById('status').textContent||'').startsWith('Gotowe')", 300, "export done")
    outs = [f for f in os.listdir(PROJ) if f.startswith(TEST_STEMS[0]) and f.endswith("_ciach.mp4")]
    assert outs, "brak wyniku"
    vals = tz.uavg(os.path.join(PROJ, outs[0]))
    blue = tz.blue_frames(vals)
    print("12 export:", outs[0], "frames", len(vals), "blue", len(blue))
    assert len(vals) == 60 and blue == list(range(60)), blue

    # Delete na środku: usuwa Zbliżenie, wiersz znika
    click("tl", x_of(frame_ts(90)), ZOOM_Y_LOW)
    key("Delete")
    time.sleep(0.2)
    s = state()
    print("13 deleted:", s["zooms"], "tlH", s["tlH"])
    assert not s["zooms"] and s["tlH"] == 110
    shot("z4_koniec.png")

    main_ok = True
finally:
    finish()
if main_ok:
    tz.clean()
    print("ALL OK")
