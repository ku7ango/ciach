"""Generuje icon.ico (nożyczki) bez zewnętrznych plików."""
from PIL import Image, ImageDraw

SIZES = [256, 128, 64, 48, 32, 16]


def draw_scissors(size: int) -> Image.Image:
    s = 8  # supersampling
    W = size * s
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # tło: zaokrąglony kwadrat
    pad = W * 0.04
    d.rounded_rectangle([pad, pad, W - pad, W - pad], radius=W * 0.22, fill=(27, 27, 31, 255))
    orange = (255, 140, 26, 255)
    blue = (138, 164, 255, 255)
    lw = max(1, int(W * 0.075))
    cx, cy = W * 0.5, W * 0.5
    # ostrza: dwie linie krzyżujące się w środku, idące w prawo-górę i prawo-dół
    d.line([(cx - W * 0.02, cy), (W * 0.86, W * 0.16)], fill=blue, width=lw)
    d.line([(cx - W * 0.02, cy), (W * 0.86, W * 0.84)], fill=blue, width=lw)
    # nit
    r = W * 0.055
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=orange)
    # uchwyty: dwa pierścienie po lewej
    R = W * 0.13
    ring = max(1, int(W * 0.06))
    for oy in (-1, 1):
        ox, oyy = W * 0.26, cy + oy * W * 0.19
        d.ellipse([ox - R, oyy - R, ox + R, oyy + R], outline=orange, width=ring)
        # łącznik uchwytu z nitem
        d.line([(ox + R * 0.7, oyy - oy * R * 0.5), (cx - W * 0.03, cy)], fill=orange, width=lw)
    return img.resize((size, size), Image.LANCZOS)


def main():
    frames = [draw_scissors(sz) for sz in SIZES]
    frames[0].save("icon.ico", format="ICO", sizes=[(sz, sz) for sz in SIZES],
                   append_images=frames[1:])
    frames[0].save("icon.png")
    print("icon.ico zapisany")


if __name__ == "__main__":
    main()
