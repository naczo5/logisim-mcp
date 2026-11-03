from __future__ import annotations

import zlib
from pathlib import Path

import pytest
from mcp.server.fastmcp import Image

from logisim_mcp.circ.parser import parse
from logisim_mcp.render.canvas import Scene
from logisim_mcp.render.canvas import JUNCTION as JUNCTION_COLOR
from logisim_mcp.render.png import PngCanvas, encode_png, scene_to_png
from logisim_mcp.render.scene import build_scene
from logisim_mcp.tools.builder_tools import add_pin, add_wire
from logisim_mcp.tools.io_tools import create_circuit_file
from logisim_mcp.tools.render_tools import render_circuit


def _png_dims(png: bytes) -> tuple[int, int]:
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    import struct

    w, h = struct.unpack(">II", png[16:24])
    return w, h


@pytest.fixture()
def half(tmp_path: Path) -> Path:
    return Path(__file__).parent / "fixtures" / "half_adder.circ"


def test_render_png_blocks_and_file(half: Path, tmp_path: Path) -> None:
    out = tmp_path / "ha.png"
    res = render_circuit(
        str(half), circuit="half_adder", output=str(out), include_image=True
    )
    assert [type(b).__name__ for b in res] == ["Image", "dict"]
    img, info = res
    assert isinstance(img, Image)
    assert img.data.startswith(b"\x89PNG\r\n\x1a\n")
    assert info["format"] == "png"
    assert info["path"] == str(out.resolve())
    assert isinstance(info["width"], int) and isinstance(info["height"], int)
    dw, dh = _png_dims(img.data)
    assert dw == info["width"] * 2  # default scale 2
    assert dh == info["height"] * 2
    assert out.read_bytes() == img.data


def test_render_default_output_name(tmp_path: Path) -> None:
    circ = tmp_path / "lab.circ"
    create_circuit_file(str(circ))
    res1 = render_circuit(str(circ), circuit="main", include_image=False)
    assert res1[0]["path"].endswith("lab.png")

    from logisim_mcp.tools.highlevel_tools import build_half_adder

    build_half_adder(str(circ))
    res2 = render_circuit(str(circ), circuit="half_adder", include_image=False)
    assert res2[0]["path"].endswith("_half_adder.png")


def test_render_svg(half: Path, tmp_path: Path) -> None:
    out = tmp_path / "ha.svg"
    res = render_circuit(str(half), circuit="half_adder", format="svg",
                         output=str(out), include_image=True)
    info = res[0]
    assert len(res) == 1
    assert "note" in info  # svg cannot be embedded
    text = Path(info["path"]).read_text()
    assert text.startswith("<svg ") and text.rstrip().endswith("</svg>")
    assert "viewBox=" in text
    assert "<circle" in text
    assert ">Sum<" in text
    assert ">Cout<" in text


def test_render_include_image_false(half: Path, tmp_path: Path) -> None:
    out = tmp_path / "ha.png"
    res = render_circuit(str(half), circuit="half_adder", output=str(out),
                         include_image=False)
    assert len(res) == 1
    info = res[0]
    assert info["path"] == str(out.resolve())
    assert out.exists()
    assert _png_dims(out.read_bytes())[0] == info["width"] * 2


def test_render_scale_clamped(tmp_path: Path) -> None:
    circ = tmp_path / "lab.circ"
    create_circuit_file(str(circ))
    res = render_circuit(str(circ), circuit="main", scale=99, include_image=False)
    assert res[0]["scale"] == 4
    res = render_circuit(str(circ), circuit="main", scale=1, include_image=False)
    assert res[0]["scale"] == 1


def test_render_errors(half: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError):  # bad format
        render_circuit(str(half), format="jpeg")
    with pytest.raises(KeyError):
        render_circuit(str(half), circuit="nope", include_image=False)
    with pytest.raises(FileNotFoundError):
        render_circuit(str(tmp_path / "missing.circ"))


def test_render_empty_circuit(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "empty.circ"
    out_dir = tmp_path / "empty"
    out_dir.mkdir()
    res = render_circuit(str(fixture), circuit="main", format="svg",
                         output=str(out_dir / "empty.svg"), include_image=False)
    text = (out_dir / "empty.svg").read_text()
    assert "(empty circuit)" in text
    res = render_circuit(str(fixture), circuit="main",
                         output=str(out_dir / "empty.png"), include_image=False)
    assert res[0]["width"] > 0 and res[0]["height"] > 0
    assert (out_dir / "empty.png").exists()


# ----- scene white-box -------------------------------------------------------


def test_scene_gate_silhouettes(half: Path) -> None:
    project = parse(half)
    circuit = project.require_circuit("half_adder")
    scene = build_scene(project, circuit)
    polys = [c for c in scene.commands if c[0] == "poly"]
    # XOR fin (sampled back curve + two bezier edges) and AND body both draw
    assert len(polys) >= 2
    big = [c for c in polys if len(c[1]) >= 12]
    assert len(big) >= 2


def test_scene_marks_floating_and_shorted(tmp_path: Path) -> None:
    circ = tmp_path / "bad.circ"
    create_circuit_file(str(circ))
    from logisim_mcp.tools.builder_tools import add_gate

    add_gate(str(circ), "main", "AND", x=200, y=100)
    add_gate(str(circ), "main", "XOR", x=260, y=260)
    # wire driven by both gate outputs: shorted net
    add_wire(str(circ), "main", (200, 100), (260, 260))
    project = parse(circ)
    circuit = project.require_circuit("main")
    scene = build_scene(project, circuit)
    red = [c for c in scene.commands if c[0] == "circle" and c[4] == (198, 40, 40)]
    orange = [
        c for c in scene.commands if c[0] == "circle" and c[4] == (230, 100, 10)
    ]
    # four undriven gate inputs (AND 2, XOR 2) ring red
    assert len(red) == 4
    # both gate outputs drive the same net: two orange rings
    assert len(orange) == 2


def test_scene_unconnected_async_pins_ring_gray(tmp_path: Path) -> None:
    """Zadanie-style JK flip-flops: S/R left unconnected on purpose."""
    from logisim_mcp.tools.builder_tools import add_component

    def setup(path: str) -> None:
        add_component(path, "main", "J-K Flip-Flop", x=300, y=300)

    circ = tmp_path / "probe.circ"
    create_circuit_file(str(circ))
    setup(str(circ))
    project = parse(circ)
    circuit = project.require_circuit("main")
    scene = build_scene(project, circuit)
    red = [c for c in scene.commands if c[0] == "circle" and c[4] == (198, 40, 40)]
    gray = [c for c in scene.commands if c[0] == "circle" and c[4] == (140, 150, 160)]
    # J, K, CLK float (errors); S, R are optional async pins (gray rings)
    assert len(red) == 3
    assert len(gray) == 2


def test_render_reports_pixel_dimensions(half: Path, tmp_path: Path) -> None:
    for scale in (1, 3):
        out = tmp_path / "pd.png"
        res = render_circuit(str(half), circuit="half_adder", scale=scale,
                             include_image=False, output=str(out))
        info = res[-1]
        assert info["pixel_width"] == info["width"] * scale
        assert info["pixel_height"] == info["height"] * scale
        w, h = _png_dims(out.read_bytes())
        assert (w, h) == (info["pixel_width"], info["pixel_height"])


def test_dense_box_port_labels_never_overlap_or_drop(tmp_path: Path) -> None:
    """Q_bar vs the next CLK: in the reported dense layout, port labels
    collided into a scrambled word. skip_overlap + wide-enough fallback
    steps fix it — and no label may silently vanish."""
    from logisim_mcp.tools.builder_tools import add_component

    circ = tmp_path / "dense.circ"
    create_circuit_file(str(circ))
    # 80px pitch: bodies are disjoint (60px wide) but the right-side
    # Q_bar label of one box overlaps the left-side CLK label of the
    # next — the exact collision reported against dense layouts.
    for x in (300, 380, 460, 540):
        add_component(str(circ), "main", "J-K Flip-Flop", x=x, y=490)
    project = parse(circ)
    circuit = project.require_circuit("main")
    scene = build_scene(project, circuit)
    texts = [c for c in scene.commands if c[0] == "text"]
    # 4 boxes x (7 port labels + 1 title) must ALL be drawn: a fallback
    # step smaller than the label rect once dropped J and CLK entirely.
    assert len(texts) == 4 * 8
    rects = []
    for cmd in texts:
        _, x, y, s, size, _color, anchor = cmd
        from logisim_mcp.render.canvas import text_width

        w = text_width(s, size)
        if anchor == "end":
            x0, x1 = x - w, x
        elif anchor == "middle":
            x0, x1 = x - w / 2, x + w / 2
        else:
            x0, x1 = x, x + w
        rects.append((x0, y - 2, x1, y + size + 1))
    for i, (a, ta) in enumerate(zip(rects, texts)):
        for b, tb in zip(rects[i + 1 :], texts[i + 1 :]):
            assert (
                a[0] >= b[2] or b[0] >= a[2] or a[1] >= b[3] or b[1] >= a[3]
            ), f"text overlap: {ta[3]!r} vs {tb[3]!r}"


def test_scene_unknown_and_specials(tmp_path: Path) -> None:
    circ = tmp_path / "misc.circ"
    create_circuit_file(str(circ))
    from logisim_mcp.tools.builder_tools import add_component

    add_component(str(circ), "main", "Clock", x=100, y=100)
    add_component(str(circ), "main", "LED", x=200, y=100)
    # unknown type: no factory; write a raw component through the parser
    # by adding a Pin and renaming it via attrs is overkill — use Tunnel
    add_component(str(circ), "main", "Constant", x=300, y=100)
    add_wire(str(circ), "main", (100, 100), (300, 100))
    project = parse(circ)
    circuit = project.require_circuit("main")
    scene = build_scene(project, circuit)
    text_ = [c for c in scene.commands if c[0] == "text"]
    joined = " ".join(c[3] for c in text_)
    assert "0x1" in joined  # Constant value renders


# ----- PNG plumbing ----------------------------------------------------------


def test_png_text_rasterizes() -> None:
    scene = Scene()
    scene.text(0, 0, "A")
    canvas = PngCanvas(scene, pad=10, scale=1)
    assert canvas.width > 0 and canvas.height > 0
    colored = 0
    for i in range(0, len(canvas.buf), 3):
        if tuple(canvas.buf[i : i + 3]) != (255, 255, 255):
            colored += 1
    assert colored >= 12  # 5x7 'A' has 12 lit glyph pixels


def test_png_encoder_roundtrip() -> None:
    import struct

    w, h = 4, 3
    rgb = bytearray(b"\x00" * (w * h * 3))
    rgb[0:3] = b"\xff\x00\x00"
    raw = encode_png(w, h, rgb)
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    assert raw.rstrip().endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")
    # walk chunks: IHDR must say bit depth 8, color type 2 (truecolor)
    pos = 8
    found = {}
    while pos < len(raw) - 8:
        (length,) = struct.unpack(">I", raw[pos : pos + 4])
        tag = raw[pos + 4 : pos + 8]
        data = raw[pos + 8 : pos + 8 + length]
        found[tag] = data
        pos += 12 + length
    assert struct.unpack(">IIBBBBB", found[b"IHDR"]) == (4, 3, 8, 2, 0, 0, 0)
    assert len(zlib.decompress(found[b"IDAT"])) == h * (1 + 3 * w)


def test_png_canvas_line_and_disc() -> None:
    scene = Scene()
    scene.line(0, 0, 40, 0, (1, 2, 3), 1.0)
    scene.circle(20, 20, 6, stroke=None, fill=(9, 9, 9))
    canvas = PngCanvas(scene, pad=10, scale=1)
    def px(x: int, y: int) -> tuple[int, int, int]:
        i = (y * canvas.width + x) * 3
        return tuple(canvas.buf[i : i + 3])
    assert px(canvas._dx(5), canvas._dy(0)) == (1, 2, 3)
    assert px(canvas._dx(20), canvas._dy(20)) == (9, 9, 9)
    assert px(0, canvas.height - 1) != (1, 2, 3)  # background untouched
    assert scene_to_png(scene)[:8] == b"\x89PNG\r\n\x1a\n"


def test_mcp_result_has_image_content(half: Path, tmp_path: Path) -> None:
    """FastMCP converts the tool result into image + text content blocks."""
    from mcp.server.fastmcp.tools.base import Tool

    tool = Tool.from_function(render_circuit)
    assert tool.fn_metadata.output_schema is None
    out = tmp_path / "ha.png"
    res = tool.fn_metadata.convert_result(
        render_circuit(str(half), circuit="half_adder", output=str(out),
                       include_image=True)
    )
    blocks = list(res)
    assert getattr(blocks[0], "type", None) == "image"
    assert getattr(blocks[0], "mimeType", None) == "image/png"
    import base64

    data = base64.b64decode(blocks[0].data)
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    # the dict follows as a JSON text block
    text = blocks[1]
    assert '"format": "png"' in text.text


# ----- regression tests for review findings ----------------------------------


WIRE_RGB = (55, 65, 75)
UNKNOWN_FILL = (243, 244, 246)


def _scene_for(tmp_path: Path, setup) -> Scene:
    circ = tmp_path / "probe.circ"
    create_circuit_file(str(circ))
    setup(str(circ))
    project = parse(circ)
    return build_scene(project, project.require_circuit("main"))


def _canvas(px_probe: Scene, pad: int = 10, scale: int = 1):
    canvas = PngCanvas(px_probe, pad=pad, scale=scale)

    def px(x: int, y: int) -> tuple[int, int, int]:
        i = (y * canvas.width + x) * 3
        return tuple(canvas.buf[i : i + 3])

    return canvas, px


def test_not_gate_draws_triangle_and_bubble_not_unknown_box(tmp_path: Path) -> None:
    from logisim_mcp.tools.builder_tools import add_gate

    def setup(path: str) -> None:
        add_gate(path, "main", "NOT", x=500, y=500)

    scene = _scene_for(tmp_path, setup)
    triangles = [c for c in scene.commands if c[0] == "poly" and len(c[1]) == 3]
    assert len(triangles) == 1
    bubbles = [c for c in scene.commands if c[0] == "circle" and abs(c[3] - 5) < 1e-9]
    assert len(bubbles) >= 1
    assert not any(c[0] == "rect" and c[6] == UNKNOWN_FILL for c in scene.commands)


def test_or_body_covers_wire_behind(tmp_path: Path) -> None:
    from logisim_mcp.tools.builder_tools import add_gate

    def setup(path: str) -> None:
        add_gate(path, "main", "OR", inputs=3, x=300, y=140)
        add_wire(path, "main", (255, 140), (300, 140))

    scene = _scene_for(tmp_path, setup)
    # no chord jumps in the fin outline: consecutive samples stay close
    fins = [c for c in scene.commands if c[0] == "poly" and len(c[1]) >= 25]
    assert len(fins) == 1
    pts = fins[0][1]
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        assert abs(bx - ax) <= 8 and abs(by - ay) <= 8

    canvas, px = _canvas(scene)
    # wire behind the body must vanish under the gate's white fill;
    # the same wire outside the body stays wire-colored.
    assert px(canvas._dx(266), canvas._dy(140)) == (255, 255, 255)
    assert px(canvas._dx(257), canvas._dy(140)) == WIRE_RGB


def test_box_ports_inside_body_for_facings(tmp_path: Path) -> None:
    from logisim_mcp.tools.builder_tools import add_component
    from logisim_mcp.circ.library import spec_for_component

    def setup(path: str) -> None:
        spots = {"east": (520, 520), "west": (520, 700), "north": (700, 520), "south": (700, 700)}
        for facing, (x, y) in spots.items():
            add_component(path, "main", "Multiplexer", attrs={"facing": facing}, x=x, y=y)
        add_component(path, "main", "Register", attrs={"facing": "west"}, x=900, y=520)

    circ = tmp_path / "probe.circ"
    create_circuit_file(str(circ))
    setup(str(circ))
    project = parse(circ)
    circuit = project.require_circuit("main")
    scene = build_scene(project, circuit)
    rects = {(c[1], c[2]): c for c in scene.commands if c[0] == "rect"}
    for comp in circuit.components:
        spec = spec_for_component(project, comp)
        assert spec is not None
        w, h = spec.bbox
        ax, ay = spec.anchor
        x0, y0 = comp.loc[0] - ax, comp.loc[1] - ay
        rect = rects.get((x0, y0))
        assert rect is not None, f"no body box at ({x0},{y0}) for {comp.name}"
        assert (x0 + w, y0 + h) == (rect[1] + rect[3], rect[2] + rect[4])
        for port in spec.ports:
            pt = (comp.loc[0] + port.dx, comp.loc[1] + port.dy)
            assert x0 <= pt[0] <= x0 + w, f"port {port.label} x off body ({comp.name} {comp.attrs.get('facing')})"
            assert y0 <= pt[1] <= y0 + h, f"port {port.label} y off body ({comp.name} {comp.attrs.get('facing')})"


def test_gate_stubs_reach_the_body(tmp_path: Path) -> None:
    from logisim_mcp.tools.builder_tools import add_gate

    def setup(path: str) -> None:
        types = [("AND", 2), ("OR", 3), ("XOR", 3), ("NAND", 2), ("NOR", 2), ("XNOR", 2), ("NOT", 1), ("BUF", 1)]
        for i, (gate, inputs) in enumerate(types):
            add_gate(path, "main", gate, inputs=inputs, x=300, y=100 + i * 90)

    circ = tmp_path / "probe.circ"
    create_circuit_file(str(circ))
    setup(str(circ))
    project = parse(circ)
    circuit = project.require_circuit("main")
    scene = build_scene(project, circuit)
    lines = [c for c in scene.commands if c[0] == "line"]

    for comp in circuit.components:
        from logisim_mcp.circ.library import gate_spec, spec_for_component

        spec = spec_for_component(project, comp)
        key = spec.type_key
        base = gate_spec(key, inputs=len([p for p in spec.ports if p.direction == "in"]))
        axis = -min(p.dx for p in base.ports if p.direction == "in")
        for port in spec.ports:
            if port.direction != "in":
                continue
            pt = (comp.loc[0] + port.dx, comp.loc[1] + port.dy)
            dy = port.dy
            half = max(25.0, abs(dy) + 5.0)
            curved = key in ("OR", "NOR", "XOR", "XNOR")
            allowed_x = comp.loc[0] + (-axis + (10.0 * (1 - (dy / half) ** 2) if curved else 0))
            ends_here = []
            for line in lines:
                if (line[1], line[2]) == pt:
                    ends_here.append((line[3], line[4]))
                elif (line[3], line[4]) == pt:
                    ends_here.append((line[1], line[2]))
            assert ends_here, f"no stub touching port {pt} of {key}"
            assert any(abs(ex - allowed_x) <= 1.0 and ey == pt[1] for ex, ey in ends_here), (
                f"stub of {key} input at {pt} ends at {ends_here}, expected x={allowed_x}"
            )


def test_junction_dots(tmp_path: Path) -> None:
    def setup(path: str) -> None:
        add_wire(path, "main", (100, 100), (200, 100))
        add_wire(path, "main", (150, 50), (150, 100))
        add_wire(path, "main", (150, 100), (150, 200))

    scene = _scene_for(tmp_path, setup)
    dots = [
        c
        for c in scene.commands
        if c[0] == "circle" and abs(c[3] - 3) < 1e-9 and c[4] is None and c[5] == JUNCTION_COLOR
    ]
    assert len(dots) == 1
    assert (dots[0][1], dots[0][2]) == (150.0, 100.0)


def test_svg_wellformed_for_weird_names(tmp_path: Path) -> None:
    from lxml import etree

    circ = tmp_path / "my--lab--v2.circ"
    create_circuit_file(str(circ))
    res = render_circuit(str(circ), circuit="main", format="svg",
                         output=str(tmp_path / "out.svg"), include_image=False)
    xml = Path(res[0]["path"]).read_text()
    etree.fromstring(xml.encode("utf-8"))  # must not raise


def test_render_param_guards(tmp_path: Path) -> None:
    circ = tmp_path / "lab.circ"
    create_circuit_file(str(circ))
    with pytest.raises(ValueError):
        render_circuit(str(circ), circuit="")
    with pytest.raises(ValueError):
        render_circuit(str(circ), circuit="main", output="")
    with pytest.raises(ValueError):
        render_circuit(str(circ), circuit="main", scale=True)


def test_wires_only_circuit(tmp_path: Path) -> None:
    def setup(path: str) -> None:
        add_wire(path, "main", (100, 100), (300, 100))

    scene = _scene_for(tmp_path, setup)
    assert any(c[0] == "line" for c in scene.commands)
    png = scene_to_png(scene)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_non_ascii_labels(tmp_path: Path) -> None:
    def setup(path: str) -> None:
        add_pin(path, "main", "Café", x=110, y=110)

    circ = tmp_path / "probe.circ"
    create_circuit_file(str(circ))
    setup(str(circ))
    project = parse(circ)
    circuit = project.require_circuit("main")
    scene = build_scene(project, circuit)
    texts = " ".join(c[3] for c in scene.commands if c[0] == "text")
    assert "Café" in texts
    canvas, _px = _canvas(scene)
    colored = sum(
        1
        for i in range(0, len(canvas.buf), 3)
        if tuple(canvas.buf[i : i + 3]) != (255, 255, 255)
    )
    assert colored >= 12


def test_render_perf_on_wire_mesh(tmp_path: Path) -> None:
    """2000 collinear wires: the T-junction pass must stay off O(w x ends)."""
    import time

    rows = [f'    <wire from="(100,{100 + i * 10})" to="(300,{100 + i * 10})"/>' for i in range(2000)]
    body = "\n".join(rows)
    circ = tmp_path / "mesh.circ"
    circ.write_text(
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<project source="4.0.0" version="1.0">\n'
        '  <lib desc="#Wiring" name="0"/>\n'
        '  <lib desc="#Gates" name="1"/>\n'
        '  <lib desc="#Base" name="9"/>\n'
        '  <main name="main"/>\n'
        '  <circuit name="main">\n'
        f'{body}\n'
        '  </circuit>\n'
        '</project>\n'
    )
    project = parse(circ)
    start = time.monotonic()
    scene = build_scene(project, project.require_circuit("main"))
    scene_to_png(scene, pad=10, scale=1)
    elapsed = time.monotonic() - start
    assert elapsed < 6.0, f"rendering 2000 wires took {elapsed:.2f}s (junction pass regressed?)"
