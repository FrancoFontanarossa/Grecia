"""Genera los íconos de la PWA (180, 192 y 512 px) y el favicon desde el logo de Neuro (static/brand/neuro.png:
el símbolo blanco sobre el fondo azul, ya cuadrado y centrado).

Uso (una vez, en desarrollo; los PNG quedan en el repo y Railway no necesita Pillow):
    .venv\Scripts\python.exe app\web\make_icons.py
"""
from pathlib import Path

from PIL import Image

STATIC = Path(__file__).parent / "static"
LOGO = STATIC / "brand" / "neuro.png"
OUT = STATIC / "icons"


def main() -> None:
    logo = Image.open(LOGO).convert("RGB")
    side = min(logo.size)
    left, top = (logo.width - side) // 2, (logo.height - side) // 2
    logo = logo.crop((left, top, left + side, top + side))
    for size in (180, 192, 512):
        logo.resize((size, size), Image.LANCZOS).save(OUT / f"icon-{size}.png", optimize=True)
    logo.save(STATIC / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])


if __name__ == "__main__":
    main()
