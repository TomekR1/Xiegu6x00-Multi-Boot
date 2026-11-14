"""The menu screen as a picture: a tile with a logo per system, above its F1..F5 key.

Drawn landscape (800x480, as the radio is held), then turned into the panel's own portrait
framebuffer layout: U-Boot's `bmp display` draws unrotated, while its console is rotated
(CONFIG_VIDEO_SUNXI_ROTATION=3: landscape (x, y) is framebuffer (y, 799 - x)).

Text row 1 (pixels 32..63) stays black: U-Boot writes the countdown there over the picture.
Needs Pillow; without it the menu is text only (compose.py).
"""
import hashlib
import io
from .i18n import t

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
    ("doom", "DOOM", ((90, 0, 0), (200, 30, 20))),
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


# ------------------------------------------------------------------------------------------
# The screen, in the manner of the classic console role-playing games' menus: blue windows
# shaded top to bottom inside a light frame, on a near-black background; a pointer over the
# default system's key. Drawn at twice the size and scaled down (smooth corners and letters).
# Between the tiles and the keys runs a rail: the only part that moves on the radio (a light
# travelling along it, the pointer bobbing), as small pictures U-Boot draws over the rail.
# ------------------------------------------------------------------------------------------
S = 2
BG_TOP, BG_BOTTOM = (8, 10, 34), (0, 0, 8)
WIN = ((62, 92, 222), (10, 16, 86))            # a window, top to bottom
WIN_LIT = ((96, 138, 255), (20, 38, 150))      # the default system's
WIN_GO = ((40, 150, 96), (8, 60, 40))          # the chosen one's: green
KEY_GO = ((72, 214, 110), (22, 140, 60))
FRAME, FRAME_DIM, FRAME_GO = (238, 241, 250), (150, 160, 200), (110, 235, 140)
GLOW, GOLD = (110, 170, 255), (255, 214, 90)
RAIL_Y = (376, 400)          # landscape rows of the rail; the animation's strip is exactly these
FRAMES = 16
_cache = {}


def _vgrad(w, h, top, bottom):
    col = Image.new("RGB", (1, h))
    px = col.load()
    for y in range(h):
        k = y / max(h - 1, 1)
        px[0, y] = tuple(int(a + (b - a) * k) for a, b in zip(top, bottom))
    return col.resize((w, h))


def _round_mask(w, h, r):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
    return m


def _soft(img, box, r, colour, blur, strength, dy=0):
    """A blurred rounded shape of a colour under what comes next: a shade (black) or a glow"""
    from PIL import ImageFilter
    x0, y0, x1, y1 = box
    pad = blur * 3
    w, h = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([pad, pad, w - pad - 1, h - pad - 1], radius=r, fill=strength)
    m = m.filter(ImageFilter.GaussianBlur(blur))
    img.paste(Image.new("RGB", (w, h), colour), (x0 - pad, y0 - pad + dy), m)


def _window(img, box, r, fill, frame, alpha=150, frame_w=2):
    """A window of tinted glass: the background shows through its blue (lighter at the top), a
    sheen over its upper part, a light rim"""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    under = img.crop(box).convert("RGBA")
    mask = _round_mask(w, h, r)
    tint = _vgrad(w, h, fill[0], fill[1]).convert("RGBA")
    tint.putalpha(mask.point(lambda v: v * alpha // 255))
    under = Image.alpha_composite(under, tint)
    sheen = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    fade = Image.new("L", (1, h), 0)
    fp = fade.load()
    for y in range(h // 2):
        fp[0, y] = int(46 * (1 - y / (h / 2)) ** 2)
    sheen.putalpha(Image.composite(fade.resize((w, h)), Image.new("L", (w, h), 0), mask))
    under = Image.alpha_composite(under, sheen)
    rim = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(rim).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, outline=frame + (235,), width=frame_w * S)
    under = Image.alpha_composite(under, rim)
    img.paste(under.convert("RGB"), (x0, y0), mask)


def _backdrop():
    """The background the glass lies on: night blue with soft lights in it (drawn small and
    blurred, then enlarged: smooth and quick)"""
    from PIL import ImageFilter
    w, h = W // 4, H // 4
    small = _vgrad(w, h, (10, 16, 52), (2, 3, 16))
    d = ImageDraw.Draw(small)
    for (cx, cy, rx, ry, colour) in ((0.16, 0.42, 0.24, 0.30, (36, 86, 230)), (0.56, 0.62, 0.26, 0.26, (110, 52, 200)),
                                     (0.90, 0.36, 0.20, 0.30, (0, 132, 190)), (0.38, 0.95, 0.30, 0.16, (30, 60, 190))):
        d.ellipse([(cx - rx) * w, (cy - ry) * h, (cx + rx) * w, (cy + ry) * h], fill=colour)
    small = small.filter(ImageFilter.GaussianBlur(14))
    small = Image.blend(small, _vgrad(w, h, (10, 16, 52), (2, 3, 16)), 0.35)
    return small.resize((W * S, H * S), Image.BICUBIC)


def _pointer(size, colour=(255, 255, 255)):
    """The pointer: a triangle pointing down, dark edged (RGBA, size wide)"""
    k = 4
    im = Image.new("RGBA", (size * k, size * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    w = size * k
    d.polygon([(w * 0.08, w * 0.12), (w * 0.92, w * 0.12), (w * 0.5, w * 0.95)], fill=(10, 14, 50, 255))
    d.polygon([(w * 0.22, w * 0.2), (w * 0.78, w * 0.2), (w * 0.5, w * 0.78)], fill=colour + (255,))
    return im.resize((size, size), Image.LANCZOS)


def _rail(img, default_cx, frame=None):
    """The rail between tiles and keys drawn into img (landscape, full size): a dark band with a
    line through it; frame None: at rest; else the light at its place and the pointer's bob"""
    import math
    y0, y1 = RAIL_Y
    d = ImageDraw.Draw(img)
    d.rectangle([0, y0, W, y1 - 1], fill=(3, 5, 22))
    mid = (y0 + y1) // 2
    d.rounded_rectangle([14, mid - 2, W - 15, mid + 2], radius=2, fill=(16, 24, 70))
    d.line([(16, mid), (W - 17, mid)], fill=(52, 70, 150), width=1)
    px = img.load()
    if frame is not None:                     # the light: bright in the middle, fading both ways
        cx = int((frame + 0.5) * W / FRAMES)
        for dx in range(-90, 91):
            x = (cx + dx) % W
            k = (1 - abs(dx) / 90) ** 2
            for dy, weight in ((-1, 0.35), (0, 1.0), (1, 0.35)):
                r, g, b = px[x, mid + dy]
                kk = k * weight
                px[x, mid + dy] = (int(r + (150 - r) * kk), int(g + (200 - g) * kk), int(b + (255 - b) * kk))
    if default_cx is not None:
        bob = 0 if frame is None else int(round(2 + 2 * math.sin(2 * math.pi * frame / FRAMES)))
        size = y1 - y0 - 6
        p = _pointer(size)
        img.paste(p, (default_cx - size // 2, y0 + 1 + bob), p)


def _key(entries, default, selected, title):
    return (tuple((e["name"], e.get("logo"), tuple(e.get("crop") or ())) for e in entries), default, selected,
            title, t("domyslny"))


def render_menu(entries, default, selected=None, title="X6100 MULTIBOOT"):
    """entries: [{"name", "logo": path or None}] in key order (F1 first). Landscape RGB image."""
    key = _key(entries, default, selected, title)
    if key in _cache:
        return _cache[key].copy()
    img = _backdrop()
    d = ImageDraw.Draw(img)
    # the title: a window's blue across the top, the light frame's line under it
    img.paste(_vgrad(W * S, 30 * S, WIN[0], (16, 26, 110)), (0, 0))
    d.rectangle([0, 30 * S, W * S, 32 * S - 1], fill=(120, 150, 240))
    d.text((16 * S + S, 15 * S + S), title, font=_font(22 * S), fill=(8, 10, 50), anchor="lm")
    d.text((16 * S, 15 * S), title, font=_font(22 * S), fill=WHITE, anchor="lm")
    if entries:
        d.text(((W - 16) * S, 15 * S), "F1-F%d" % len(entries), font=_font(17 * S), fill=(200, 212, 245), anchor="rm")
    for i, e in enumerate(entries):
        cx = COL_W * i + COL_W // 2
        is_def = i == default and selected is None
        is_sel = selected is not None and i == selected
        lit = is_sel or is_def
        fill = WIN_GO if is_sel else (WIN_LIT if is_def else WIN)
        frame = FRAME_GO if is_sel else (FRAME if is_def else FRAME_DIM)
        glow = GO if is_sel else GLOW
        logo = None
        if e.get("logo"):
            try:
                logo = load_logo(e["logo"], size=124 * S, bg=fill[0], width=124 * S, crop=e.get("crop"))
            except Exception:
                logo = None
        if logo is None:
            logo = default_logo(e["name"], size=124 * S, bg=fill[0])
        # the system's own colour (its logo's) lights its tile from inside, under the logo
        own = logo.resize((1, 1), Image.BOX).getpixel((0, 0))
        own = tuple(min(255, int(c * 1.25) + 20) for c in own)
        box = ((cx - 73) * S, 72 * S, (cx + 73) * S, 368 * S)
        _soft(img, box, 26 * S, (0, 0, 0), 6 * S, 150, dy=4 * S)
        if lit:
            _soft(img, box, 26 * S, glow, 7 * S, 160)
        _window(img, box, 26 * S, fill, frame, alpha=175 if lit else 135, frame_w=3 if lit else 2)
        lx, ly = cx * S - logo.width // 2, 84 * S
        _soft(img, (lx, ly + 20 * S, lx + logo.width, ly + logo.height + 6 * S), 30 * S, own, 9 * S, 150)
        _soft(img, (lx, ly, lx + logo.width, ly + logo.height), 30 * S, (0, 0, 20), 3 * S, 120, dy=3 * S)
        img.paste(logo, (lx, ly), _round_mask(logo.width, logo.height, 30 * S))
        # a light rim round the logo: a button of its own on the glass
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([lx, ly, lx + logo.width - 1, ly + logo.height - 1], radius=30 * S,
                            outline=tuple(min(255, c + 60) for c in own), width=S)
        # the name on a darker plate across the tile's lower part
        plate = ((cx - 64) * S, 226 * S, (cx + 64) * S, (300 if lit else 304) * S)
        _window(img, plate, 16 * S, ((8, 12, 48), (4, 6, 30)), tuple(c // 2 + 40 for c in own), alpha=150, frame_w=1)
        d = ImageDraw.Draw(img)
        f = _font(19 * S)
        lines = _wrap(d, e["name"], f, 118 * S)
        mid = (plate[1] + plate[3]) // 2
        for k, line in enumerate(lines):
            lf = _fit_text(d, line, 118 * S, 19 * S)
            y = mid + int((k - (len(lines) - 1) / 2) * 25 * S)
            d.text((cx * S + S, y + S), line, font=lf, fill=(0, 0, 20), anchor="mm")
            d.text((cx * S, y), line, font=lf, fill=WHITE, anchor="mm")
        if lit:                       # what the countdown will start, or what was chosen: a badge
            label = "START" if is_sel else t("domyslny")
            lf = _font(16 * S)
            lw = int(d.textlength(label, font=lf)) + 26 * S
            pill = (cx * S - lw // 2, 318 * S, cx * S + lw // 2, 352 * S)
            tone = GO if is_sel else (150, 200, 255)
            _window(img, pill, 17 * S, (tuple(c // 3 for c in tone), tuple(c // 5 for c in tone)), tone, alpha=220, frame_w=1)
            d = ImageDraw.Draw(img)
            d.text((cx * S, 335 * S), label, font=lf, fill=tone if not is_sel else (210, 255, 220), anchor="mm")
        # the key, right above the radio's button: a pill of glass, green when it is the one chosen
        kbox = ((cx - 54) * S, 406 * S, (cx + 54) * S, 468 * S)
        _soft(img, kbox, 30 * S, (0, 0, 0), 4 * S, 170, dy=3 * S)
        if lit:
            _soft(img, kbox, 30 * S, glow, 5 * S, 150)
        kfill = KEY_GO if is_sel else fill
        _window(img, kbox, 30 * S, kfill, frame, alpha=225 if lit else 175)
        d = ImageDraw.Draw(img)
        d.text((cx * S + 2 * S, 436 * S + 2 * S), "F%d" % (i + 1), font=_font(30 * S), fill=(4, 8, 30), anchor="mm")
        d.text((cx * S, 436 * S), "F%d" % (i + 1), font=_font(30 * S), fill=WHITE, anchor="mm")
    img = img.resize((W, H), Image.LANCZOS)
    # row 1 (32..63) is the countdown's: exactly black, U-Boot writes there over the picture
    ImageDraw.Draw(img).rectangle([0, TEXT_ROW_Y[0], W, TEXT_ROW_Y[1] - 1], fill=(0, 0, 0))
    mark = selected if selected is not None else default
    _rail(img, COL_W * mark + COL_W // 2 if entries and mark is not None else None)
    if len(_cache) > 24:
        _cache.clear()
    _cache[key] = img
    return img.copy()


def rail_frames(entries, default):
    """The rail's FRAMES pictures (landscape strips W wide, RAIL_Y high): the light moving along,
    the pointer over the default system's key bobbing. Drawn over the menu at rows RAIL_Y."""
    cx = COL_W * default + COL_W // 2 if entries and default is not None else None
    out = []
    for k in range(FRAMES):
        strip = Image.new("RGB", (W, H))
        _rail(strip, cx, frame=k)
        out.append(strip.crop((0, RAIL_Y[0], W, RAIL_Y[1])))
    return out


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
