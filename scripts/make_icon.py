#!/usr/bin/env python3
"""Generate the Home Assistant brand icons.

Requires Pillow. The mark is a battery with a lightning bolt knocked out of
it, drawn so it survives the 24 px at which Home Assistant renders it in the
integrations list — an outlined battery with a bolt inside turns to mush at
that size, a filled one does not.

See custom_components/lifepowr/brand/README.md for how these reach
Home Assistant.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

BACKGROUND = (28, 36, 45, 255)
BATTERY = (122, 214, 122, 255)

#: Supersampling factor. Pillow has no anti-aliased polygon fill, so
#: everything is drawn large and resampled down.
SCALE = 4


def _bolt(
    cx: float, cy: float, height: float, width: float
) -> list[tuple[float, float]]:
    """Return the polygon for a chunky lightning bolt centred on (cx, cy)."""
    return [
        (cx + width * 0.30, cy - height * 0.50),
        (cx - width * 0.50, cy + height * 0.08),
        (cx - width * 0.04, cy + height * 0.08),
        (cx - width * 0.30, cy + height * 0.50),
        (cx + width * 0.50, cy - height * 0.08),
        (cx + width * 0.04, cy - height * 0.08),
    ]


def icon(size: int) -> Image.Image:
    """Draw the icon at the given edge length."""
    s = size * SCALE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=BACKGROUND)

    body_w, body_h = int(s * 0.48), int(s * 0.58)
    body_x, body_y = (s - body_w) // 2, int(s * 0.25)
    draw.rounded_rectangle(
        [body_x, body_y, body_x + body_w, body_y + body_h],
        radius=int(s * 0.06),
        fill=BATTERY,
    )

    terminal_w, terminal_h = int(body_w * 0.42), int(s * 0.055)
    draw.rounded_rectangle(
        [
            (s - terminal_w) // 2,
            body_y - terminal_h - int(s * 0.025),
            (s + terminal_w) // 2,
            body_y - int(s * 0.025),
        ],
        radius=int(terminal_h * 0.45),
        fill=BATTERY,
    )

    draw.polygon(
        _bolt(s / 2, body_y + body_h / 2, body_h * 0.66, body_w * 0.50),
        fill=BACKGROUND,
    )

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    """Write both icon sizes into the integration's brand directory."""
    # The HACS action looks for these at custom_components/<domain>/brand/,
    # not at the repository root.
    out = Path(__file__).resolve().parent.parent / "custom_components/lifepowr/brand"
    out.mkdir(exist_ok=True)
    for size, name in ((256, "icon.png"), (512, "icon@2x.png")):
        image = icon(size)
        # home-assistant/brands rejects images with empty edges.
        if image.getbbox() != (0, 0, size, size):
            raise SystemExit(f"{name} is not trimmed to its content")
        image.save(out / name, optimize=True)
        print(f"wrote {out / name} ({size}x{size})")


if __name__ == "__main__":
    main()
