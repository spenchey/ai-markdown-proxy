#!/usr/bin/env python3
"""Generate the store-specific 512x512 icons used by Google Connected Apps."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

STORES = {
    "motorinnautogroup": "Auto Group",
    "motorinnchevy": "Of Carroll",
    "motorinntoyota": "Toyota Of Carroll",
}


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def render(store_name: str, path: Path) -> None:
    image = Image.new("RGB", (512, 512), "#0B1F3A")
    draw = ImageDraw.Draw(image)
    draw.text((256, 230), "MI", font=font(170), anchor="mm", fill="#FFFFFF")
    draw.text((256, 434), store_name, font=font(44), anchor="mm", fill="#C9D6E3")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)


def main() -> None:
    for key, store_name in STORES.items():
        render(store_name, ASSETS / key / "icon-512.png")


if __name__ == "__main__":
    main()
