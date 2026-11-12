"""The menu screen as a picture: a tile with a logo per system, above its F1..F5 key.

Drawn landscape (800x480, as the radio is held), then turned into the panel's own portrait
framebuffer layout: U-Boot's `bmp display` draws unrotated, while its console is rotated
(CONFIG_VIDEO_SUNXI_ROTATION=3: landscape (x, y) is framebuffer (y, 799 - x)).

Text row 1 (pixels 32..63) stays black: U-Boot writes the countdown there over the picture.
Needs Pillow; without it the menu is text only (compose.py).
"""
import hashlib
import io

try:
    from PIL import Image, ImageDraw, ImageFont
    HAVE_PIL = True
except ImportError:          # the menu falls back to text
    HAVE_PIL = False

W, H = 800, 480
COL_W = W // 5
TEXT_ROW_Y = (32, 64)        # console row 1 with the 16x32 font
ACCENT = (63, 169, 245)
GO = (52, 199, 89)
TILE = (22, 27, 38)
TILE_EDGE = (48, 56, 74)
WHITE = (240, 242, 247)
GREY = (150, 158, 175)

# Colours of the generated logos by system family (a logo of one's own can be chosen in the app)
FAMILIES = [
    ("cx8anm", "CX8ANM", ((20, 120, 70), (60, 200, 120))),
    ("1ko125", "1KO125", ((0, 110, 140), (40, 170, 210))),
    ("iu1wxy", "IU1WXY", ((70, 80, 100), (130, 140, 160))),
    ("openx6x00", "OpenX6X00", ((0, 122, 204), (0, 190, 170))),
    ("r1cbu", "R1CBU", ((235, 110, 20), (250, 180, 40))),
    ("openx6100", "OpenX6100", ((120, 70, 220), (200, 90, 220))),
    ("xiegu", "XIEGU", ((190, 20, 30), (240, 70, 60))),
    ("wspr", "WSPR", ((30, 140, 60), (120, 200, 70))),
]


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:            # Pillow before 10.1: a small bitmap font
        return ImageFont.load_default()


def _family(name):
    n = name.lower().replace(" ", "")
    for key, label, colours in FAMILIES:
        if key in n:
            return label, colours
    h = hashlib.sha1(name.encode()).digest()
    c1 = (60 + h[0] % 140, 60 + h[1] % 140, 60 + h[2] % 140)
    c2 = tuple(min(255, v + 70) for v in c1)
    words = [w for w in name.replace("-", " ").split() if w]
    return (words[0] if words else name)[:9], (c1, c2)


def _fit_text(draw, text, max_w, start):
    size = start
    while size > 10:
        f = _font(size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return _font(10)


def default_logo(name, size=120, bg=None):
    """A rounded square in the family's colours with its name: no one's trademark copied"""
    label, (c1, c2) = _family(name)
    img = Image.new("RGB", (size, size), bg or TILE)
    grad = Image.new("RGB", (size, size))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / (size - 1)
        gd.line([(0, y), (size, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=size // 5, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    f = _fit_text(d, label, size - 16, size // 3)
    d.text((size / 2, size / 2), label, font=f, fill=(255, 255, 255), anchor="mm")
    return img


def _content_box(img, tol=24):
    """The part of a picture that is not its background (the colour of its corners)"""
    rgb = img.convert("RGB")
    w, h = rgb.size
    bg = rgb.getpixel((2, 2))
    diff = Image.new("L", (w, h))
    px, dp = rgb.load(), diff.load()
    for y in range(0, h):
        for x in range(0, w):
            r, g, b = px[x, y]
            if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) > tol:
                dp[x, y] = 255
    box = diff.getbbox()
    return box, bg


def load_logo(path, size=120, bg=None, width=None, crop=None):
    """A picture (a project's boot screen, a PNG/JPG of one's own) fitted into the logo box:
    cropped to what is not background, on a rounded card of its own background colour.
    crop: (left, top, right, bottom) as fractions, the part of the picture to start from."""
    width = width or size
    src = Image.open(path)
    src.load()
    if crop:
        w, h = src.size
        src = src.crop((int(crop[0] * w), int(crop[1] * h), int(crop[2] * w), int(crop[3] * h)))
    alpha = None
    if src.mode in ("RGBA", "LA") or (src.mode == "P" and "transparency" in src.info):
        alpha = src.convert("RGBA").getchannel("A")
        if alpha.getextrema()[0] == 255:          # an alpha channel that hides nothing
            alpha = None
    if alpha is not None:
        rgba = src.convert("RGBA")
        box = alpha.getbbox()
        card = (34, 38, 50)
    else:
        rgba = src.convert("RGBA")
        small = rgba.copy()
        small.thumbnail((400, 400))
        sbox, card = _content_box(small)
        k = rgba.width / small.width
        box = tuple(int(v * k) for v in sbox) if sbox else None
    if box:
        x0, y0, x1, y1 = box
        pad = int(max(x1 - x0, y1 - y0) * 0.06)
        rgba = rgba.crop((max(0, x0 - pad), max(0, y0 - pad), min(rgba.width, x1 + pad), min(rgba.height, y1 + pad)))
    out = Image.new("RGB", (width, size), bg or TILE)
    mask = Image.new("L", (width, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, width - 1, size - 1], radius=size // 6, fill=255)
    out.paste(Image.new("RGB", (width, size), card[:3]), (0, 0), mask)
    inner = rgba.copy()
    inner.thumbnail((width - 12, size - 12), Image.LANCZOS)
    out.paste(inner, ((width - inner.width) // 2, (size - inner.height) // 2), inner)
    return out


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:2]


def render_menu(entries, default, selected=None, title="X6100 MULTIBOOT"):
    """entries: [{"name", "logo": path or None}] in key order (F1 first). Landscape RGB image."""
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((16, 16), title, font=_font(24), fill=WHITE, anchor="lm")
    d.text((W - 16, 16), "F1-F%d" % max(1, len(entries)), font=_font(18), fill=GREY, anchor="rm")
    d.line([(0, 31), (W, 31)], fill=TILE_EDGE, width=1)
    # row 1 (32..63) is the countdown's: left black
    for i, e in enumerate(entries):
        cx = COL_W * i + COL_W // 2
        x0, x1 = cx - 72, cx + 72
        is_def = i == default
        is_sel = selected is not None and i == selected
        edge = GO if is_sel else (ACCENT if is_def and selected is None else TILE_EDGE)
        fill = (20, 48, 30) if is_sel else TILE
        d.rounded_rectangle([x0, 76, x1, 372], radius=14, fill=fill, outline=edge, width=4 if edge != TILE_EDGE else 2)
        logo = None
        if e.get("logo"):
            try:
                logo = load_logo(e["logo"], size=124, bg=fill, width=136, crop=e.get("crop"))
            except Exception:
                logo = None
        if logo is None:
            logo = default_logo(e["name"], size=124, bg=fill)
        img.paste(logo, (cx - logo.width // 2, 88))
        f = _font(19)
        for k, line in enumerate(_wrap(d, e["name"], f, 136)):
            d.text((cx, 240 + 26 * k), line, font=_fit_text(d, line, 136, 19), fill=WHITE, anchor="mm")
        if is_sel:
            d.text((cx, 340), "START", font=_font(18), fill=GO, anchor="mm")
        elif is_def and selected is None:
            d.text((cx, 340), "domyslny", font=_font(16), fill=ACCENT, anchor="mm")
        # the key, right above the radio's button
        kc = GO if is_sel else (ACCENT if is_def and selected is None else (60, 68, 88))
        d.rounded_rectangle([cx - 52, 404, cx + 52, 466], radius=10, fill=kc)
        d.text((cx, 435), "F%d" % (i + 1), font=_font(30), fill=(255, 255, 255), anchor="mm")
    return img


def to_framebuffer_bmp(img):
    """The landscape picture as the 480x800 BMP U-Boot draws into the portrait framebuffer.

    8 bits with a 256-colour palette: U-Boot draws that always, 24-bit only with
    CONFIG_BMP_24BPP. Black stays index 0's exact black (the countdown row's background)."""
    fb = img.transpose(Image.ROTATE_90).quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = fb.getpalette()[:255 * 3]
    out = Image.new("P", fb.size)
    out.putpalette([0, 0, 0] + pal)
    # shift indices by one so black is its own entry 0, then map pure-black pixels to it
    src = fb.load()
    rgb = img.transpose(Image.ROTATE_90).load()
    dst = out.load()
    for y in range(fb.size[1]):
        for x in range(fb.size[0]):
            dst[x, y] = 0 if rgb[x, y] == (0, 0, 0) else src[x, y] + 1
    buf = io.BytesIO()
    out.save(buf, "BMP")
    return buf.getvalue()
