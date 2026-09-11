"""Automatyczny test UI Ciach. Steruje oknem przez endpoint debugowy (CIACH_DEBUG=1),
zrzuty robi przez PrintWindow. Nie używa SendKeys ani nie zabiera fokusu.

Użycie:  venv/Scripts/python tests/drive_ui.py [--exe]
Wymaga:  CIACH_TEST_MP4 = ścieżka do mp4 (domyślnie generowany syntetyczny plik 55 s / 30 fps).
"""
import os, sys, time, json, subprocess, urllib.request
SP = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(SP)
FF = "ffmpeg"
MP4 = os.environ.get("CIACH_TEST_MP4") or os.path.join(SP, "_test.mp4")
MP3 = os.path.join(SP, "_test.mp3")
if not os.path.exists(MP4):
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=54.733333",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=54.733333", "-c:v", "libx264", "-preset", "veryfast",
                    "-g", "60", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", MP4], check=True)
if not os.path.exists(MP3):
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=20", "-c:a", "libmp3lame",
                    "-b:a", "192k", "-metadata", "title=Test Ciach", MP3], check=True)
USE_EXE = "--exe" in sys.argv
PORTFILE = os.path.join(SP, "_port.txt")
if os.path.exists(PORTFILE):
    os.remove(PORTFILE)
env = dict(os.environ, CIACH_DEBUG="1", CIACH_PORTFILE=PORTFILE, PYTHONIOENCODING="utf-8")
log = open(os.path.join(SP, "_app.log"), "w", encoding="utf-8")
# Sprzątaj WYŁĄCZNIE wyniki własnych plików testowych. Użytkownik pracuje w tym samym
# folderze i jego eksporty (`<jego nagranie>_ciach*.mp4`) nie mogą zniknąć.
TEST_STEMS = tuple(os.path.splitext(os.path.basename(x))[0] + "_ciach" for x in (MP4, MP3))


def clean_test_outputs():
    for f in os.listdir(PROJ):
        if f.startswith(TEST_STEMS):
            os.remove(os.path.join(PROJ, f))


clean_test_outputs()
cmd = [os.path.join(PROJ, "Ciach.exe"), MP4] if USE_EXE else [sys.executable, os.path.join(PROJ, "ciach.py"), MP4]
t_start = time.time()
proc = subprocess.Popen(cmd, cwd=PROJ, env=env, stdout=subprocess.DEVNULL, stderr=log)
while not os.path.exists(PORTFILE):
    if proc.poll() is not None:
        raise SystemExit("app exited early rc=%s" % proc.returncode)
    time.sleep(0.1)
port = int(open(PORTFILE).read().strip())
print("port", port, "server up after %.1fs" % (time.time() - t_start))


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


def key(code, shift=False):
    sh = "true" if shift else "false"
    js("window.dispatchEvent(new KeyboardEvent('keydown',{code:'%s',shiftKey:%s,bubbles:true,cancelable:true}));"
       "window.dispatchEvent(new KeyboardEvent('keyup',{code:'%s',bubbles:true})); true" % (code, sh, code))


def pointer(kind, x, y=60):
    js("(()=>{const c=document.getElementById('tl');const r=c.getBoundingClientRect();"
       "c.dispatchEvent(new PointerEvent('%s',{clientX:r.left+%s,clientY:r.top+%s,button:0,buttons:1,pointerId:1,bubbles:true}));return true})()" % (kind, x, y))


def handle_x(kind, W):
    return js("(()=>{const S=window.__ciach.S;const i=S.%s;return (window.__ciach.frameTs(i)/S.duration)*%d})()" % (kind, W))


def state():
    return js("(()=>{const S=window.__ciach.S;const v=window.__ciach.video;const st=document.getElementById('status');"
              "return {loaded:S.loaded,kind:S.kind,N:S.N,frames:!!S.frames,wave:S.wave?S.wave.length:0,left:S.left,right:S.right,"
              "sel:S.sel,dur:S.duration,view:S.view,t:v.currentTime,paused:v.paused,playing:S.playing,vdur:v.duration,"
              "status:st.hidden?null:st.textContent,title:document.title,cls:document.body.className}})()")


def status_text():
    return js("(document.getElementById('status').hidden?'':document.getElementById('status').textContent)")


wait("!!(window.__ciach && window.__ciach.S.loaded)", 60, "loaded")
print("window+file loaded after %.1fs" % (time.time() - t_start))
wait("!!window.__ciach.S.frames && !!window.__ciach.S.wave", 60, "frames+wave")
wait("window.__ciach.video.readyState>=2", 30, "video ready")
s = state()
print("1 loaded:", s)
assert s["N"] > 1600 and s["right"] == s["N"] and s["left"] == 0 and s["wave"] > 20000
shot("t1_loaded.png")

# play / pause
key("Space")
time.sleep(1.5)
s = state()
print("2 after space:", {k: s[k] for k in ("t", "paused", "playing")})
if s["paused"]:
    print("   autoplay blocked for synthetic key -> muting for test")
    js("window.__ciach.video.muted=true; true")
    key("Space")
    time.sleep(1.5)
    s = state()
    print("   retry:", {k: s[k] for k in ("t", "paused", "playing")})
assert not s["paused"] and s["t"] > 0.5
key("Space")
time.sleep(0.3)
s = state()
assert s["paused"], "pause failed"
print("3 paused at", s["t"])

# drag right handle from far right to ~60%
W = js("document.getElementById('tl').clientWidth")
pointer("pointerdown", W - 3)
pointer("pointermove", int(W * 0.6))
pointer("pointerup", int(W * 0.6))
time.sleep(0.5)
s = state()
print("4 after drag right:", {k: s[k] for k in ("left", "right", "sel", "t", "paused")})
assert s["sel"] == "right" and 900 < s["right"] < 1100
assert abs(s["t"] - js("window.__ciach.frameTs(%d)" % s["right"])) < 0.01
shot("t2_right_handle.png")

# arrows on selected handle
r0 = s["right"]
for _ in range(3):
    key("ArrowLeft")
time.sleep(0.4)
s = state()
print("5 after 3x left:", s["right"], "t", s["t"])
assert s["right"] == r0 - 3
key("ArrowRight", shift=True)
time.sleep(0.4)
s = state()
print("6 after shift+right:", s["right"])
assert s["right"] == r0 - 3 + 30

# drag left handle to 20%
pointer("pointerdown", 3)
pointer("pointermove", int(W * 0.2))
pointer("pointerup", int(W * 0.2))
time.sleep(0.4)
s = state()
print("7 after drag left:", {k: s[k] for k in ("left", "right", "sel")})
assert s["sel"] == "left" and 250 < s["left"] < 400
# push left beyond right -> blocked
pointer("pointerdown", handle_x("left", W))
pointer("pointermove", W - 1)
pointer("pointerup", W - 1)
time.sleep(0.3)
s = state()
print("8 push past right:", {k: s[k] for k in ("left", "right")})
assert s["left"] == s["right"] - 1
# restore left to 20%
pointer("pointerdown", handle_x("left", W))
pointer("pointermove", int(W * 0.2))
pointer("pointerup", int(W * 0.2))
time.sleep(0.3)

# escape + playhead step
key("Escape")
s = state()
assert s["sel"] is None
t0 = s["t"]
key("ArrowRight")
time.sleep(0.3)
s = state()
print("9 playhead step:", t0, "->", s["t"])
assert 0.02 < s["t"] - t0 < 0.05

# loop: seek just before right handle, play, expect jump to left
js("window.__ciach.video.currentTime = window.__ciach.frameTs(window.__ciach.S.right) - 0.3; true")
time.sleep(0.3)
key("Space")
time.sleep(1.2)
s = state()
lt = js("window.__ciach.frameTs(window.__ciach.S.left)")
print("10 loop:", "t", s["t"], "left", lt, "paused", s["paused"])
assert not s["paused"] and lt <= s["t"] < lt + 1.5
key("Space")
time.sleep(0.2)

# zoom via wheel around 50%
js("(()=>{const c=document.getElementById('tl');const r=c.getBoundingClientRect();"
   "c.dispatchEvent(new WheelEvent('wheel',{deltaY:-300,clientX:r.left+%d,clientY:r.top+50,bubbles:true,cancelable:true}));return true})()" % (W // 2))
time.sleep(0.3)
s = state()
print("11 zoomed view:", s["view"])
assert s["view"]["end"] - s["view"]["start"] < s["dur"] * 0.8
shot("t3_zoomed.png")
js("document.getElementById('tl').dispatchEvent(new MouseEvent('dblclick',{bubbles:true})); true")
time.sleep(0.2)
s = state()
assert abs(s["view"]["end"] - s["dur"]) < 1e-6 and s["view"]["start"] == 0

# export via Enter
sel = js("(()=>{const S=window.__ciach.S;return [window.__ciach.frameTs(S.left), window.__ciach.frameTs(S.right), S.right-S.left]})()")
print("12 export range:", sel)
key("Enter")
time.sleep(0.5)
s = state()
print("   status:", s["status"], "| title:", s["title"])
shot("t4_exporting.png")
wait("(document.getElementById('status').textContent||'').startsWith('Gotowe')", 300, "export done")
s = state()
print("13 done:", s["status"])
shot("t5_done.png")
outs = [f for f in os.listdir(PROJ) if f.startswith(TEST_STEMS) and f.endswith("_ciach.mp4")]
print("   files:", outs)
out = os.path.join(PROJ, outs[0])
pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,nb_frames,start_time:format=duration",
                     "-of", "compact", out], capture_output=True, text=True)
print("   probe:", pr.stdout.strip().replace("\n", " | "))
assert "nb_frames=%d" % sel[2] in pr.stdout

# Mały Ciach (Ctrl+Enter) na krótkim fragmencie: plik _ciach_maly, rozmiar w komunikacie, < 25 MB
js("(()=>{const S=window.__ciach.S;S.left=window.__ciach.frameIndex(5);S.right=window.__ciach.frameIndex(25);return true})()")
js("window.dispatchEvent(new KeyboardEvent('keydown',{code:'Enter',ctrlKey:true,bubbles:true,cancelable:true})); true")
time.sleep(0.5)
print("12b small status:", status_text())
assert status_text().startswith("Mały ciach")
wait("(document.getElementById('status').textContent||'').startsWith('Gotowe')", 600, "small export done")
st = status_text()
print("13b small done:", st)
assert "_ciach_maly" in st and "MB)" in st
small_out = [f for f in os.listdir(PROJ) if f.startswith(TEST_STEMS[0]) and f.endswith("_ciach_maly.mp4")]
assert small_out and os.path.getsize(os.path.join(PROJ, small_out[0])) < 25_000_000
pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,nb_frames:format=size",
                     "-of", "compact", os.path.join(PROJ, small_out[0])], capture_output=True, text=True)
print("   probe:", pr.stdout.strip().replace("\n", " | "))

# load mp3 via api
js("window.pywebview.api.open_path(%s); true" % json.dumps(MP3))
wait("window.__ciach.S.kind==='audio' && window.__ciach.S.loaded && !!window.__ciach.S.frames && !!window.__ciach.S.wave", 60, "mp3 loaded")
time.sleep(0.5)
s = state()
print("14 mp3:", {k: s[k] for k in ("kind", "N", "dur", "cls", "title", "right")})
shot("t6_mp3.png")
pointer("pointerdown", W - 3)
pointer("pointermove", int(W * 0.5))
pointer("pointerup", int(W * 0.5))
time.sleep(0.3)
key("Enter")
wait("(document.getElementById('status').textContent||'').startsWith('Gotowe')", 60, "mp3 export")
print("15 mp3 export:", status_text())
outs = [f for f in os.listdir(PROJ) if f.startswith(TEST_STEMS[1]) and f.endswith("_ciach.mp3")]
assert outs
pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags=title", "-of", "compact",
                     os.path.join(PROJ, outs[0])], capture_output=True, text=True)
print("   probe:", pr.stdout.strip().replace("\n", " | "))

# reject: unsupported extension
js("window.pywebview.api.open_path(%s); true" % json.dumps(os.path.join(SP, "shot_window.ps1")))
time.sleep(1.0)
print("16 reject:", status_text())

# collision name: export again -> (2)
key("Enter")
wait("(document.getElementById('status').textContent||'').startsWith('Gotowe')", 60, "mp3 export 2")
print("17 second export:", status_text())

# cancel on close: start a long mp4 export and close the window
js("window.pywebview.api.open_path(%s); true" % json.dumps(MP4))
wait("window.__ciach.S.kind==='video' && window.__ciach.S.loaded && !!window.__ciach.S.frames", 60, "mp4 reload")
key("Enter")
time.sleep(1.0)
print("18 long export status:", status_text())
print("   partial present:", [f for f in os.listdir(PROJ) if f.startswith(TEST_STEMS[0]) and f.endswith(".mp4")])
close_app()
try:
    proc.wait(timeout=15)
    print("19 closed, rc", proc.returncode)
except subprocess.TimeoutExpired:
    proc.kill()
    print("19 KILL needed")
time.sleep(0.5)
print("   files after close:", [f for f in os.listdir(PROJ) if f.startswith(TEST_STEMS)])
clean_test_outputs()
print("ALL OK")
