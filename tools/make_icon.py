"""Draws the app icon: the X6100's front as it is laid out (an original drawing, no photograph:
ribbed bumpers, VOL and MFK knobs and the small keys left, the screen with a spectrum and a
waterfall, five keys under it, the speaker's slots and the big tuning knob right).

    python tools/make_icon.py      -> x6100mb/assets/icon.png, icon.ico, icon.icns
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 1024
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "x6100mb", "assets")


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _knob(d, cx, cy, r, ridges):
    """A knurled knob seen from the front: a ridged rim, a flat cap lit from above"""
    d.ellipse([cx - r - 6, cy - r - 2, cx + r + 6, cy + r + 10], fill=(8, 8, 10))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(30, 31, 35))
    for k in range(ridges):
        a = 2 * math.pi * k / ridges
        x0, y0 = cx + (r - 1) * math.cos(a), cy + (r - 1) * math.sin(a)
        x1, y1 = cx + (r * 0.80) * math.cos(a), cy + (r * 0.80) * math.sin(a)
        d.line([(x0, y0), (x1, y1)], fill=(64, 66, 73), width=max(2, r // 24))
    d.ellipse([cx - r * 0.78, cy - r * 0.78, cx + r * 0.78, cy + r * 0.78], fill=(44, 45, 51), outline=(70, 72, 80), width=3)
    d.ellipse([cx - r * 0.70, cy - r * 0.74, cx + r * 0.70, cy + r * 0.62], fill=(52, 54, 60))


def radio():
    """The X6100's front as it is laid out: ribbed bumpers at both ends; left the VOL knob, the
    power key, six small keys and the MFK knob; the screen with five keys under it; right the
    speaker's slots and the large tuning knob"""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([50, 300, 990, 820], radius=50, fill=(0, 0, 0, 170))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(26)))
    d = ImageDraw.Draw(img)
    X0, Y0, X1, Y1 = 28, 248, 996, 790
    # the bumpers (ribbed, a little taller than the body) and the body between them
    for bx0, bx1 in ((X0, X0 + 92), (X1 - 92, X1)):
        d.rounded_rectangle([bx0, Y0, bx1, Y1], radius=26, fill=(26, 27, 30), outline=(70, 72, 78), width=5)
        for k in range(7):
            y = Y0 + 44 + k * 68
            d.rounded_rectangle([bx0 + 10, y, bx1 - 10, y + 26], radius=8, fill=(40, 41, 46))
            d.line([(bx0 + 14, y + 2), (bx1 - 14, y + 2)], fill=(62, 64, 70), width=3)
    d.rounded_rectangle([X0 + 70, Y0 + 14, X1 - 70, Y1 - 14], radius=22, fill=(22, 23, 26), outline=(66, 68, 75), width=5)
    d.rounded_rectangle([X0 + 80, Y0 + 22, X1 - 80, Y0 + 44], radius=10, fill=(38, 39, 44))        # light on the top edge
    # the screen in its bezel
    sx0, sy0, sx1, sy1 = 300, 296, 742, 660
    d.rounded_rectangle([sx0 - 14, sy0 - 14, sx1 + 14, sy1 + 14], radius=18, fill=(6, 6, 8), outline=(58, 60, 66), width=4)
    d.rectangle([sx0, sy0, sx1, sy1], fill=(6, 12, 34))
    # the screen: a status line, the frequency, the spectrum, the waterfall, the soft keys' labels
    d.rectangle([sx0, sy0, sx1, sy0 + 78], fill=(10, 14, 30))
    d.rounded_rectangle([sx0 + 8, sy0 + 8, sx0 + 84, sy0 + 38], radius=5, fill=(30, 110, 215))
    d.rounded_rectangle([sx0 + 8, sy0 + 44, sx0 + 84, sy0 + 72], radius=5, fill=(30, 110, 215))
    d.text((sx0 + 96, sy0 + 4), "07.050.000", font=_font(52), fill=(245, 247, 250))
    d.rounded_rectangle([sx1 - 96, sy0 + 44, sx1 - 8, sy0 + 72], radius=5, fill=(24, 60, 40), outline=(60, 190, 90), width=2)
    for k in range(5):
        d.rounded_rectangle([sx0 + 96 + k * 42, sy0 + 60, sx0 + 130 + k * 42, sy0 + 72], radius=3,
                            fill=(60, 66, 84) if k else (40, 170, 80))
    top, mid, bot = sy0 + 84, sy0 + 190, sy1 - 46
    d.rectangle([sx0, top, sx1, mid], fill=(8, 16, 46))
    for gy in range(top + 26, mid, 26):
        d.line([(sx0, gy), (sx1, gy)], fill=(26, 40, 84), width=1)
    for gx in range(sx0 + 44, sx1, 44):
        d.line([(gx, top), (gx, mid)], fill=(26, 40, 84), width=1)
    pts = []
    for x in range(sx0, sx1 + 1, 3):
        n = ((x * 7919) % 23) / 23 * 12 + ((x * 104729) % 11)
        peak = sum(h * math.exp(-((x - c) / w) ** 2) for c, h, w in ((478, 70, 5), (560, 44, 4), (392, 30, 6), (660, 52, 3)))
        pts.append((x, mid - 14 - n - peak))
    d.line(pts, fill=(80, 230, 110), width=3)
    d.line([(521, top), (521, mid)], fill=(230, 60, 60), width=2)
    d.rectangle([sx0, mid, sx1, bot], fill=(6, 18, 70))
    for y in range(mid, bot, 4):
        for x in range(sx0, sx1, 6):
            v = ((x * 31 + y * 17) % 53) / 53
            c = (10, int(30 + 60 * v), int(110 + 110 * v))
            for cc, w in ((478, 7), (560, 5), (392, 8), (660, 4)):
                if abs(x - cc - ((y * 3) % 5 - 2)) < w and (y // 4 + cc) % 3:
                    c = (150, 215, 255) if w < 6 else (90, 170, 250)
            d.rectangle([x, y, x + 5, y + 3], fill=c)
    d.rectangle([sx0, bot, sx1, sy1], fill=(12, 20, 60))
    for k in range(5):
        x = sx0 + 10 + k * 87
        d.rounded_rectangle([x, bot + 6, x + 76, sy1 - 6], radius=5, fill=(26, 44, 112), outline=(70, 96, 190), width=2)
        d.line([(x + 14, bot + 18), (x + 62, bot + 18)], fill=(225, 230, 245), width=4)
        d.line([(x + 22, bot + 29), (x + 54, bot + 29)], fill=(225, 230, 245), width=4)
    # the five keys under the screen: black, a light frame in each
    for k in range(5):
        x = sx0 + 6 + k * 88
        d.rounded_rectangle([x, 694, x + 78, 742], radius=11, fill=(36, 37, 42), outline=(84, 86, 94), width=3)
        d.rounded_rectangle([x + 16, 708, x + 62, 728], radius=7, outline=(222, 225, 232), width=4)
    # left: VOL, the light and the power key, six keys, MFK
    _knob(d, 196, 330, 44, 30)
    d.ellipse([146, 400, 164, 418], fill=(70, 78, 74), outline=(110, 116, 112), width=2)
    d.rounded_rectangle([184, 392, 240, 426], radius=9, fill=(40, 41, 46), outline=(214, 217, 224), width=3)
    d.arc([201, 398, 223, 420], 300, 240, fill=(214, 217, 224), width=3)
    d.line([(212, 396), (212, 408)], fill=(214, 217, 224), width=3)
    for r_ in range(3):
        for c_ in range(2):
            x, y = 136 + c_ * 62, 452 + r_ * 54
            d.rounded_rectangle([x, y, x + 52, y + 40], radius=9, fill=(40, 41, 46), outline=(214, 217, 224), width=3)
            d.line([(x + 12, y + 20), (x + 40, y + 20)], fill=(214, 217, 224), width=4)
    _knob(d, 196, 678, 44, 30)
    # right: the name, the speaker's slots, the lock key, the tuning knob
    d.text((776, 286), "X6100", font=_font(40), fill=(236, 238, 242))
    d.line([(778, 334), (896, 334)], fill=(170, 174, 182), width=4)
    for k in range(6):
        y = 366 + k * 22
        d.rounded_rectangle([772, y, 898, y + 10], radius=5, fill=(8, 8, 10), outline=(52, 54, 60), width=2)
    d.rounded_rectangle([764, 520, 796, 548], radius=8, fill=(40, 41, 46), outline=(120, 124, 132), width=3)
    _knob(d, 836, 638, 98, 56)
    d.ellipse([868, 574, 898, 604], fill=(26, 27, 31), outline=(84, 86, 94), width=3)      # the finger dimple
    # "multi" badge: three stacked cards
    for k, col in enumerate(((0, 170, 200), (240, 150, 30), (210, 40, 50))):
        x0, y0 = 706 + k * 36, 68 + k * 36
        d.rounded_rectangle([x0, y0, x0 + 196, y0 + 138], radius=24, fill=col, outline=(255, 255, 255), width=8)
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    big = radio()
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "icon.png"))
    big.save(os.path.join(OUT, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(os.path.join(OUT, "icon.icns"))
    big.resize((512, 512), Image.LANCZOS).save(os.path.join(OUT, "icon-512.png"))


if __name__ == "__main__":
    main()
