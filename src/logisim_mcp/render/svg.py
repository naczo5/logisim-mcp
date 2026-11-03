"""SVG rendering backend for the circuit scene.

Emits a self-contained SVG string; shapes are drawn with raw attributes
(no CSS), so any viewer — including ones that ignore stylesheets — shows
the same picture. Text uses a generic monospace family and always keeps
the size used for layout math, so labels do not overflow their bounds.
"""

from __future__ import annotations

from .canvas import Scene, cap_height


def _hex(color: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


def _num(v: float) -> str:
    r = round(v, 2)
    if isinstance(r, float) and r.is_integer():
        return str(int(r))
    return str(r)


def _fmt_points(points) -> str:
    return " ".join(f"{_num(x)},{_num(y)}" for x, y in points)


def scene_to_svg(scene: Scene, pad: int = 34, *, title: str | None = None) -> str:
    """Return an SVG document for ``scene``, plus padding on every side."""
    w = scene.width(pad)
    h = scene.height(pad)
    ox = int(scene.min_x) - pad
    oy = int(scene.min_y) - pad
    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{ox} {oy} {w} {h}" '
        f'width="{w}" height="{h}" font-family="\'DejaVu Sans Mono\', Menlo, '
        f'Consolas, monospace">'
    )
    if title:
        # XML comments cannot contain '--'; keep the title well-formed for
        # any filename or circuit name a project uses.
        safe_title = title.replace("--", "-")
        parts.append(f"<!-- {safe_title} -->")
    parts.append(f'<rect x="{ox}" y="{oy}" width="{w}" height="{h}" fill="#ffffff"/>')
    for cmd in scene.commands:
        kind = cmd[0]
        if kind == "line":
            _, x0, y0, x1, y1, color, width = cmd
            parts.append(
                f'<line x1="{_num(x0)}" y1="{_num(y0)}" x2="{_num(x1)}" y2="{_num(y1)}" '
                f'stroke="{_hex(color)}" stroke-width="{_num(width)}"/>'
            )
        elif kind == "rect":
            _, x, y, w_, h_, stroke, fill, width = cmd
            attrs = f'x="{_num(x)}" y="{_num(y)}" width="{_num(w_)}" height="{_num(h_)}"'
            if fill is not None:
                attrs += f' fill="{_hex(fill)}"'
            if stroke is not None:
                attrs += f' stroke="{_hex(stroke)}" stroke-width="{_num(width)}"'
            parts.append(f"<rect {attrs}/>")
        elif kind == "circle":
            _, cx, cy, r, stroke, fill, width = cmd
            attrs = f'cx="{_num(cx)}" cy="{_num(cy)}" r="{_num(r)}"'
            if fill is not None:
                attrs += f' fill="{_hex(fill)}"'
            else:
                attrs += ' fill="none"'
            if stroke is not None:
                attrs += f' stroke="{_hex(stroke)}" stroke-width="{_num(width)}"'
            parts.append(f"<circle {attrs}/>")
        elif kind == "polyline":
            _, pts, color, width = cmd
            parts.append(
                f'<polyline points="{_fmt_points(pts)}" fill="none" '
                f'stroke="{_hex(color)}" stroke-width="{_num(width)}"/>'
            )
        elif kind == "poly":
            _, pts, stroke, fill, width = cmd
            attrs = f'points="{_fmt_points(pts)}"'
            attrs += f' fill="{_hex(fill)}"' if fill is not None else ' fill="none"'
            if stroke is not None:
                attrs += f' stroke="{_hex(stroke)}" stroke-width="{_num(width)}" stroke-linejoin="round"'
            # even-odd matches the PNG rasterizer's crossing rule, so both
            # formats fill the same silhouette.
            attrs += ' fill-rule="evenodd"'
            parts.append(f"<polygon {attrs}/>")
        elif kind == "text":
            _, x, y, s, size, color, anchor = cmd
            fx = {"start": "start", "middle": "middle", "end": "end"}[anchor]
            baseline = y + cap_height(size)
            escaped = (
                s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )
            parts.append(
                f'<text x="{_num(x)}" y="{_num(baseline)}" font-size="{_num(size * 1.2)}" '
                f'fill="{_hex(color)}" text-anchor="{fx}">{escaped}</text>'
            )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
