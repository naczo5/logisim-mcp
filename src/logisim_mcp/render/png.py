"""PNG rendering backend: a small pure-stdlib rasterizer.

Shape primitives are Bresenham-style lines stamped with a thickness,
scanline polygon/disc fills, and 5x7 bitmap-font text. Coordinates from
the scene (logical, circuit space) are translated by the scene's
bounding-box padding and multiplied by ``scale`` to reach device pixels.
The encoder writes a truecolor RGB PNG with no interlace and no filters
(zlib only — no third-party dependencies).
"""

from __future__ import annotations

import math
import struct
import zlib

from .canvas import Scene
from .font import glyph_columns, glyph_scale

_MAX_DEVICE_PIXELS = 16_000_000
_MAX_SCALE = 4

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PngCanvas:
    """Rasterize a :class:`Scene` into flat RGB bytes and encode a PNG."""

    def __init__(self, scene: Scene, pad: int = 34, scale: int = 2) -> None:
        scale = max(1, min(_MAX_SCALE, int(scale)))
        self.scale = scale
        self.pad = pad
        self.ox = int(scene.min_x) - pad
        self.oy = int(scene.min_y) - pad
        self.width = scene.width(pad) * scale
        self.height = scene.height(pad) * scale
        if self.width * self.height > _MAX_DEVICE_PIXELS:
            raise ValueError(
                f"circuit is too large to raster at scale {scale} "
                f"({self.width}x{self.height} pixels); try a smaller scale"
            )
        self.buf = bytearray(b"\xff" * (self.width * self.height * 3))
        for cmd in scene.commands:
            getattr(self, "_" + cmd[0])(*cmd[1:])

    # ----- device transforms ---------------------------------------------------

    def _dx(self, x: float) -> int:
        return int((x - self.ox) * self.scale)

    def _dy(self, y: float) -> int:
        return int((y - self.oy) * self.scale)

    # ----- pixel stamping ------------------------------------------------------

    def _put(self, px: int, py: int, color: tuple[int, int, int]) -> None:
        if 0 <= px < self.width and 0 <= py < self.height:
            i = (py * self.width + px) * 3
            self.buf[i : i + 3] = bytes(color)

    def _thick_stamp(self, cx: int, cy: int, color: tuple[int, int, int], r: int) -> None:
        if r <= 0:
            self._put(cx, cy, color)
            return
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                self._put(cx + dx, cy + dy, color)

    def _fill_disc(self, cx: float, cy: float, r: float, color: tuple[int, int, int]) -> None:
        cx, cy, r = self._dx(cx), self._dy(cy), r * self.scale
        r2 = r * r
        for py in range(int(cy - r), int(cy + r) + 1):
            span = int(math.sqrt(r2 - (py - cy) ** 2)) if abs(py - cy) <= r else 0
            if span <= 0:
                continue
            for px in range(int(cx - span), int(cx + span) + 1):
                self._put(px, py, color)

    # ----- primitive handlers --------------------------------------------------

    def _line(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        color,
        width: float = 1.0,
    ) -> None:
        ax, ay = self._dx(x0), self._dy(y0)
        bx, by = self._dx(x1), self._dy(y1)
        r = max(0, int(width * self.scale / 2 + 0.5) - 1)
        dx, dy = abs(bx - ax), abs(by - ay)
        sx = 1 if ax < bx else -1
        sy = 1 if ay < by else -1
        err = dx - dy
        x, y = ax, ay
        while True:
            self._thick_stamp(x, y, color, r)
            if x == bx and y == by:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    def _rect(self, x, y, w, h, stroke, fill, width):  # noqa: C901
        if fill is not None:
            x0, y0 = self._dx(x), self._dy(y)
            x1, y1 = self._dx(x + w) - 1, self._dy(y + h) - 1
            for py in range(y0, y1 + 1):
                for px in range(x0, x1 + 1):
                    self._put(px, py, fill)
        if stroke is not None:
            self._line(x, y, x + w, y, stroke, width)
            self._line(x + w, y, x + w, y + h, stroke, width)
            self._line(x + w, y + h, x, y + h, stroke, width)
            self._line(x, y + h, x, y, stroke, width)

    def _circle(self, cx, cy, r, stroke, fill, width):
        if fill is not None:
            self._fill_disc(cx, cy, r, fill)
        if stroke is not None:
            t = max(1, int(width * self.scale / 2 + 0.5))
            steps = max(48, int(8 * r * self.scale))
            dev_cx, dev_cy = self._dx(cx), self._dy(cy)
            rr = r * self.scale
            for i in range(steps):
                a = 2 * math.pi * i / steps
                # round() here: int() truncates and collapses small radii
                # (bubbles, rings) into flat runs.
                px = int(round(dev_cx + rr * math.cos(a)))
                py = int(round(dev_cy + rr * math.sin(a)))
                self._thick_stamp(px, py, stroke, t // 2)

    def _polyline(self, pts, color, width):
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            self._line(ax, ay, bx, by, color, width)

    def _poly(self, pts, stroke, fill, width):
        if fill is not None:
            self._fill_polygon(pts, fill)
        if stroke is not None:
            n = len(pts)
            for i in range(n):
                ax, ay = pts[i]
                bx, by = pts[(i + 1) % n]
                self._line(ax, ay, bx, by, stroke, width)

    def _fill_polygon(self, pts, color) -> None:
        verts = [(self._dx(x), self._dy(y)) for x, y in pts]
        if len(verts) < 3:
            return
        ys = [p[1] for p in verts]
        y_lo, y_hi = max(0, min(ys)), min(self.height - 1, max(ys))
        edges = list(zip(verts, verts[1:] + [verts[0]]))
        for py in range(y_lo, y_hi + 1):
            sample = py + 0.5
            xs: list[float] = []
            for (ax, ay), (bx, by) in edges:
                if ay == by:
                    continue
                lo, hi = (ay, by) if ay <= by else (by, ay)
                if lo <= sample < hi:
                    xs.append(ax + (sample - ay) * (bx - ax) / (by - ay))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                a, b = int(math.ceil(xs[i] - 0.5)), int(math.floor(xs[i + 1] - 0.5))
                for px in range(a, b + 1):
                    self._put(px, py, color)

    def _text(self, x, y, s, size, color, anchor):  # noqa: C901
        # The bitmap font only covers printable ASCII; anything else draws
        # as '?' (same glyph count, so metrics and bounds stay valid).
        s = "".join(c if 0x20 <= ord(c) <= 0x7E else "?" for c in str(s))
        if not s:
            return
        scale = self.scale
        gs = glyph_scale(size) * scale
        adv = int(round(size * 0.75 * scale))
        width_px = adv * len(s)
        if anchor == "end":
            x_dev = self._dx(x) - width_px
        elif anchor == "middle":
            x_dev = self._dx(x) - width_px // 2
        else:
            x_dev = self._dx(x)
        top = self._dy(y)
        for i, ch in enumerate(s):
            cols = glyph_columns(ord(ch))
            base = x_dev + i * adv
            for cx, byte in enumerate(cols):
                for row in range(8):
                    if (byte >> row) & 1:
                        px0 = base + cx * gs
                        py0 = top + row * gs
                        for jy in range(gs):
                            for jx in range(gs):
                                self._put(px0 + jx, py0 + jy, color)


def encode_png(width: int, height: int, rgb: bytearray) -> bytes:
    """Encode raw flat RGB bytes as a PNG file (truecolor, no interlace)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type None
        raw += rgb[y * stride : (y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        _PNG_SIGNATURE
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


def scene_to_png(scene: Scene, pad: int = 34, scale: int = 2) -> bytes:
    """Render ``scene`` and return PNG file bytes."""
    canvas = PngCanvas(scene, pad=pad, scale=scale)
    return encode_png(canvas.width, canvas.height, canvas.buf)
