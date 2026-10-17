"""Genera los íconos de la PWA (180, 192 y 512 px): cuadrado redondeado pino con la casa de trazo blanco.

Uso (una vez, en desarrollo; los PNG quedan en el repo y Railway no necesita Pillow):
    .venv\\Scripts\\python.exe app\\web\\make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

PINO = (0x1E, 0x5B, 0x4F, 255)
BLANCO = (255, 255, 255, 255)
OUT = Path(__file__).parent / "static" / "icons"

# Logo de design/screens/Selector.html, en el viewBox 24x24 de lucide:
#   M3 11l9-7 9 7 · M5.5 9.5V20h13V9.5 · M9.5 20v-5a2.5 2.5 0 0 1 5 0v5
ROOF = [(3, 11), (12, 4), (21, 11)]
WALLS = [(5.5, 9.5), (5.5, 20), (18.5, 20), (18.5, 9.5)]


def door(steps: int = 24):
    import math

    pts = [(9.5, 20), (9.5, 15)]
    for i in range(steps + 1):  # arco de 180° con centro (12, 15) y radio 2,5
        a = math.pi - math.pi * i / steps
        pts.append((12 + 2.5 * math.cos(a), 15 - 2.5 * math.sin(a)))
    pts.append((14.5, 20))
    return pts


def draw_icon(size: int, full_bleed: bool) -> Image.Image:
    scale = 4  # supermuestreo para bordes suaves
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if full_bleed:
        d.rectangle([0, 0, s, s], fill=PINO)  # iOS redondea solo; el 512 sirve también como maskable
    else:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=PINO)
    # La casa ocupa ~56% del ícono (zona segura de maskable).
    box = s * 0.56
    off = (s - box) / 2
    u = box / 24
    width = max(2, int(2 * u))

    def tr(pts):
        return [(off + x * u, off + y * u) for x, y in pts]

    for path in (ROOF, WALLS, door()):
        pts = tr(path)
        d.line(pts, fill=BLANCO, width=width, joint="curve")
        r = width / 2
        for x, y in (pts[0], pts[-1]):  # puntas redondeadas
            d.ellipse([x - r, y - r, x + r, y + r], fill=BLANCO)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw_icon(180, full_bleed=True).save(OUT / "icon-180.png")
    draw_icon(192, full_bleed=False).save(OUT / "icon-192.png")
    draw_icon(512, full_bleed=True).save(OUT / "icon-512.png")
    print("Íconos en", OUT)


if __name__ == "__main__":
    main()
