"""Test czystej funkcji planowania Małego Ciachu. Uruchom: venv\\Scripts\\python tests\\test_plan_small.py"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # konsola Windows w cp1252 nie zna polskich liter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ciach import SMALL_LIMIT, plan_small_video  # noqa: E402

OBS30 = dict(width=1280, height=720, fps=30.0, vbitrate=6_000_000, abitrate=160_000, audio_streams=1, factor=0.98)
OBS60 = dict(OBS30, fps=60.0)


def plan(src, dur):
    return plan_small_video(dur, **src)


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL") + " " + msg)
    if not cond:
        sys.exit(1)


print("720p30:")
for dur, exp_h, exp_a in [(20, 720, "copy"), (60, 720, "copy"), (100, 720, "aac"), (150, 540, "aac"),
                          (240, 360, "aac"), (480, 360, "aac")]:
    p = plan(OBS30, dur)
    check(p["height"] == exp_h and p["a_mode"] == exp_a and p["fps"] == 30.0,
          f"{dur:4d} s -> {p['height']}p{p['fps']:g}, wideo {p['v_rate']/1e6:.2f} Mbit/s, audio {p['a_mode']} {p['a_rate']//1000}k"
          + (" mono" if p["mono"] else ""))

print("720p60:")
for dur, exp_h, exp_fps in [(30, 720, 60.0), (60, 720, 60.0), (90, 720, 30.0), (120, 720, 30.0),
                            (180, 540, 30.0), (240, 360, 30.0)]:
    p = plan(OBS60, dur)
    check(p["height"] == exp_h and p["fps"] == exp_fps,
          f"{dur:4d} s -> {p['height']}p{p['fps']:g}, wideo {p['v_rate']/1e6:.2f} Mbit/s, audio {p['a_mode']} {p['a_rate']//1000}k")

print("ograniczenie do bitrate źródła:")
p = plan(OBS30, 20)
check(p["v_rate"] == 6_000_000, f"20 s -> {p['v_rate']} = bitrate źródła")

print("budżet nie przekracza limitu:")
for dur in (20, 60, 100, 150, 240, 480, 1200):
    p = plan(OBS30, dur)
    est = (p["v_rate"] + p["a_rate"]) * dur / 8
    check(est <= SMALL_LIMIT * 0.98, f"{dur:4d} s -> szacunek {est/1e6:.2f} MB")

print("brak audio / wiele ścieżek:")
p = plan_small_video(60, 1280, 720, 30.0, 6_000_000, 0, 0, 0.98)
check(p["a_mode"] == "none", "0 ścieżek -> none")
p = plan_small_video(60, 1280, 720, 30.0, 6_000_000, 160_000, 2, 0.98)
check(p["a_mode"] == "aac" and p["a_rate"] == 160_000, "2 ścieżki, 60 s -> aac 160k (miks)")
print("ALL OK")
