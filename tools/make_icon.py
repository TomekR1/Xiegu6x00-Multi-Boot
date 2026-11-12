"""Draws the app icon: a small HF transceiver in the X6100's layout (an original drawing:
screen with a waterfall, five keys under it, small knobs left, the big tuning knob right).

    python tools/make_icon.py      -> x6100mb/assets/icon.png, icon.ico, icon.icns
"""
import os

from PIL import Image, ImageDraw, ImageFilter

S = 1024
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "x6100mb", "assets")


def radio():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # soft shadow
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([70, 300, 970, 790], radius=70, fill=(0, 0, 0, 150))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(28)))
    d = ImageDraw.Draw(img)
    # body
    d.rounded_rectangle([52, 262, 972, 762], radius=64, fill=(38, 40, 46), outline=(88, 92, 102), width=10)
    d.rounded_rectangle([72, 282, 952, 330], radius=28, fill=(52, 55, 63))
    # screen
    d.rounded_rectangle([262, 338, 742, 612], radius=18, fill=(10, 12, 18), outline=(110, 116, 128), width=6)
    # spectrum + waterfall
    for x in range(278, 728, 6):
        h = 30 + int(60 * abs(((x * 37) % 97) / 97 - 0.5)) + (70 if 470 < x < 500 else 0)
        d.line([(x, 470), (x, 470 - h)], fill=(70, 200, 255), width=4)
    for y in range(478, 600, 6):
        for x in range(278, 728, 12):
            v = ((x * 13 + y * 7) % 41) / 41
            hot = 470 < x < 500
            c = (int(30 + 200 * v), int(40 + 120 * v), 200) if not hot else (255, 210, 60)
            d.rectangle([x, y, x + 10, y + 4], fill=c)
    d.text((290, 352), "14.074", fill=(240, 240, 240))
    # F1..F5 keys
    for i in range(5):
        x = 270 + i * 96
        d.rounded_rectangle([x, 636, x + 80, 676], radius=10, fill=(215, 218, 225))
        d.rounded_rectangle([x + 26, 652, x + 54, 660], radius=4, fill=(60, 63, 72))
    # left knobs and buttons
    for cx, cy, r in ((160, 410, 52), (160, 600, 52)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(22, 23, 27), outline=(120, 124, 134), width=8)
        d.line([(cx, cy - r + 12), (cx, cy - r + 34)], fill=(200, 200, 200), width=8)
    for y in (482, 528):
        d.rounded_rectangle([96, y, 150, y + 30], radius=8, fill=(215, 218, 225))
        d.rounded_rectangle([170, y, 224, y + 30], radius=8, fill=(215, 218, 225))
    d.ellipse([196, 380, 216, 400], fill=(80, 230, 90))
    # big tuning knob
    cx, cy, r = 858, 500, 110
    d.ellipse([cx - r - 14, cy - r - 14, cx + r + 14, cy + r + 14], fill=(70, 74, 84))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(26, 27, 32), outline=(150, 154, 164), width=10)
    d.ellipse([cx - 64, cy - 64, cx + 64, cy + 64], fill=(44, 46, 54))
    d.ellipse([cx + 18, cy - 54, cx + 46, cy - 26], fill=(150, 154, 164))
    # "multi" badge: three stacked cards
    for k, col in enumerate(((0, 170, 200), (240, 150, 30), (210, 40, 50))):
        x0, y0 = 690 + k * 38, 92 + k * 38
        d.rounded_rectangle([x0, y0, x0 + 210, y0 + 150], radius=24, fill=col, outline=(255, 255, 255), width=8)
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
