"""
generate_widget_assets.py — Generates pixel-perfect background assets matching
the Time Tracker AI 2 Dashboard Focus Widget (forest artwork, atmospheric lighting,
soft glows, and illuminated cyan-to-purple gradient border).
"""

from pathlib import Path
from PIL import Image, ImageDraw

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def generate_widget_background(width: int, height: int, corner_radius: int = 20, is_compact: bool = False) -> Image.Image:
    SCALE = 2
    SW, SH = width * SCALE, height * SCALE
    R = corner_radius * SCALE

    # 1. Base surface: Deep Midnight Navy (#0F1420)
    img = Image.new("RGBA", (SW, SH), (15, 20, 32, 255))
    draw = ImageDraw.Draw(img)

    # 2. Atmospheric radial glows (blended softly via alpha composite matching web CSS)
    glow_layer = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow_layer)

    # Top-right violet nebula glow (matching dashboard index.css: 85% 25%, rgba(99, 102, 241, 0.22))
    vcx, vcy = int(SW * 0.85), int(SH * 0.25)
    vr = int(SW * 0.45)
    for r in range(vr, 0, -4):
        f = 1.0 - (r / vr)
        gdraw.ellipse([vcx - r, vcy - r, vcx + r, vcy + r], fill=(99, 102, 241, int(f * f * 42)))

    # Top-left cyan ambient glow (matching dashboard index.css: 15% 15%, rgba(22, 213, 226, 0.10))
    ccx, ccy = int(SW * 0.15), int(SH * 0.18)
    cr = int(SW * 0.35)
    for r in range(cr, 0, -4):
        f = 1.0 - (r / cr)
        gdraw.ellipse([ccx - r, ccy - r, ccx + r, ccy + r], fill=(22, 213, 226, int(f * f * 22)))

    # Soft glowing purple depth halo behind the circular play/pause button
    if not is_compact:
        bcx, bcy = int(420 * SCALE), int(75 * SCALE)
        br = int(48 * SCALE)
        for r in range(br, 0, -2):
            f = 1.0 - (r / br)
            gdraw.ellipse([bcx - r, bcy - r, bcx + r, bcy + r], fill=(93, 107, 255, int(f * f * 68)))
    else:
        bcx, bcy = int(405 * SCALE), int(34 * SCALE)
        br = int(30 * SCALE)
        for r in range(br, 0, -2):
            f = 1.0 - (r / br)
            gdraw.ellipse([bcx - r, bcy - r, bcx + r, bcy + r], fill=(93, 107, 255, int(f * f * 58)))

    img = Image.alpha_composite(img, glow_layer)

    # 3. Forest artwork layer (matching forest-artwork.svg bottom right / 360px with opacity 0.34)
    forest_w = 360
    forest_h = int(800 * (forest_w / 900))
    offset_x = width - forest_w
    offset_y = height - forest_h
    scale = forest_w / 900.0

    forest = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(forest)

    def tx(x): return (offset_x + x * scale) * SCALE
    def ty(y): return (offset_y + y * scale) * SCALE

    # Distant high mountain peaks (#1C1035)
    peaks = [
        (-50, 470), (30, 370), (110, 420), (180, 340), (260, 405), (350, 320),
        (450, 420), (560, 360), (680, 450), (950, 400), (950, 800), (-50, 800)
    ]
    fdraw.polygon([(tx(x), ty(y)) for x, y in peaks], fill=(28, 16, 53, 240))

    # Mid-distance mountain slopes (#120A24)
    slopes = [
        (-50, 520), (50, 450), (140, 490), (210, 430), (310, 495), (400, 440),
        (500, 510), (610, 460), (750, 530), (950, 480), (950, 800), (-50, 800)
    ]
    fdraw.polygon([(tx(x), ty(y)) for x, y in slopes], fill=(18, 10, 36, 245))

    # Atmospheric mist valleys
    fdraw.ellipse([tx(180 - 260), ty(495 - 45), tx(180 + 260), ty(495 + 45)], fill=(59, 7, 100, 115))
    fdraw.ellipse([tx(90 - 190), ty(550 - 40), tx(90 + 190), ty(550 + 40)], fill=(46, 16, 101, 125))

    def draw_pine(cx, cy, s, color):
        levels = [
            (-230, -212, 10), (-216, -195, 16), (-198, -172, 22),
            (-175, -144, 28), (-147, -110, 35), (-113, -70, 42), (-74, -24, 50)
        ]
        for top_y, bot_y, hw in levels:
            p = [
                (tx(cx), ty(cy + top_y * s)),
                (tx(cx - hw * s), ty(cy + bot_y * s)),
                (tx(cx + hw * s), ty(cy + bot_y * s)),
            ]
            fdraw.polygon(p, fill=color)

    # Distant Ridge Trees (Y=520 in SVG)
    for x, s in [(15, 0.85), (40, 0.9), (65, 0.8), (90, 0.95), (120, 0.85), (150, 1.0),
                 (180, 0.8), (210, 0.9), (245, 0.85), (280, 1.0), (320, 0.8), (360, 0.9),
                 (410, 0.85), (460, 0.95), (520, 0.8)]:
        draw_pine(x, 520, s * 0.45, (19, 16, 42, 240))

    # Midground Pine Trees (Y=590 in SVG)
    for x, s in [(20, 1.1), (55, 1.25), (95, 1.05), (135, 1.3), (180, 1.15), (225, 1.2),
                 (270, 1.05), (320, 1.15), (375, 1.0), (430, 1.1)]:
        draw_pine(x, 590, s * 0.65, (10, 14, 24, 250))

    # Foreground Sharp Dark Pine Silhouettes (Y=740 in SVG)
    for x, s in [(15, 1.5), (50, 1.35), (85, 1.65), (130, 1.4), (170, 1.55), (215, 1.3),
                 (260, 1.45), (310, 1.25), (365, 1.35), (425, 1.15), (485, 1.25)]:
        draw_pine(x, 740, s * 0.9, (5, 8, 15, 255))

    # Dark ground base
    fdraw.rectangle([tx(0), ty(720), tx(900), ty(800)], fill=(4, 6, 12, 255))

    # Apply 0.34 opacity to the entire forest artwork layer
    r_ch, g_ch, b_ch, a_ch = forest.split()
    a_ch = a_ch.point(lambda p: int(p * 0.34))
    forest.putalpha(a_ch)
    img = Image.alpha_composite(img, forest)

    # 4. Rounded mask for card surface
    card_mask = Image.new("L", (SW, SH), 0)
    m_draw = ImageDraw.Draw(card_mask)
    m_draw.rounded_rectangle([0, 0, SW - 1, SH - 1], radius=R, fill=255)
    img.putalpha(card_mask)

    # 5. Illuminated Gradient Border (1.5px stroke at 1x = 3px stroke at 2x)
    # Generate 135-degree continuous diagonal gradient field
    grad_img = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(grad_img)
    total_diag = SW + SH
    for d in range(0, total_diag + 2, 2):
        proj = d / float(total_diag)
        if proj <= 0.45:
            f = proj / 0.45
            r = int(0 + 59 * f)
            g = int(245 + (130 - 245) * f)
            b = int(255 + (246 - 255) * f)
            a = int(245 + (200 - 245) * f)
        else:
            f = (proj - 0.45) / 0.55
            r = int(59 + (139 - 59) * f)
            g = int(130 + (92 - 130) * f)
            b = int(246 + (246 - 246) * f)
            a = int(200 + (245 - 200) * f)
        col = (r, g, b, a)
        gdraw.line([(d, 0), (0, d)], fill=col, width=3)

    stroke_w = int(1.5 * SCALE)
    inset = stroke_w // 2

    # Draw border mask with rounded corners
    border_mask = Image.new("L", (SW, SH), 0)
    bdraw = ImageDraw.Draw(border_mask)
    bdraw.rounded_rectangle(
        [inset, inset, SW - 1 - inset, SH - 1 - inset],
        radius=R - inset,
        outline=255,
        width=stroke_w,
    )

    border_layer = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    border_layer.paste(grad_img, (0, 0), mask=border_mask)

    img = Image.alpha_composite(img, border_layer)
    return img.resize((width, height), Image.Resampling.LANCZOS)


def ensure_widget_assets(force: bool = False):
    """Ensure both expanded and compact background assets exist on disk."""
    exp_path = ASSETS_DIR / "widget_bg_expanded.png"
    comp_path = ASSETS_DIR / "widget_bg_compact.png"

    if force or not exp_path.exists() or exp_path.stat().st_size < 1000:
        exp = generate_widget_background(520, 190, corner_radius=20, is_compact=False)
        exp.save(exp_path)

    if force or not comp_path.exists() or comp_path.stat().st_size < 1000:
        comp = generate_widget_background(520, 68, corner_radius=18, is_compact=True)
        comp.save(comp_path)


if __name__ == "__main__":
    ensure_widget_assets(force=True)
    print("Widget background assets generated successfully!")
