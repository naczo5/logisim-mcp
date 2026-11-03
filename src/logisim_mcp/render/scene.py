"""Draw a parsed circuit into a :class:`~logisim_mcp.render.canvas.Scene`.

Geometry comes from the component catalogue (``circ.library``): every
glyph is defined *east-facing relative to the component ``loc``*, which
is exactly how ports are specified, so one rotation helper turns both
ports and outlines to the component's ``facing``.

Verification cues an agent relies on:

- wires draw under component bodies (Logisim-style layering);
- every known port gets a dot; **floating inputs get a red ring** and
  shorted-net drivers get an orange ring (reuses the DRC net builder);
- diagonal wires, which Logisim refuses to load, draw red;
- a junction dot appears where three or more wire ends meet.
"""

from __future__ import annotations

import math

from ..circ.coords import on_segment
from ..circ.library import (
    _GATE_GEOMETRY,
    gate_spec,
    is_output_pin,
    rotate_offset,
    spec_for_component,
)
from ..circ.model import Circuit, Component, Point, Project
from ..circ.parser import is_diagonal
from .canvas import (
    ACCENT_ORANGE,
    ACCENT_RED,
    BODY_FILL,
    BLACK,
    BOX_FILL,
    GRAY_FILL,
    GATE_STROKE,
    JUNCTION,
    LABEL,
    LED_UNLIT,
    OPTIONAL_RING,
    PIN_IN,
    PIN_IN_FILL,
    PIN_OUT,
    PIN_OUT_FILL,
    PORT_DOT,
    Scene,
    TITLE,
    WIRE,
)

GATE_KEYS = ("AND", "OR", "NAND", "NOR", "XOR", "XNOR", "NOT", "BUF")

_BOX_TITLES = {
    "Multiplexer": "MUX",
    "Demultiplexer": "DEMUX",
    "Decoder": "DEC",
    "Adder": "ADD",
    "Comparator": "CMP",
    "Register": "REG",
    "Counter": "CNT",
    "D Flip-Flop": "D FF",
    "T Flip-Flop": "T FF",
    "J-K Flip-Flop": "JK FF",
    "S-R Flip-Flop": "SR FF",
}

_LABEL_SIZE = 13.0
_TITLE_SIZE = 12.0
_PORT_MARK_SIZE = 9.0
_UNKNOWN_FILL = (243, 244, 246)


def _pt(loc: Point, p: tuple[float, float], facing: str) -> tuple[float, float]:
    dx, dy = rotate_offset(int(round(p[0])), int(round(p[1])), facing)
    return loc[0] + dx, loc[1] + dy


def _port_status(
    project: Project, circuit: Circuit
) -> tuple[set[Point], set[Point], set[Point]]:
    """Points of floating required inputs, shorted-net drivers, and
    unconnected *optional* (async preset/clear) pins — from the DRC net
    builder (describe_tools), so the picture matches the report."""
    from ..circ.library import is_async_optional
    from ..tools.describe_tools import _build_nets

    point_to_net, _ = _build_nets(project, circuit)
    drivers: dict[int, int] = {}
    members: list[tuple[Point, str, int, bool]] = []
    for comp in circuit.components:
        spec = spec_for_component(project, comp)
        if spec is None:
            continue
        for port in spec.ports:
            pt = (comp.loc[0] + port.dx, comp.loc[1] + port.dy)
            nid = point_to_net.get(pt)
            if nid is None:
                continue
            members.append(
                (pt, port.direction, nid, is_async_optional(spec, port))
            )
            if port.direction == "out":
                drivers[nid] = drivers.get(nid, 0) + 1
    floating = {
        pt for pt, direction, nid, optional in members
        if direction == "in" and drivers.get(nid, 0) == 0 and not optional
    }
    shorted = {
        pt for pt, direction, nid, optional in members
        if direction == "out" and drivers.get(nid, 0) >= 2
    }
    optional = {
        pt for pt, direction, nid, optional in members
        if direction == "in" and drivers.get(nid, 0) == 0 and optional
    }
    return floating, shorted, optional


# ----- sampling helpers -----------------------------------------------------


def _quad(p0, c, p1, n: int = 12) -> list[tuple[float, float]]:
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        pts.append(
            (
                u * u * p0[0] + 2 * u * t * c[0] + t * t * p1[0],
                u * u * p0[1] + 2 * u * t * c[1] + t * t * p1[1],
            )
        )
    return pts


def _make_or_back(corner_x: float, half: float):
    """Back-edge x for dy: a curve whose middle bulges ``10`` px toward
    the output; corners sit at ``corner_x``. Used for OR-family bodies and
    for XOR's extra curve (offset outside the body)."""

    def fx(dy: float) -> float:
        return corner_x + 10.0 * (1 - (dy / half) ** 2)

    return fx


# ----- per-family glyphs (all east-space, relative to loc) ------------------


def _draw_and_body(
    scene: Scene, loc: Point, facing: str, axis: int, negate: bool, half: float
) -> None:
    front = -10 if negate else 0
    cx = max(-axis, front - half)
    rx = front - cx
    cap = []
    for i in range(13):
        t = -math.pi / 2 + math.pi * i / 12
        cap.append((cx + rx * math.cos(t), half * math.sin(t)))
    outline = [_pt(loc, (-axis, -half), facing)]
    outline += [_pt(loc, (x, y), facing) for x, y in cap[1:-1]]
    outline.append(_pt(loc, (-axis, half), facing))
    scene.poly(outline, stroke=GATE_STROKE, fill=BODY_FILL, width=1.6)
    if negate:
        bx = _pt(loc, (-5, 0), facing)
        scene.circle(bx[0], bx[1], 5, stroke=GATE_STROKE, fill=BODY_FILL, width=1.4)


def _draw_or_body(
    scene: Scene,
    loc: Point,
    facing: str,
    axis: int,
    negate: bool,
    half: float,
    xor_extra: bool,
) -> None:
    front = -10 if negate else 0
    fbody = _make_or_back(corner_x=-axis + (10 if xor_extra else 0), half=half)
    outline: list[tuple[float, float]] = []
    for sgn in (1, -1):
        corner = (fbody(sgn * half), sgn * half)
        ctrl = ((corner[0] + front) * 0.45, sgn * half)
        tip = (front, 0)
        pts = _quad(corner, ctrl, tip, 10)
        if sgn == -1:
            pts.reverse()
        outline.extend(pts if sgn == -1 else pts[:-1])
    for i in range(1, 12):  # back curve, ascending top corner -> bottom corner
        dy = -half + 2 * half * i / 12
        outline.append((fbody(dy), dy))
    scene.poly([_pt(loc, p, facing) for p in outline], stroke=GATE_STROKE, fill=BODY_FILL, width=1.6)
    if xor_extra:
        fouter = _make_or_back(corner_x=-axis, half=half)
        outer = [(fouter(dy), dy) for dy in (-half + 2 * half * i / 16 for i in range(17))]
        scene.polyline([_pt(loc, p, facing) for p in outer], GATE_STROKE, 1.4)
    if negate:
        bx = _pt(loc, (-5, 0), facing)
        scene.circle(bx[0], bx[1], 5, stroke=GATE_STROKE, fill=BODY_FILL, width=1.4)


def _draw_triangle_gate(
    scene: Scene, loc: Point, facing: str, axis: int, negate: bool
) -> None:
    front = -10 if negate else 0
    pts = [
        _pt(loc, (-axis, -12), facing),
        _pt(loc, (-axis, 12), facing),
        _pt(loc, (front, 0), facing),
    ]
    scene.poly(pts, stroke=GATE_STROKE, fill=BODY_FILL, width=1.6)
    if negate:
        bx = _pt(loc, (-5, 0), facing)
        scene.circle(bx[0], bx[1], 5, stroke=GATE_STROKE, fill=BODY_FILL, width=1.4)


def _gate(scene: Scene, comp: Component, spec: ComponentSpec, facing: str) -> None:
    key = spec.type_key
    inputs = int(comp.attrs.get("inputs", 1 if key in ("NOT", "BUF") else 2))
    raw_size = comp.attrs.get("size")
    size = int(raw_size) if raw_size and raw_size.isdigit() else None
    base = gate_spec(key, inputs=inputs, size=size)
    ins = [p for p in base.ports if p.direction == "in"]
    axis = -min(p.dx for p in ins)
    half = float(max(25, max(abs(p.dy) for p in ins) + 5)) if ins else 25.0
    negate = _GATE_GEOMETRY[key].get("negate_out", False)
    xor_extra = key in ("XOR", "XNOR")

    # Stub target for each input: flat back plane (AND/NAND/NOT/BUF) or the
    # curved back silhouette (OR-family — corner inputs reach the curve
    # only for XOR's outer curve; see _draw_or_body / _make_or_back).
    if xor_extra:
        fouter = _make_or_back(-float(axis), half)
        back_x = lambda dy: fouter(dy)
    elif key in ("OR", "NOR"):
        fbody = _make_or_back(-float(axis), half)
        back_x = lambda dy: fbody(dy)
    else:
        back_x = lambda dy: -float(axis)
    for p in ins:
        x0, y0 = _pt(comp.loc, (p.dx, p.dy), facing)
        x1, y1 = _pt(comp.loc, (back_x(p.dy), p.dy), facing)
        scene.line(x0, y0, x1, y1, WIRE, 2.0)

    if key in ("AND", "NAND"):
        _draw_and_body(scene, comp.loc, facing, axis, negate, half)
    elif key in ("OR", "NOR", "XOR", "XNOR"):
        _draw_or_body(scene, comp.loc, facing, axis, negate, half, xor_extra)
    else:
        _draw_triangle_gate(scene, comp.loc, facing, axis, negate)

    label = comp.attrs.get("label")
    if label:
        top = _pt(comp.loc, (-axis / 2, -half - 18), facing)
        scene.text(top[0], top[1], label, size=_LABEL_SIZE, anchor="middle")


def _draw_box(
    scene: Scene,
    comp: Component,
    spec: ComponentSpec,
    title: str,
) -> None:
    # spec.bbox/anchor are already in the same frame as spec.ports (east
    # for #Arithmetic/#Memory/flip-flops; the absolute frame _port_bbox
    # computes for plexers with a non-east facing), so the body must NOT
    # be rotated again — only gate/pin/etc. glyphs need _pt().
    w, h = spec.bbox
    ax, ay = spec.anchor
    x0 = comp.loc[0] - ax
    y0 = comp.loc[1] - ay
    scene.rect(x0, y0, w, h, stroke=BLACK, fill=BOX_FILL, width=1.6)
    center = (x0 + w / 2, y0 + h / 2)
    scene.text(center[0], center[1] - _TITLE_SIZE * 0.45, title, size=_TITLE_SIZE, color=TITLE, anchor="middle")
    for port in spec.ports:
        pt = (comp.loc[0] + port.dx, comp.loc[1] + port.dy)
        ddx = pt[0] - center[0]
        ddy = pt[1] - center[1]
        size = _PORT_MARK_SIZE

        def place(bx: float, by: float, anchor: str) -> bool:
            return scene.text(
                bx, by, port.label, size=size, anchor=anchor, skip_overlap=True
            )

        if abs(ddx) >= abs(ddy) and ddx != 0:
            bx = pt[0] + (5 if ddx > 0 else -5)
            anchor = "start" if ddx > 0 else "end"
            # Colliding labels shift one row before giving up silently:
            # two labels on top of each other in dense layouts read as a
            # single scrambled word (Q_bar vs the next CLK).
            if not place(bx, pt[1] - 4, anchor):
                if not place(bx, pt[1] - 4 - (size + 2), anchor):
                    place(bx, pt[1] - 4 + (size + 2), anchor)
        elif ddy != 0:
            by = pt[1] + (4 if ddy > 0 else -size * 1.15)
            if not place(pt[0], by, "middle"):
                if not place(pt[0] - (size * 1.6 + 2), by, "middle"):
                    place(pt[0] + (size * 1.6 + 2), by, "middle")


def _draw_pin(scene: Scene, comp: Component, spec: ComponentSpec) -> None:
    facing = comp.attrs.get("facing", "east")
    is_out = is_output_pin(comp.attrs)
    body = _pt(comp.loc, (-7, 0), facing)
    stroke = PIN_OUT if is_out else PIN_IN
    fill = PIN_OUT_FILL if is_out else PIN_IN_FILL
    scene.circle(body[0], body[1], 7, stroke=stroke, fill=fill, width=1.7)
    scene.circle(body[0], body[1], 2.4, stroke=None, fill=stroke)
    label = comp.attrs.get("label", "")
    width = comp.attrs.get("width", "1")
    if width.isdigit() and int(width) > 1:
        label += f"[{width}]"
    if not label:
        return
    d = rotate_offset(-1, 0, facing)
    if d[0] != 0:
        x = body[0] + d[0] * 10
        y = comp.loc[1] - _LABEL_SIZE * 0.52
        scene.text(x, y, label, size=_LABEL_SIZE, anchor="end" if d[0] < 0 else "start")
    else:
        top = body[1] + d[1] * 14 if d[1] > 0 else body[1] - 14 - _LABEL_SIZE
        scene.text(body[0], top, label, size=_LABEL_SIZE, anchor="middle")


def _draw_tunnel(scene: Scene, comp: Component, spec: ComponentSpec) -> None:
    facing = comp.attrs.get("facing", "west")
    tip = _pt(comp.loc, (0, 0), facing)
    up = _pt(comp.loc, (-24, -9), facing)
    back = _pt(comp.loc, (-24, 0), facing)
    down = _pt(comp.loc, (-24, 9), facing)
    scene.poly([tip, up, back, down], stroke=BLACK, fill=BODY_FILL, width=1.5)
    label = comp.attrs.get("label", "").strip()
    if not label:
        return
    d = rotate_offset(-1, 0, facing)
    if d[0] != 0:
        x = back[0] + d[0] * 10
        y = comp.loc[1] - _LABEL_SIZE * 0.52
        scene.text(x, y, label, size=_LABEL_SIZE, anchor="end" if d[0] < 0 else "start")
    else:
        top = back[1] + d[1] * 14 if d[1] > 0 else back[1] - 14 - _LABEL_SIZE
        scene.text(back[0], top, label, size=_LABEL_SIZE, anchor="middle")


def _draw_clock(scene: Scene, comp: Component) -> None:
    facing = comp.attrs.get("facing", "east")
    corners = [(-30, -15), (0, -15), (0, 15), (-30, 15)]
    scene.poly([_pt(comp.loc, c, facing) for c in corners], stroke=BLACK, fill=BODY_FILL, width=1.5)
    wave = [(-24, 7), (-24, -6), (-14, -6), (-14, 7), (-4, 7), (-4, -6)]
    scene.polyline([_pt(comp.loc, p, facing) for p in wave], BLACK, 1.4)


def _draw_constant(scene: Scene, comp: Component) -> None:
    facing = comp.attrs.get("facing", "east")
    corners = [(-16, -9), (0, -9), (0, 9), (-16, 9)]
    scene.poly([_pt(comp.loc, c, facing) for c in corners], stroke=BLACK, fill=BODY_FILL, width=1.5)
    value = comp.attrs.get("value", "0x1")
    d = rotate_offset(-1, 0, facing)
    if d[0] != 0:
        x = comp.loc[0] + d[0] * 20
        y = comp.loc[1] - _LABEL_SIZE * 0.52
        scene.text(x, y, value, size=_LABEL_SIZE, anchor="end" if d[0] < 0 else "start")
    else:
        top = comp.loc[1] + d[1] * 14 if d[1] > 0 else comp.loc[1] - 14 - _LABEL_SIZE
        scene.text(comp.loc[0], top, value, size=_LABEL_SIZE, anchor="middle")


def _draw_led(scene: Scene, comp: Component) -> None:
    facing = comp.attrs.get("facing", "east")
    body = _pt(comp.loc, (-8, 0), facing)
    scene.circle(body[0], body[1], 7.5, stroke=BLACK, fill=LED_UNLIT, width=1.6)
    label = comp.attrs.get("label", "")
    if label:
        scene.text(body[0], body[1] + 12, label, size=_LABEL_SIZE, anchor="middle")


def _draw_subcircuit(scene: Scene, comp: Component) -> None:
    facing = comp.attrs.get("facing", "east")
    corners = [(-50, -18), (0, -18), (0, 18), (-50, 18)]
    scene.poly([_pt(comp.loc, c, facing) for c in corners], stroke=BLACK, fill=BODY_FILL, width=1.6)
    scene.text(comp.loc[0] - 25, comp.loc[1] - _LABEL_SIZE * 0.45, comp.name, size=_LABEL_SIZE, anchor="middle")


def _draw_unknown(scene: Scene, comp: Component) -> None:
    scene.rect(comp.loc[0] - 26, comp.loc[1] - 9, 26, 18, stroke=GRAY_FILL, fill=_UNKNOWN_FILL, width=1.2)
    scene.text(comp.loc[0] - 13, comp.loc[1] - _PORT_MARK_SIZE * 0.45, comp.name,
               size=_PORT_MARK_SIZE, anchor="middle")
    scene.circle(comp.loc[0], comp.loc[1], 2.2, stroke=None, fill=PORT_DOT)


# ----- wiring, ports, assembly ---------------------------------------------


def _draw_wires(scene: Scene, circuit: Circuit) -> None:
    ends: dict[Point, int] = {}
    for wire in circuit.wires:
        color = ACCENT_RED if is_diagonal(wire) else WIRE
        scene.line(wire.start[0], wire.start[1], wire.end[0], wire.end[1], color, 2.0)
        ends[wire.start] = ends.get(wire.start, 0) + 1
        ends[wire.end] = ends.get(wire.end, 0) + 1
    # T-junctions: a wire endpoint landing on another wire's interior.
    # Bucket endpoints by row/column first so each wire only probes the
    # points sharing its axis — linear overall instead of O(wires x ends).
    rows: dict[int, set[Point]] = {}
    cols: dict[int, set[Point]] = {}
    for point in ends:
        rows.setdefault(point[1], set()).add(point)
        cols.setdefault(point[0], set()).add(point)
    branch: set[Point] = set()
    for wire in circuit.wires:
        if is_diagonal(wire):
            continue
        if wire.start[1] == wire.end[1]:
            candidates = rows.get(wire.start[1])
        elif wire.start[0] == wire.end[0]:
            candidates = cols.get(wire.start[0])
        else:
            continue  # diagonal — Logisim would not load it
        if not candidates:
            continue
        for point in candidates:
            if point == wire.start or point == wire.end:
                continue
            if on_segment(point, wire.start, wire.end):
                ends[point] = ends.get(point, 0) + 1
                branch.add(point)
    for point, count in ends.items():
        if count >= 3 or point in branch:
            scene.circle(point[0], point[1], 3, stroke=None, fill=JUNCTION)


def _draw_ports(
    scene: Scene,
    project: Project,
    circuit: Circuit,
    floating: set[Point],
    shorted: set[Point],
    optional: set[Point],
) -> None:
    for comp in circuit.components:
        spec = spec_for_component(project, comp)
        if spec is None:
            continue
        for port in spec.ports:
            pt = (comp.loc[0] + port.dx, comp.loc[1] + port.dy)
            scene.circle(pt[0], pt[1], 2.6, stroke=None, fill=PORT_DOT)
            if pt in floating:
                scene.circle(pt[0], pt[1], 6, stroke=ACCENT_RED, fill=None, width=1.6)
            elif pt in shorted:
                scene.circle(pt[0], pt[1], 6, stroke=ACCENT_ORANGE, fill=None, width=1.6)
            elif pt in optional:
                # Intentionally-unused async preset/clear pins: Logisim
                # treats an unconnected one as inactive, so a neutral
                # gray ring instead of an alarming error color.
                scene.circle(pt[0], pt[1], 6, stroke=OPTIONAL_RING, fill=None, width=1.4)


def build_scene(project: Project, circuit: Circuit) -> Scene:
    scene = Scene()
    if not circuit.components and not circuit.wires:
        scene.rect(-100, -55, 200, 110, stroke=GRAY_FILL, fill=BODY_FILL, width=1.4)
        scene.text(0, -10, "(empty circuit)", size=15, color=GRAY_FILL, anchor="middle")
        return scene

    floating, shorted, optional = _port_status(project, circuit)
    _draw_wires(scene, circuit)

    circuit_names = {c.name for c in project.circuits}
    for comp in circuit.components:
        spec = spec_for_component(project, comp)
        facing = comp.attrs.get("facing", "east")
        if spec is None:
            if comp.name in circuit_names:
                _draw_subcircuit(scene, comp)
            else:
                _draw_unknown(scene, comp)
            continue
        tk = spec.type_key
        base = tk.split("_")[0]
        if base in GATE_KEYS:
            _gate(scene, comp, spec, facing)
        elif base in _BOX_TITLES:
            _draw_box(scene, comp, spec, _BOX_TITLES[base])
        elif spec.type_key == "InputPin" or spec.type_key == "OutputPin" or comp.name == "Pin":
            _draw_pin(scene, comp, spec)
        elif comp.name == "Tunnel":
            _draw_tunnel(scene, comp, spec)
        elif comp.name == "Clock":
            _draw_clock(scene, comp)
        elif comp.name == "Constant":
            _draw_constant(scene, comp)
        elif comp.name == "LED":
            _draw_led(scene, comp)
        else:
            _draw_unknown(scene, comp)

    _draw_ports(scene, project, circuit, floating, shorted, optional)
    return scene
