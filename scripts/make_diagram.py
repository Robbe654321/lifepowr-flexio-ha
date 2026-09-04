#!/usr/bin/env python3
"""Generate the data-flow diagram in a light and a dark variant.

Both files share one geometry, so the README can swap them by colour scheme
with a <picture> element without anything shifting.
"""

from __future__ import annotations

from pathlib import Path

W, H = 940, 512

LIGHT = {
    "bg": "#ffffff",
    "panel": "#f6f8fa",
    "border": "#d1d9e0",
    "text": "#1f2328",
    "muted": "#59636e",
    "mono": "#0550ae",
    "accent": "#1a7f37",
    "write": "#9a6700",
    "arrow": "#8c959f",
}
DARK = {
    "bg": "#0d1117",
    "panel": "#161b22",
    "border": "#3d444d",
    "text": "#e6edf3",
    "muted": "#9198a1",
    "mono": "#79c0ff",
    "accent": "#3fb950",
    "write": "#d29922",
    "arrow": "#6e7681",
}

FONT = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
)
MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace"

COLUMNS = [
    {
        "x": 24,
        "w": 244,
        "title": "FlexiObox",
        "subtitle": "myio.local · local network only",
        "rows": [
            ("mono", "GET  /api/ems/measurements"),
            ("mono", "GET  /api/ems/generic-load"),
            ("mono", "GET  /api/info/version"),
            ("mono", "GET  /api/info/converter"),
            ("gap", ""),
            ("write", "POST /api/ems/generic-load"),
            ("muted", "the only writable value"),
        ],
    },
    {
        "x": 348,
        "w": 244,
        "title": "lifepowr",
        "subtitle": "the integration",
        "rows": [
            ("text", "Probes the layout once,"),
            ("text", "falls back to older paths"),
            ("gap", ""),
            ("text", "Maps 12 fields by alias,"),
            ("text", "spelling-insensitive"),
            ("gap", ""),
            ("accent", "Reports watts, not kW"),
            ("accent", "Flips grid + load sign"),
            ("gap", ""),
            ("muted", "polls every 15 s"),
        ],
    },
    {
        "x": 672,
        "w": 244,
        "title": "Home Assistant",
        "subtitle": "one device, real entities",
        "rows": [
            ("text", "12 sensors"),
            ("muted", "solar · load · grid · battery"),
            ("muted", "price · SoC · SoH · V · A"),
            ("gap", ""),
            ("text", "1 number"),
            ("muted", "generic load price cap"),
            ("gap", ""),
            ("muted", "missing fields make"),
            ("muted", "no entity at all"),
        ],
    },
]

BOX_Y, BOX_H = 92, 268
BAND_Y, BAND_H = 422, 66


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build(c: dict[str, str]) -> str:
    p: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" '
        f'aria-label="Data flow from the FlexiObox through the integration '
        f'into Home Assistant">',
        f'<rect width="{W}" height="{H}" fill="{c["bg"]}"/>',
        f'<text x="24" y="40" font-family="{FONT}" font-size="19" '
        f'font-weight="600" fill="{c["text"]}">How it fits together</text>',
        f'<text x="24" y="64" font-family="{FONT}" font-size="13" '
        f'fill="{c["muted"]}">Everything stays on your network. '
        f'No cloud, no account, no authentication.</text>',
    ]

    for col in COLUMNS:
        x, w = col["x"], col["w"]
        p.append(
            f'<rect x="{x}" y="{BOX_Y}" width="{w}" height="{BOX_H}" rx="10" '
            f'fill="{c["panel"]}" stroke="{c["border"]}"/>'
        )
        p.append(
            f'<text x="{x + 18}" y="{BOX_Y + 32}" font-family="{FONT}" '
            f'font-size="15" font-weight="600" fill="{c["text"]}">'
            f'{esc(col["title"])}</text>'
        )
        p.append(
            f'<text x="{x + 18}" y="{BOX_Y + 52}" font-family="{FONT}" '
            f'font-size="11.5" fill="{c["muted"]}">'
            f'{esc(col["subtitle"])}</text>'
        )
        p.append(
            f'<line x1="{x + 18}" y1="{BOX_Y + 66}" x2="{x + w - 18}" '
            f'y2="{BOX_Y + 66}" stroke="{c["border"]}"/>'
        )

        y = BOX_Y + 90
        for kind, label in col["rows"]:
            if kind == "gap":
                y += 10
                continue
            font = MONO if kind in ("mono", "write") else FONT
            size = 11 if kind in ("mono", "write") else 12.5
            fill = {
                "mono": c["mono"],
                "write": c["write"],
                "muted": c["muted"],
                "accent": c["accent"],
                "text": c["text"],
            }[kind]
            weight = "600" if kind == "accent" else "400"
            p.append(
                f'<text x="{x + 18}" y="{y}" font-family="{font}" '
                f'font-size="{size}" font-weight="{weight}" fill="{fill}">'
                f'{esc(label)}</text>'
            )
            y += 20

    # Arrows between the columns.
    for x1, x2 in ((268, 348), (592, 672)):
        mid = BOX_Y + BOX_H / 2
        p.append(
            f'<path d="M{x1 + 8} {mid} H{x2 - 16}" stroke="{c["arrow"]}" '
            f'stroke-width="1.5" fill="none" marker-end="url(#a)"/>'
        )

    # Return path for the one write.
    p.append(
        f'<path d="M{672 + 122} {BOX_Y + BOX_H - 6} V{BOX_Y + BOX_H + 22} '
        f'H{24 + 122} V{BOX_Y + BOX_H + 6}" stroke="{c["write"]}" '
        f'stroke-width="1.5" stroke-dasharray="4 4" fill="none" '
        f'marker-end="url(#w)"/>'
    )
    p.append(
        f'<text x="{W / 2}" y="{BOX_Y + BOX_H + 40}" text-anchor="middle" '
        f'font-family="{FONT}" font-size="11.5" fill="{c["write"]}">'
        f'setting the price cap posts straight back to the box</text>'
    )

    # Bottom band: the energy package.
    p.append(
        f'<rect x="24" y="{BAND_Y}" width="{W - 48}" height="{BAND_H}" rx="10" '
        f'fill="{c["panel"]}" stroke="{c["border"]}" stroke-dasharray="5 4"/>'
    )
    p.append(
        f'<text x="44" y="{BAND_Y + 27}" font-family="{FONT}" font-size="13" '
        f'font-weight="600" fill="{c["text"]}">Optional: '
        f'<tspan font-family="{MONO}" font-size="11.5" fill="{c["mono"]}">'
        f'packages/lifepowr_energy.yaml</tspan></text>'
    )
    p.append(
        f'<text x="44" y="{BAND_Y + 48}" font-family="{FONT}" font-size="12" '
        f'fill="{c["muted"]}">Splits grid and battery into directions and '
        f'integrates watts into kWh — six totals the Energy dashboard '
        f'accepts directly.</text>'
    )

    p.append(
        f'<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0 0 L10 5 L0 10 z" fill="{c["arrow"]}"/></marker>'
        f'<marker id="w" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0 0 L10 5 L0 10 z" fill="{c["write"]}"/></marker></defs>'
    )
    p.append("</svg>")
    return "\n".join(p)


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "docs"
    out.mkdir(exist_ok=True)
    (out / "architecture-light.svg").write_text(build(LIGHT))
    (out / "architecture-dark.svg").write_text(build(DARK))
    print(f"wrote {out}/architecture-{{light,dark}}.svg")


if __name__ == "__main__":
    main()
