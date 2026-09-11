"""Test UI Sekwencji i Podkładów. Steruje oknem przez endpoint debugowy (CIACH_DEBUG=1),
zrzuty przez PrintWindow, bez SendKeys i bez zabierania fokusu. Dropy idą przez
`window.__ciach.dropFiles`, czyli tę samą drogę co prawdziwe upuszczenie pliku.

Użycie:  venv/Scripts/python tests/drive_seq.py [--exe]
Pliki testowe generuje test_sekwencja.py (uruchamiany tu przy braku plików).
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
import test_sekwencja as ts  # noqa: E402

A, B, C, D, P = ts.A, ts.B, ts.C, ts.D, ts.P
ts.gen(A, 4.0)
ts.gen(B, 2.5)
ts.gen(C, 2.0, fps=60)
ts.gen(D, 2.0, size="640x360")
ts.gen_mp3(P, 6.0, 1000)
TEST_STEMS = ts.TEST_STEMS
USE_EXE = "--exe" in sys.argv
PORTFILE = os.path.join(SP, "_port.txt")
if os.path.exists(PORTFILE):
    os.remove(PORTFILE)
env = dict(os.environ, CIACH_DEBUG="1", CIACH_PORTFILE=PORTFILE, PYTHONIOENCODING="utf-8")
log = open(os.path.join(SP, "_app_seq.log"), "w", encoding="utf-8")
ts.clean()
cmd = [os.path.join(PROJ, "Ciach.exe"), A] if USE_EXE else [sys.executable, os.path.join(PROJ, "ciach.py"), A]
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


def win_title():
    """Tytuł okna procesu testu (set_title z Pythona nie zmienia document.title)."""
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "$ids=@(%d)+@(Get-CimInstance Win32_Process -Filter 'ParentProcessId = %d' | %%{ $_.ProcessId });"
                        "(Get-Process | ? { $ids -contains $_.Id -and $_.MainWindowHandle -ne 0 } | select -First 1).MainWindowTitle"
                        % (proc.pid, proc.pid)], capture_output=True, text=True, encoding="utf-8")
    return (r.stdout or "").strip()


def key(code, shift=False, ctrl=False):
    js("window.dispatchEvent(new KeyboardEvent('keydown',{code:'%s',shiftKey:%s,ctrlKey:%s,bubbles:true,cancelable:true}));"
       "window.dispatchEvent(new KeyboardEvent('keyup',{code:'%s',bubbles:true})); true"
       % (code, str(shift).lower(), str(ctrl).lower(), code))


def pointer(kind, x, y, ctrl=False):
    js("(()=>{const c=document.getElementById('tl');const r=c.getBoundingClientRect();"
       "c.dispatchEvent(new PointerEvent('%s',{clientX:r.left+%s,clientY:r.top+%s,button:0,buttons:1,pointerId:1,ctrlKey:%s,bubbles:true}));return true})()"
       % (kind, x, y, str(ctrl).lower()))


def drag(x0, y0, x1, y1, ctrl=False):
    pointer("pointerdown", x0, y0, ctrl)
    pointer("pointermove", (x0 + x1) / 2, y1, ctrl)
    pointer("pointermove", x1, y1, ctrl)
    pointer("pointerup", x1, y1, ctrl)
    time.sleep(0.2)


def x_of(t):
    return js("(()=>{const S=window.__ciach.S;const W=document.getElementById('tl').clientWidth;"
              "return (%r - S.view.start)/(S.view.end-S.view.start)*W})()" % t)


def state():
    return js("(()=>{const S=window.__ciach.S;const v=window.__ciach.video;const st=document.getElementById('status');"
              "return {loaded:S.loaded,kind:S.kind,N:S.N,frames:!!S.frames,left:S.left,right:S.right,sel:S.sel,dur:S.duration,"
              "parts:S.parts.map(p=>[p.name,p.start]),pods:S.pods.map(p=>({gen:p.gen,at:p.at,tin:p.tin,tout:p.tout,gain:p.gain,wave:!!p.wave,"
              "vol:p.audio?p.audio.volume:null,paused:p.audio?p.audio.paused:null})),gain:S.gain,vvol:v.volume,busy:S.busy,t:v.currentTime,"
              "paused:v.paused,view:S.view,ext:window.__ciach.extent(),tlH:document.getElementById('tl').clientHeight,"
              "status:st.hidden?null:st.textContent,title:document.title}})()")


def drop(paths, where, index=None):
    """where: 'preview' | 'gniazdo' (index) | 'strip' | 'nowhere'"""
    code = """(()=>{const c=document.getElementById('tl');const r=c.getBoundingClientRect();
      const pv=document.getElementById('preview').getBoundingClientRect();const L=window.__ciach.layout(true);
      const S=window.__ciach.S;const W=c.clientWidth;const xOf=t=>(t-S.view.start)/(S.view.end-S.view.start)*W;
      let x,y; const where=%s, idx=%s;
      if(where==='preview'){x=pv.left+pv.width/2;y=pv.top+pv.height/2;}
      else if(where==='gniazdo'){const n=S.parts.length;const t=idx<n?S.parts[idx].start:S.duration;
        const cx=idx===0?xOf(t)+8:idx===n?xOf(t)-8:xOf(t);x=r.left+cx;y=r.top+L.vidTop+L.vidH/2;}
      else if(where==='strip'){x=r.left+W/2;y=r.top+L.stripTop+L.stripTop*0+5;}
      else {x=r.left+W/2;y=r.top+L.rulerTop+5;}
      return window.__ciach.dropFiles(%s,x,y);})()""" % (json.dumps(where), json.dumps(index), json.dumps(paths))
    return js(code)


def probe(path):
    pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,nb_frames", "-of", "compact", path],
                        capture_output=True, text=True)
    return pr.stdout.strip().replace("\n", " | ")


wait("!!(window.__ciach && window.__ciach.S.loaded && window.__ciach.S.frames)", 60, "loaded")
s = state()
print("1 loaded:", s["parts"], "N", s["N"], "tlH", s["tlH"])
assert s["N"] == 120 and s["tlH"] == 110

# Gniazda podczas przeciągania: syntetyczny dragover bez typów → oba rodzaje Gniazd
js("(()=>{const c=document.getElementById('tl');const r=c.getBoundingClientRect();const dt=new DataTransfer();"
   "window.dispatchEvent(new DragEvent('dragenter',{clientX:r.left+20,clientY:r.top+40,dataTransfer:dt,bubbles:true,cancelable:true}));"
   "window.dispatchEvent(new DragEvent('dragover',{clientX:r.left+20,clientY:r.top+40,dataTransfer:dt,bubbles:true,cancelable:true}));return true})()")
time.sleep(0.3)
s = state()
print("2 dragover: tlH", s["tlH"], "dragover", js("JSON.stringify(window.__ciach.S.dragOver)"))
assert s["tlH"] == 134, "pasek Gniazda Podkładu powinien dodać 24 px"
shot("s1_gniazda.png")
js("window.dispatchEvent(new DragEvent('drop',{clientX:100,clientY:100,dataTransfer:new DataTransfer(),bubbles:true,cancelable:true})); true")
time.sleep(0.2)
assert state()["tlH"] == 110

# niezgodne nagranie (640x360) na Gniazdo → komunikat, Sekwencja bez zmian
r = drop([D], "gniazdo", 1)
print("3 drop D:", r)
wait("(document.getElementById('status').textContent||'').includes('inne parametry')", 20, "reject D")
print("   status:", state()["status"])
assert len(state()["parts"]) == 1

# sklejenie: B za A; Suwaki obejmują całość, tytuł +1
r = drop([B], "gniazdo", 1)
print("4 drop B:", r)
wait("window.__ciach.S.parts.length===2 && !!window.__ciach.S.frames && !window.__ciach.S.busy", 60, "joined")
time.sleep(0.5)
s = state()
title = win_title()
print("   joined:", s["parts"], "N", s["N"], "right", s["right"], "title", title, "dur", s["dur"])
assert s["N"] == 195 and s["right"] == 195 and s["left"] == 0 and title.endswith("+1")
assert abs(s["parts"][1][1] - 4.0) < 0.01
shot("s2_sekwencja.png")

# Podkład na pasek
r = drop([P], "strip")
print("5 drop P:", r)
wait("window.__ciach.S.pods.length===1 && window.__ciach.S.pods[0].wave", 30, "podklad")
time.sleep(0.3)
s = state()
p = s["pods"][0]
print("   pod:", p, "tlH", s["tlH"], "ext", s["ext"], "sel", s["sel"])
assert s["tlH"] == 154 and p["at"] == 0 and p["tin"] == 0 and abs(p["tout"] - 6.0) < 0.05
assert s["sel"] == {"pod": p["gen"], "edge": None}
assert abs(s["ext"] - 6.5) < 0.1  # wystaje nieznacznie? nie: 6.0 < 6.52 → ext = Sekwencja
shot("s3_podklad.png")

# przesunięcie Podkładu z Ctrl (bez Przyciągania) o ok. 1 s w prawo
ROW_Y = 22 + 68 + 22
x0 = x_of(1.0)
x1 = x_of(2.0)
drag(x0, ROW_Y, x1, ROW_Y, ctrl=True)
s = state()
p = s["pods"][0]
print("6 moved:", p["at"], "ext", s["ext"])
assert 0.9 < p["at"] < 1.1 and abs(s["ext"] - (p["at"] + 6.0)) < 0.01, "timeline rozciąga się do końca Podkładu"

# Przyciąganie: dosunięcie lewej Krawędzi do Styku (4,0 s) z odległości ~5 px
x0 = x_of(p["at"] + 0.5)
x1 = x_of(4.0 + 0.5) + 5
drag(x0, ROW_Y, x1, ROW_Y)
p = state()["pods"][0]
print("7 snapped:", p["at"])
assert abs(p["at"] - 4.0) < 1e-6, "lewa Krawędź powinna przyciągnąć się do Styku"
# dwuklik: cały zakres z wystawaniem
js("document.getElementById('tl').dispatchEvent(new MouseEvent('dblclick',{bubbles:true})); true")

# strzałki na zaznaczonym Podkładzie: 1 klatka, Shift = 1 s
def frame_ts(i):
    return js("window.__ciach.frameTs(%d)" % i)


def frame_index(t):
    return js("window.__ciach.frameIndex(%r)" % t)


i0 = frame_index(4.0)
key("ArrowRight")
time.sleep(0.2)
p = state()["pods"][0]
assert abs(p["at"] - frame_ts(i0 + 1)) < 1e-6, (p, frame_ts(i0 + 1))
key("ArrowLeft", shift=True)
time.sleep(0.2)
p = state()["pods"][0]
print("8 arrows:", p["at"])
assert abs(p["at"] - frame_ts(i0 + 1 - 30)) < 1e-6, p

# Głośność Podkładu: ↓ = -5 %, Shift+↓ = -1 %
key("ArrowDown")
key("ArrowDown", shift=True)
time.sleep(0.2)
p = state()["pods"][0]
print("9 gain pod:", p["gain"], "vol", p["vol"])
assert abs(p["gain"] - 0.94) < 1e-6 and abs(p["vol"] - 0.94) < 1e-6
shot("s4_glosnosc.png")

# lewa Krawędź: klik przy krawędzi i przeciągnięcie w prawo o ~1 s (treść zostaje: tin rośnie)
at0 = p["at"]
drag(x_of(at0), ROW_Y, x_of(at0 + 1.0), ROW_Y, ctrl=True)
s = state()
p = s["pods"][0]
print("10 edge in:", p, "sel", s["sel"])
assert s["sel"]["edge"] == "in" and 0.9 < p["tin"] < 1.1 and abs(p["at"] - (at0 + p["tin"])) < 1e-3 and abs(p["tout"] - 6.0) < 0.05
# strzałka na Krawędzi: przycina o klatkę
key("ArrowRight")
time.sleep(0.2)
p2 = state()["pods"][0]
assert abs(p2["tin"] - p["tin"] - 1 / 30) < 1e-3 and abs(p2["at"] - p["at"] - 1 / 30) < 1e-3
# prawa Krawędź: dosunięcie do końca Sekwencji (Przyciąganie do S.duration)
end = state()["pods"][0]
xr = x_of(end["at"] + end["tout"] - end["tin"])
drag(xr, ROW_Y, x_of(s["dur"]) - 4, ROW_Y)
p3 = state()["pods"][0]
print("11 edge out:", p3)
assert abs(p3["at"] + p3["tout"] - p3["tin"] - s["dur"]) < 1e-3, "prawa Krawędź powinna przyciągnąć się do końca Sekwencji"
shot("s5_krawedzie.png")

# Esc → fokus na wideo; ↓ zmienia Głośność Sekwencji
key("Escape")
key("ArrowDown")
time.sleep(0.2)
s = state()
print("12 gain seq:", s["gain"], "video.volume", s["vvol"], "sel", s["sel"])
assert s["sel"] is None and abs(s["gain"] - 0.95) < 1e-6 and abs(s["vvol"] - 0.95) < 1e-6

# odtwarzanie: Podkład gra tylko w swoim zakresie
js("window.__ciach.video.muted=true; true")
js("window.__ciach.video.currentTime = %r; true" % (p3["at"] + 0.3))
time.sleep(0.2)
key("Space")
time.sleep(1.0)
s = state()
print("13 playing:", s["t"], "pod paused", s["pods"][0]["paused"], "video paused", s["paused"])
if not s["paused"]:
    assert s["pods"][0]["paused"] is False, "Podkład powinien grać razem z wideo"
key("Space")
time.sleep(0.3)
assert state()["pods"][0]["paused"] is True

# Ciach z miksem: jedna ścieżka AAC, liczba klatek = Fragment
js("(()=>{const S=window.__ciach.S;S.left=30;S.right=150;return true})()")
key("Enter")
wait("(document.getElementById('status').textContent||'').startsWith('Gotowe')", 300, "export done")
st = state()["status"]
print("14 export:", st)
outs = [f for f in os.listdir(PROJ) if f.startswith(TEST_STEMS[0]) and f.endswith("_ciach.mp4")]
assert outs
pr = probe(os.path.join(PROJ, outs[0]))
print("   probe:", pr)
assert "nb_frames=120" in pr and pr.count("codec_type=audio") == 1 and "codec_name=aac" in pr

# Delete na zaznaczonym Podkładzie
pointer("pointerdown", x_of(p3["at"] + 0.5), ROW_Y)
pointer("pointerup", x_of(p3["at"] + 0.5), ROW_Y)
time.sleep(0.1)
assert state()["sel"]["edge"] is None
key("Delete")
time.sleep(0.3)
s = state()
print("15 pod deleted:", s["pods"], "tlH", s["tlH"], "ext", s["ext"])
assert not s["pods"] and s["tlH"] == 110 and abs(s["ext"] - s["dur"]) < 1e-6

# Delete przy fokusie na wideo: usuwa Nagranie pod playheadem (B, od 4,0 s)
js("window.__ciach.video.currentTime = 5.0; true")
time.sleep(0.2)
key("Delete")
wait("window.__ciach.S.parts.length===1 && !!window.__ciach.S.frames && !window.__ciach.S.busy", 60, "removed")
time.sleep(0.3)
s = state()
title = win_title()
print("16 part removed:", s["parts"], "N", s["N"], "title", title, "t", s["t"])
assert s["parts"][0][0] == "_seq_a.mp4" and s["N"] == 120 and "+1" not in title
assert s["t"] < 4.05, "playhead po usunięciu Nagrania za nim zostaje na jego dawnym początku"

# wstawienie na początek: B przed A → Podkład jedzie z obrazem
drop([P], "strip")
wait("window.__ciach.S.pods.length===1", 30, "podklad 2")
drop([B], "gniazdo", 0)
wait("window.__ciach.S.parts.length===2 && !!window.__ciach.S.frames && !window.__ciach.S.busy", 60, "joined front")
time.sleep(0.3)
s = state()
print("17 prepend:", s["parts"], "pod at", s["pods"][0]["at"], "right", s["right"])
assert s["parts"][0][0] == "_seq_b.mp4" and abs(s["pods"][0]["at"] - 2.5) < 0.01 and s["right"] == s["N"]
shot("s6_prepend.png")

# drop mp3 na Gniazdo → komunikat; mp4 na pasek → komunikat; drop obok → nic
print("18 wrong drops:", drop([P], "gniazdo", 2), drop([A], "strip"), drop([A], "nowhere"))
time.sleep(0.3)
assert len(state()["parts"]) == 2 and len(state()["pods"]) == 1

# drop na podgląd: podmiana sesji, Podkłady znikają
r = drop([A], "preview")
wait("window.__ciach.S.parts.length===1 && window.__ciach.S.pods.length===0 && !!window.__ciach.S.frames", 60, "replaced")
s = state()
print("19 replaced:", r, s["parts"], "gain", s["gain"], "tlH", s["tlH"])
assert s["gain"] == 1 and s["tlH"] == 110

close_app()
try:
    proc.wait(timeout=15)
    print("20 closed, rc", proc.returncode)
except subprocess.TimeoutExpired:
    proc.kill()
    print("20 KILL needed")
ts.clean()
print("ALL OK")
