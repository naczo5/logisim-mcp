"""Backend-agnostic scene description for circuit rendering.

Both renderers (SVG and PNG) draw from the same command list, so the two
formats stay visually consistent. :class:`Scene` records drawing calls in
circuit coordinates and tracks the bounds they cover, which lets each
backend size its canvas before rasterising anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from . import font

# (r, g, b) tuples — SVG converts them to hex, PNG writes them verbatim.
def rgb(r: int, g: int, b: int) -> tuple[int, int, int]:
    return (r, g, b)


WHITE = rgb(255, 255, 255)
BLACK = rgb(17, 17, 17)
WIRE = rgb(55, 65, 75)
PORT_DOT = rgb(17, 17, 24)
JUNCTION = rgb(17, 17, 17)
BODY_FILL = WHITE
GATE_STROKE = rgb(17, 17, 17)
PIN_IN = rgb(4, 100, 78)
PIN_IN_FILL = rgb(225, 245, 238)
PIN_OUT = rgb(150, 90, 8)
PIN_OUT_FILL = rgb(253, 246, 227)
ACCENT_RED = rgb(198, 40, 40)
ACCENT_ORANGE = rgb(230, 100, 10)
LED_UNLIT = rgb(148, 163, 184)
GRAY_FILL = rgb(107, 114, 128)
BOX_FILL = rgb(240, 250, 255)
LABEL = rgb(30, 34, 40)
TITLE = rgb(30, 34, 40)


@dataclass
class Scene:
    """A recorded drawing command list plus the bounds it covers."""

    commands: list[tuple] = field(default_factory=list)
    min_x: float | None = None
    min_y: float | None = None
    max_x: float | None = None
    max_y: float | None = None

    # ----- bounds ---------------------------------------------------------
    def _cover(self, xmin: float, ymin: float, xmax: float, ymax: float) -> None:
        self.min_x = xmin if self.min_x is None else min(self.min_x, xmin)
        self.min_y = ymin if self.min_y is None else min(self.min_y, ymin)
        self.max_x = xmax if self.max_x is None else max(self.max_x, xmax)
        self.max_y = ymax if self.max_y is None else max(self.max_y, ymax)

    def width(self, pad: int = 0) -> int:
        if self.min_x is None:
            return 0
        lo = int(self.min_x)
        hi = int(self.max_x) + (1 if float(self.max_x) != int(self.max_x) else 0)
        return max(1, hi - lo + 2 * pad)

    def height(self, pad: int = 0) -> int:
        if self.min_y is None:
            return 0
        lo = int(self.min_y)
        hi = int(self.max_y) + (1 if float(self.max_y) != int(self.max_y) else 0)
        return max(1, hi - lo + 2 * pad)

    # ----- drawing---------------------------------------------------------
    def line(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        color: tuple[int, int, int],
        width: float = 1.0,
    ) -> None:
        half = width / 2
        self.commands.append(("line", x0, y0, x1, y1, color, width))
        self._cover(
            min(x0, x1) - half - 1,
            min(y0, y1) - half - 1,
            max(x0, x1) + half + 1,
            max(y0, y1) + half + 1,
        )

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        stroke: tuple[int, int, int] | None = None,
        fill: tuple[int, int, int] | None = None,
        width: float = 1.0,
    ) -> None:
        self.commands.append(("rect", x, y, w, h, stroke, fill, width))
        half = width / 2 if stroke else 0
        self._cover(x - half - 1, y - half - 1, x + w + half + 1, y + h + half + 1)

    def circle(
        self,
        cx: float,
        cy: float,
        r: float,
        *,
        stroke: tuple[int, int, int] | None = None,
        fill: tuple[int, int, int] | None = None,
        width: float = 1.0,
    ) -> None:
        self.commands.append(("circle", cx, cy, r, stroke, fill, width))
        extra = max(width / 2 if stroke else 0, 0)
        self._cover(cx - r - extra - 1, cy - r - extra - 1, cx + r + extra + 1, cy + r + extra + 1)

    def polyline(
        self,
        points: list[tuple[float, float]],
        color: tuple[int, int, int],
        width: float = 1.0,
    ) -> None:
        self.commands.append(("polyline", points, color, width))
        half = width / 2
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        self._cover(min(xs) - half - 1, min(ys) - half - 1, max(xs) + half + 1, max(ys) + half + 1)

    def poly(
        self,
        points: list[tuple[float, float]],
        *,
        stroke: tuple[int, int, int] | None = None,
        fill: tuple[int, int, int] | None = None,
        width: float = 1.0,
    ) -> None:
        self.commands.append(("poly", points, stroke, fill, width))
        half = width / 2 if stroke else 0
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        self._cover(min(xs) - half - 1, min(ys) - half - 1, max(xs) + half + 1, max(ys) + half + 1)

    def text(
        self,
        x: float,
        y: float,
        s: str,
        *,
        size: float = 14.0,
        color: tuple[int, int, int] = LABEL,
        anchor: str = "start",
    ) -> None:
        """Draw ``s`` with its *cap top-left region* near ``(x, y)``.

        ``anchor`` is interpreted horizontally only ('start', 'middle',
        'end'). ``y`` is the top of the glyphs; the baseline lands at
        ``y + cap_height``.
        """
        s = str(s)
        self.commands.append(("text", x, y, s, size, color, anchor))
        w = text_width(s, size)
        if anchor == "end":
            x0, x1 = x - w, x
        elif anchor == "middle":
            x0, x1 = x - w / 2, x + w / 2
        else:
            x0, x1 = x, x + w
        self._cover(x0 - 1, y - 2, x1 + 1, y + size + 1)

    @property
    def empty(self) -> bool:
        return not self.commands


def text_width(s: str, size: float) -> float:
    return font.advance(size) * len(s)


def cap_height(size: float) -> float:
    """Distance from the text anchor (cap top) down to the baseline."""
    return 0.875 * size
