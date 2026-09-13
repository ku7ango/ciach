"""Test UI Wycięć (ADR 0002). Steruje oknem przez endpoint debugowy (CIACH_DEBUG=1), zrzuty przez
PrintWindow, bez SendKeys i bez zabierania fokusu. Pokrywa: C w Playheadzie, C dociągające
Krawędzie (dalej, bliżej, przed początkiem), blokady (Enter, Głośność, drop), przeciąganie Krawędzi
myszą z Przyciąganiem do Styku, odtwarzanie pomijające Wycięcie, Esc, wykonanie Delete (Nagrania na
kawałki, Suwaki, Zbliżenie z pozycjami, Podkład trzymający Klatkę), Ciach z dziurą, Ctrl+Z,
Wycięcie na Podkładzie (odcinki), Delete Nagrania jako Wycięcie, sklejanie po Wycięciu (remap).

Użycie:  venv/Scripts/python tests/drive_cut.py [--exe]
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SP = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(SP)
sys.path.insert(0, SP)
import test_sekwencja as ts  # noqa: E402

A, B, P = ts.A, ts.B, ts.P
ts.gen(A, 4.0)
ts.gen(B, 2.5)
ts.gen_mp3(P, 6.0, 1000)
TEST_STEMS = ts.TEST_STEMS
USE_EXE = "--exe" in sys.argv
PORTFILE = os.path.join(SP, "_port_cut.txt")
if os.path.exists(PORTFILE):
    os.remove(PORTFILE)
env = dict(os.environ, CIACH_DEBUG="1", CIACH_PORTFILE=PORTFILE, PYTHONIOENCODING="utf-8")
log = open(os.path.join(SP, "_app_cut.log"), "w", encoding="utf-8")
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
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "$ids=@(%d)+@(Get-CimInstance Win32_Process -Filter 'ParentProcessId = %d' | %%{ $_.ProcessId });"
                        "(Get-Process | ? { $ids -contains $_.Id -and $_.MainWindowHandle -ne 0 } | select -First 1).MainWindowTitle"
                        % (proc.pid, proc.pid)], capture_output=True, text=True, encoding="utf-8")
    return (r.stdout or "").strip()


def key(code, shift=False, ctrl=False):
    js("window.dispatchEvent(new KeyboardEvent('keydown',{code:'%s',shiftKey:%s,ctrlKey:%s,bubbles:true,cancelable:true}));"
       "window.dispatchEvent(new KeyboardEvent('keyup',{code:'%s',bubbles:true})); true"
       % (code, str(shift).lower(), str(ctrl).lower(), code))
    time.sleep(0.15)


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


def xs(s):
    """Piksel dla czasu Sekwencji."""
    return js("(()=>{const S=window.__ciach.S;const W=document.getElementById('tl').clientWidth;"
              "return (%r - S.view.start)/(S.view.end-S.view.start)*W})()" % s)


def seqs(i):
    return js("window.__ciach.S.seqs[%d]" % i)


def frame_ts(i):
    return js("window.__ciach.frameTs(%d)" % i)


def goto(i):
    """Playhead na Klatkę i (jak klik w timeline)."""
    js("window.__ciach.video.currentTime = window.__ciach.frameTs(%d) + 0.001; true" % i)
    time.sleep(0.2)


def state():
    return js("(()=>{const S=window.__ciach.S;const v=window.__ciach.video;const st=document.getElementById('status');"
              "return {N:S.N,dur:S.duration,fileDur:S.fileDuration,left:S.left,right:S.right,sel:S.sel,cut:S.cut,undo:S.undo.length,"
              "parts:S.parts.map(p=>[p.name,p.src,+p.in.toFixed(3),+p.out.toFixed(3)]),pieces:S.pieces,"
              "pods:S.pods.map(p=>({gen:p.gen,at:p.at,segs:p.segs.map(s=>[+s.tin.toFixed(4),+s.tout.toFixed(4)]),paused:p.audio?p.audio.paused:null})),"
              "zooms:S.zooms.map(z=>({at:z.at,end:z.end,keys:z.keys.map(q=>[q.t,+q.k.x.toFixed(3)])})),"
              "t:v.currentTime,paused:v.paused,busy:S.busy,status:st.hidden?null:st.textContent}})()")


def drop(paths, where, index=None):
    code = """(()=>{const c=document.getElementById('tl');const r=c.getBoundingClientRect();
      const pv=document.getElementById('preview').getBoundingClientRect();const L=window.__ciach.layout(true);
      const S=window.__ciach.S;const W=c.clientWidth;const xS=t=>(t-S.view.start)/(S.view.end-S.view.start)*W;
      let x,y; const where=%s, idx=%s;
      if(where==='gniazdo'){const n=S.pieces.length;const t=idx<n?S.seqs[S.pieces[idx].ia]:S.duration;
        const cx=idx===0?xS(t)+8:idx===n?xS(t)-8:xS(t);x=r.left+cx;y=r.top+L.vidTop+L.vidH/2;}
      else if(where==='strip'){x=r.left+W/2;y=r.top+L.stripTop+5;}
      else {x=pv.left+pv.width/2;y=pv.top+pv.height/2;}
      return window.__ciach.dropFiles(%s,x,y);})()""" % (json.dumps(where), json.dumps(index), json.dumps(paths))
    return js(code)


def probe(path):
    pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,nb_frames", "-of", "compact", path],
                        capture_output=True, text=True)
    return pr.stdout.strip().replace("\n", " | ")


VID_Y = 22 + 34  # środek wiersza Sekwencji

try:
    wait("!!(window.__ciach && window.__ciach.S.loaded && window.__ciach.S.scanned)", 60, "loaded")
    # Sekwencja A + B (195 Klatek), Podkład zaczepiony w Klatce 130 (w B), Zbliżenie [30, 150) z przejazdem
    drop([B], "gniazdo", 1)
    wait("window.__ciach.S.parts.length===2 && window.__ciach.S.scanned && !window.__ciach.S.busy", 60, "joined")
    drop([P], "strip")
    wait("window.__ciach.S.pods.length===1 && window.__ciach.S.pods[0].wave", 30, "podklad")
    js("(()=>{const S=window.__ciach.S;S.pods[0].at=window.__ciach.frameTs(130);S.sel=null;return true})()")
    goto(30)
    js("window.__ciach.commitKadr({x:0.5,y:0,s:0.5}); true")
    js("(()=>{const S=window.__ciach.S;const z=S.zooms[0];z.end=window.__ciach.frameTs(150);"
       "z.keys.push({t:window.__ciach.frameTs(149),k:{x:0,y:0,s:0.5}});S.sel=null;return true})()")
    js("(()=>{const S=window.__ciach.S;S.left=20;S.right=150;return true})()")
    time.sleep(0.3)
    s = state()
    print("1 setup:", s["parts"], "N", s["N"], "pod at", s["pods"][0]["at"], "zoom", s["zooms"][0]["keys"])
    assert s["N"] == 195 and len(s["pieces"]) == 2 and abs(s["pods"][0]["at"] - frame_ts(130)) < 1e-6
    pod_at0 = s["pods"][0]["at"]

    # C w Klatce 60: Wycięcie od 60, prawa Krawędź kawałek dalej (nie 1 Klatka, ale i nie pół ekranu)
    goto(60)
    key("KeyC")
    s = state()
    print("2 C:", s["cut"], "sel", s["sel"], "status", s["status"])
    assert s["cut"] == {"pod": None, "a": 60, "b": s["cut"]["b"]} and 61 < s["cut"]["b"] < 90
    shot("c1_wyciecie.png")

    # Shift+→ = 1 s Playheada (Suwaki nie są zaznaczone), C dociąga koniec; przed początkiem C dociąga początek; bliżej skraca
    key("ArrowRight", shift=True)
    key("KeyC")
    assert state()["cut"]["b"] == 90, state()["cut"]
    key("ArrowLeft", shift=True)
    key("ArrowLeft", shift=True)
    key("KeyC")
    assert state()["cut"] == {"pod": None, "a": 30, "b": 90}, state()["cut"]
    goto(75)
    key("KeyC")
    s = state()
    print("3 dociaganie:", s["cut"])
    assert s["cut"] == {"pod": None, "a": 30, "b": 75}

    # blokady: Ciach, Głośność, drop, Z; Suwaki wolno
    key("Enter")
    s = state()
    assert "Najpierw wytnij" in (s["status"] or "") and s["cut"] is not None, s
    key("ArrowUp")
    assert "Najpierw wytnij" in (state()["status"] or "")
    assert drop([P], "strip") == "cut" and len(state()["pods"]) == 1
    key("KeyZ")
    assert js("window.__ciach.S.zKey") is False
    key("ArrowLeft")
    key("Escape")  # tu: porzuca Wycięcie, nie odznacza
    assert state()["cut"] is None
    print("4 blokady ok")

    # znów Wycięcie [30, 75); prawa Krawędź myszą z Ctrl (bez Przyciągania) na ~Klatkę 90, potem
    # z Przyciąganiem do Styku (120) z odległości 5 px; obraz pokazuje Klatkę pod Krawędzią
    goto(30)
    key("KeyC")
    goto(75)
    key("KeyC")
    assert state()["cut"] == {"pod": None, "a": 30, "b": 75}
    drag(xs(seqs(75)), VID_Y, xs(seqs(90)), VID_Y, ctrl=True)
    s = state()
    print("5 drag:", s["cut"], "t", s["t"], "kl.90", frame_ts(90))
    assert 88 <= s["cut"]["b"] <= 92 and abs(s["t"] - frame_ts(s["cut"]["b"])) < 0.02
    b0 = s["cut"]["b"]
    drag(xs(seqs(b0)), VID_Y, xs(seqs(120)) - 5, VID_Y)
    s = state()
    print("   snap:", s["cut"])
    assert s["cut"] == {"pod": None, "a": 30, "b": 120}, "prawa Krawędź powinna przyciągnąć się do Styku"
    drag(xs(seqs(120)), VID_Y, xs(seqs(75)), VID_Y, ctrl=True)
    s = state()
    assert 73 <= s["cut"]["b"] <= 77, s["cut"]
    b0 = s["cut"]["b"]

    # odtwarzanie pomija Wycięcie: start w Klatce 25, po 0,8 s Playhead jest za Klatką b0
    js("window.__ciach.video.muted=true; true")
    goto(25)
    key("Space")
    time.sleep(0.9)
    s = state()
    key("Space")
    print("6 play:", s["t"], "b0", frame_ts(b0), "paused", s["paused"])
    if not s["paused"]:
        assert s["t"] >= frame_ts(b0) - 0.02 and s["t"] < frame_ts(b0) + 1.0, "odtwarzanie powinno przeskoczyć Wycięcie"
    js("(()=>{const c=window.__ciach.S.cut;c.b=75;return true})()")
    goto(50)  # Playhead wewnątrz Wycięcia: po wykonaniu ma stanąć na Styku

    # Delete wykonuje: A na dwa kawałki, Suwaki jadą z obrazem, Zbliżenie skrócone z pozycjami na
    # brzegach, Podkład trzyma swoją Klatkę, Playhead na Styku, tytuł +2
    key("Delete")
    time.sleep(0.4)
    s = state()
    title = win_title()
    print("7 wyciete:", s["parts"], "N", s["N"], "suwaki", s["left"], s["right"], "t", s["t"], "pod", s["pods"][0]["at"],
          "zoom", s["zooms"][0], "undo", s["undo"], "title", title)
    assert s["cut"] is None and s["N"] == 150 and s["undo"] == 1
    assert [p[0] for p in s["parts"]] == ["_seq_a.mp4", "_seq_a.mp4", "_seq_b.mp4"]
    # in/out w czasie pliku źródłowego: Klatki A leżą ~0,02 s później (opóźnienie AAC w sklejce)
    assert abs(s["parts"][0][3] - 1.0) < 0.04 and abs(s["parts"][1][2] - 2.5) < 0.04 and abs(s["parts"][1][3] - 4.0) < 0.04
    assert s["left"] == 20 and s["right"] == 105
    assert abs(s["t"] - frame_ts(30)) < 0.02 and abs(s["pods"][0]["at"] - pod_at0) < 1e-6
    z = s["zooms"][0]
    assert abs(z["at"] - frame_ts(30)) < 1e-6 and abs(z["end"] - frame_ts(105)) < 1e-6
    assert len(z["keys"]) == 2 and abs(z["keys"][0][0] - frame_ts(30)) < 1e-6 and 0.05 < z["keys"][0][1] < 0.45 and z["keys"][1][1] == 0
    assert title.endswith("+2")
    assert abs(s["dur"] - (s["fileDur"] - 1.5)) < 0.05
    shot("c2_po_wycieciu.png")

    # Ciach Fragmentu [20, 105) z dziurą: liczba klatek = 85, jedna ścieżka AAC
    key("Enter")
    wait("(document.getElementById('status').textContent||'').startsWith('Gotowe')", 300, "export done")
    outs = [f for f in os.listdir(PROJ) if f.startswith(TEST_STEMS[0]) and f.endswith("_ciach.mp4")]
    pr = probe(os.path.join(PROJ, outs[0]))
    print("8 export:", outs[0], pr)
    assert "nb_frames=85" in pr and pr.count("codec_type=audio") == 1 and "codec_name=aac" in pr

    # Ctrl+Z: wszystko wraca
    key("KeyZ", ctrl=True)
    time.sleep(0.4)
    s = state()
    print("9 undo:", s["parts"], "N", s["N"], "suwaki", s["left"], s["right"], "zoom keys", len(s["zooms"][0]["keys"]), "status", s["status"])
    assert s["N"] == 195 and len(s["parts"]) == 2 and s["left"] == 20 and s["right"] == 150 and s["undo"] == 0
    assert len(s["zooms"][0]["keys"]) == 2 and abs(s["zooms"][0]["end"] - frame_ts(150)) < 1e-6
    key("KeyZ", ctrl=True)
    assert "Nie ma czego" in (state()["status"] or "")

    # Wycięcie na Podkładzie: zaznaczony Podkład, C w Klatce 135, C w 150, Delete → odcinki, muzyka dosunięta
    ROW_Y = 22 + 68 + 30 + 22  # wiersz Podkładu pod wierszem Zbliżeń
    pointer("pointerdown", xs(seqs(140)), ROW_Y)
    pointer("pointerup", xs(seqs(140)), ROW_Y)
    time.sleep(0.1)
    assert state()["sel"] == {"pod": s["pods"][0]["gen"], "edge": None}, state()["sel"]
    goto(135)
    key("KeyC")
    s = state()
    print("10 C na Podkladzie:", s["cut"])
    assert s["cut"]["pod"] == s["pods"][0]["gen"] and s["cut"]["a"] == 135
    goto(150)
    key("KeyC")
    assert state()["cut"]["b"] == 150
    shot("c3_podklad_wyciecie.png")
    key("Delete")
    time.sleep(0.3)
    s = state()
    p = s["pods"][0]
    print("   odcinki:", p["segs"], "N", s["N"], "sel", s["sel"])
    assert s["N"] == 195 and s["cut"] is None and len(p["segs"]) == 2
    ua, ub = seqs(135) - seqs(130), seqs(150) - seqs(130)
    assert abs(p["segs"][0][1] - ua) < 1e-3 and abs(p["segs"][1][0] - ub) < 1e-3 and abs(p["segs"][1][1] - 6.0) < 0.05
    assert s["sel"] == {"pod": p["gen"], "edge": None}
    key("KeyZ", ctrl=True)
    time.sleep(0.2)
    assert state()["pods"][0]["segs"] == [[0, 6.0]] or abs(state()["pods"][0]["segs"][0][1] - 6.0) < 0.05

    # Delete Nagrania = Wycięcie całego kawałka: bez zaznaczenia, Playhead w B
    key("Escape")
    goto(150)
    key("Delete")
    time.sleep(0.4)
    s = state()
    title = win_title()
    print("11 usuniete Nagranie:", s["parts"], "N", s["N"], "t", s["t"], "title", title)
    assert len(s["parts"]) == 1 and s["N"] == 120 and "+" not in title and s["t"] <= frame_ts(119) + 0.01
    key("KeyZ", ctrl=True)
    time.sleep(0.4)
    assert state()["N"] == 195 and len(state()["parts"]) == 2
    goto(0)
    key("Delete")  # pierwsze Nagranie (A): B zostaje, Podkład z Klatki 130 → Klatka 10
    time.sleep(0.4)
    s = state()
    print("    usuniete A:", s["parts"], "N", s["N"], "pod at", s["pods"][0]["at"], "kl.10", frame_ts(10))
    assert s["N"] == 75 and s["parts"][0][0] == "_seq_b.mp4" and abs(s["pods"][0]["at"] - frame_ts(10)) < 1e-6
    key("KeyZ", ctrl=True)
    time.sleep(0.4)

    # sklejanie po Wycięciu: [30, 75) wycięte, B w Gniazdo między kawałki A → kopia A dublowana,
    # Podkład i Zbliżenie jadą z obrazem, lista cofnięć czyszczona
    goto(30)
    key("KeyC")
    goto(75)
    key("KeyC")
    key("Delete")
    time.sleep(0.3)
    assert state()["N"] == 150 and len(state()["parts"]) == 3
    r = drop([B], "gniazdo", 1)
    wait("window.__ciach.S.parts.length===4 && window.__ciach.S.scanned && !window.__ciach.S.busy", 60, "joined after cut")
    time.sleep(0.5)
    s = state()
    print("12 join po Wycieciu:", r, s["parts"], "N", s["N"], "pod at", s["pods"][0]["at"], "kl.160", frame_ts(160),
          "zoom", s["zooms"][0]["at"], s["zooms"][0]["end"], "undo", s["undo"])
    assert [p[0] for p in s["parts"]] == ["_seq_a.mp4", "_seq_b.mp4", "_seq_a.mp4", "_seq_b.mp4"] and s["N"] == 225
    assert abs(s["pods"][0]["at"] - frame_ts(160)) < 1e-6, "Podkład trzyma się swojej Klatki obrazu po sklejeniu"
    # Zbliżenie [30, 105) leżało w drugim kawałku A i na początku B: teraz Klatki 105..180 (B wstawione przed nim ma 75 Klatek)
    assert abs(s["zooms"][0]["at"] - frame_ts(105)) < 1e-6 and abs(s["zooms"][0]["end"] - frame_ts(180)) < 1e-6
    assert s["undo"] == 0 and s["right"] == 225
    shot("c4_sklejone_po_wycieciu.png")
finally:
    close_app()
    try:
        proc.wait(timeout=15)
        print("13 closed, rc", proc.returncode)
    except subprocess.TimeoutExpired:
        proc.kill()
        print("13 KILL needed")
    ts.clean()
print("ALL OK")
