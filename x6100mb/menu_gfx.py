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
# The screen: drawn at twice the size and scaled down (smooth corners and letters), on a dark
# blue background; tiles and keys with a soft shade, light from above, a glow round the chosen one
# ------------------------------------------------------------------------------------------
S = 2
BG_TOP, BG_BOTTOM = (16, 28, 56), (4, 7, 16)
TILE_TOP, TILE_BOTTOM = (40, 49, 72), (20, 25, 39)
KEY_GREY = ((84, 94, 120), (46, 53, 72))
KEY_BLUE = ((96, 190, 255), (30, 126, 214))
KEY_GREEN = ((92, 222, 124), (30, 158, 66))
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


def _panel(img, box, r, top, bottom, edge=None, edge_w=0, shine=True):
    """A rounded panel filled top to bottom, a lighter line along its upper edge, an outline"""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    img.paste(_vgrad(w, h, top, bottom), (x0, y0), _round_mask(w, h, r))
    d = ImageDraw.Draw(img)
    if shine:
        light = tuple(min(255, c + 38) for c in top)
        d.arc([x0, y0, x0 + 2 * r, y0 + 2 * r], 180, 270, fill=light, width=S)
        d.arc([x1 - 2 * r - 1, y0, x1 - 1, y0 + 2 * r], 270, 360, fill=light, width=S)
        d.line([(x0 + r, y0 + S // 2), (x1 - r, y0 + S // 2)], fill=light, width=S)
    if edge:
        d.rounded_rectangle([x0, y0, x1 - 1, y1 - 1], radius=r, outline=edge, width=edge_w)


def _key(entries, default, selected, title):
    return (tuple((e["name"], e.get("logo"), tuple(e.get("crop") or ())) for e in entries), default, selected,
            title, t("domyslny"))


def render_menu(entries, default, selected=None, title="X6100 MULTIBOOT"):
    """entries: [{"name", "logo": path or None}] in key order (F1 first). Landscape RGB image."""
    key = _key(entries, default, selected, title)
    if key in _cache:
        return _cache[key].copy()
    img = _vgrad(W * S, H * S, BG_TOP, BG_BOTTOM)
    d = ImageDraw.Draw(img)
    # the title bar, a blue line under it
    img.paste(_vgrad(W * S, 30 * S, (26, 44, 84), (14, 24, 48)), (0, 0))
    d.rectangle([0, 30 * S, W * S, 32 * S - 1], fill=ACCENT)
    d.text((16 * S, 15 * S), title, font=_font(22 * S), fill=WHITE, anchor="lm")
    if entries:
        d.text(((W - 16) * S, 15 * S), "F1-F%d" % len(entries), font=_font(17 * S), fill=(170, 190, 225), anchor="rm")
    for i, e in enumerate(entries):
        cx = COL_W * i + COL_W // 2
        is_def = i == default and selected is None
        is_sel = selected is not None and i == selected
        tone = GO if is_sel else ACCENT
        lit = is_sel or is_def
        box = ((cx - 72) * S, 76 * S, (cx + 72) * S, 372 * S)
        _soft(img, box, 16 * S, (0, 0, 0), 7 * S, 150, dy=5 * S)
        if lit:
            _soft(img, box, 16 * S, tone, 8 * S, 120)
        top, bottom = ((30, 74, 48), (14, 40, 26)) if is_sel else (TILE_TOP, TILE_BOTTOM)
        _panel(img, box, 16 * S, top, bottom, edge=tone if lit else (62, 72, 98), edge_w=(3 if lit else 1) * S)
        d = ImageDraw.Draw(img)
        logo = None
        if e.get("logo"):
            try:
                logo = load_logo(e["logo"], size=120 * S, bg=top, width=128 * S, crop=e.get("crop"))
            except Exception:
                logo = None
        if logo is None:
            logo = default_logo(e["name"], size=120 * S, bg=top)
        lx, ly = cx * S - logo.width // 2, 90 * S
        _soft(img, (lx, ly, lx + logo.width, ly + logo.height), 22 * S, (0, 0, 0), 4 * S, 110, dy=3 * S)
        img.paste(logo, (lx, ly), _round_mask(logo.width, logo.height, 22 * S))
        d = ImageDraw.Draw(img)
        f = _font(19 * S)
        for k, line in enumerate(_wrap(d, e["name"], f, 132 * S)):
            d.text((cx * S, (244 + 26 * k) * S), line, font=_fit_text(d, line, 132 * S, 19 * S), fill=WHITE, anchor="mm")
        if lit:                       # a small label: what the countdown will start, or what was chosen
            label = "START" if is_sel else t("domyslny")
            lf = _font(15 * S)
            lw = int(d.textlength(label, font=lf)) + 22 * S
            pill = (cx * S - lw // 2, 326 * S, cx * S + lw // 2, 354 * S)
            d.rounded_rectangle(pill, radius=14 * S, fill=tuple(c // 4 for c in tone), outline=tone, width=S)
            d.text((cx * S, 340 * S), label, font=lf, fill=tone, anchor="mm")
        # the key, right above the radio's button: raised, lit when it is the one
        ktop, kbottom = KEY_GREEN if is_sel else (KEY_BLUE if is_def else KEY_GREY)
        kbox = ((cx - 54) * S, 402 * S, (cx + 54) * S, 466 * S)
        _soft(img, kbox, 14 * S, (0, 0, 0), 5 * S, 170, dy=4 * S)
        if lit:
            _soft(img, kbox, 14 * S, tone, 6 * S, 90)
        _panel(img, kbox, 14 * S, ktop, kbottom, edge=tuple(c // 2 for c in kbottom), edge_w=S)
        d = ImageDraw.Draw(img)
        d.text((cx * S + S, 434 * S + S), "F%d" % (i + 1), font=_font(30 * S), fill=tuple(c // 3 for c in kbottom), anchor="mm")
        d.text((cx * S, 434 * S), "F%d" % (i + 1), font=_font(30 * S), fill=(255, 255, 255), anchor="mm")
    img = img.resize((W, H), Image.LANCZOS)
    # row 1 (32..63) is the countdown's: exactly black, U-Boot writes there over the picture
    ImageDraw.Draw(img).rectangle([0, TEXT_ROW_Y[0], W, TEXT_ROW_Y[1] - 1], fill=(0, 0, 0))
    if len(_cache) > 24:
        _cache.clear()
    _cache[key] = img
    return img.copy()


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
