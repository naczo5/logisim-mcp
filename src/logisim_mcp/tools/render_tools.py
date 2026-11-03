"""MCP tool: ``render_circuit`` — image rendering of a circuit.

One tool serves both audiences:

*multimodal agent verification* — format=``png`` embeds the image as an
MCP image content block, so the agent can *look* at the result of its
edits (alignment, bubbles, floating inputs) without leaving the chat;

*export* — every call writes the file to disk (next to the ``.circ`` by
default) and returns its absolute path.

The renderer is pure Python (no Java or JDK required).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Image

from ..render.png import scene_to_png
from ..render.scene import build_scene
from ..render.svg import scene_to_svg
from ..circ.parser import parse
from ..server import mcp

_FORMATS = ("png", "svg")


def _default_output(p: Path, circuit: str, is_main: bool, fmt: str) -> Path:
    if is_main or p.stem == circuit:
        stem = p.stem
    else:
        stem = f"{p.stem}_{circuit}"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._") or "circuit"
    return p.parent / f"{safe}.{fmt}"


def _fix_suffix(output: Path, fmt: str) -> Path:
    suffix = output.suffix.lower()
    if suffix == f".{fmt}":
        return output
    if not suffix:
        return output.with_suffix(f".{fmt}")
    return output.with_suffix(f".{fmt}")


@mcp.tool()
def render_circuit(
    path: str,
    circuit: str | None = None,
    format: str = "png",
    output: str | None = None,
    scale: int = 2,
    include_image: bool = True,
):
    """Render a circuit as an image (PNG or SVG) for visual verification and export.

    Args:
        path: ``.circ`` project file.
        circuit: circuit name (defaults to the project's main circuit).
        format: ``png`` (embeddable image, default) or ``svg`` (vector).
        output: output file path; default is next to the ``.circ`` file,
            named ``<stem>_<circuit>.<format>`` (or ``<stem>.<format>``
            when the circuit name equals the file stem).
        scale: PNG pixel scale multiplier, 1-4 (default 2). Ignored by SVG.
        include_image: when True and format is ``png``, also return the
            image itself as MCP image content so a multimodal client can
            look at the schematic. SVG renders ignore this flag (vision
            models cannot read SVG); the file path is always returned.

    Returns the written file path, image size, and (for ``png``) the
    embedded image content. Ports facing nowhere are marked with a red
    ring (floating inputs) or an orange ring (shorted drivers); diagonal
    wires draw red. ``describe_circuit`` remains the textual counterpart.
    """
    fmt = format.strip().lower()
    if fmt not in _FORMATS:
        raise ValueError(f"unsupported format {format!r}; use one of {list(_FORMATS)}")
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"no such file: {path}")
    if circuit is not None and not str(circuit):
        raise ValueError("circuit name is empty; pass a name or omit it")
    if output is not None and not str(output):
        raise ValueError("output path is empty")
    if isinstance(scale, bool):
        raise ValueError("scale must be an integer, not a boolean")
    project = parse(p)
    name = circuit or project.main
    c = project.require_circuit(name)
    scale = max(1, min(4, int(scale)))

    scene = build_scene(project, c)
    if fmt == "png":
        data = scene_to_png(scene, scale=scale)
        width, height = scene.width(34), scene.height(34)
    else:
        data = scene_to_svg(scene, pad=34, title=f"{p.name} — circuit {name}").encode("utf-8")
        width, height = scene.width(34), scene.height(34)
    out_path = _fix_suffix(
        _default_output(p, name, name == project.main, fmt)
        if output is None
        else Path(output).expanduser(),
        fmt,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)

    result: dict[str, Any] = {
        "circuit": name,
        "path": str(out_path.resolve()),
        "format": fmt,
        "width": width,
        "height": height,
    }
    if fmt == "png":
        result["scale"] = scale
        # Device pixels are width/height times the PNG scale, so the file
        # dimensions are never a surprise next to the logical render size.
        result["pixel_width"] = width * scale
        result["pixel_height"] = height * scale
    elif include_image:
        result["note"] = "SVG cannot be embedded as image content; use format='png' with include_image=True."
    if fmt == "png" and include_image:
        return [Image(data=data, format="png"), result]
    return [result]
