"""5x7 bitmap font for PNG text rasterisation.

Column-encoded 5x7 glyphs for printable ASCII (codepoints 0x20..0x7E).
Each glyph is five bytes, one per column, bit 0 at the top row; rows 0-6
cover the cap height and row 7 is the descender. Derived from the classic
fixed-width font shipped with Adafruit-GFX-Library (``glcdfont.c``,
MIT license); unknown characters render as blank space.
"""

from __future__ import annotations

import re as _re

# 95 glyphs x 5 columns, low bit = top row. Hex digits only: whitespace
# tolerated, anything else stripped defensively.
_FONT_HEX_RAW = """
    000000000000005f00000007000700147f147f14242a7f2a122313086462
    36495620500008070300001c2241000041221c002a1c7f1c2a08083e0808
    00807030000808080808000060600020100804023e5149453e00427f4000
    72494949462141494d331814127f1027454545393c4a4949314121110907
    3649494936464949291e0000140000004034000000081422411414141414
    004122140802015909063e415d594e7c1211127c7f494949363e41414122
    7f4141413e7f494949417f090909013e414151737f0808087f00417f4100
    2040413f017f081422417f404040407f021c027f7f0408107f3e4141413e
    7f090909063e4151215e7f09192946264949493203017f01033f4040403f
    1f2040201f3f4038403f631408146303047804036159494d43007f414141
    0204081020004141417f0402010204404040404000030708002054547840
    7f284444383844444428384444287f385454541800087e090218a4a49c78
    7f0804047800447d40002040403d007f1028440000417f40007c04780478
    7c080404783844444438fc1824241818242418fc7c080404084854545424
    04043f44243c4040207c1c2040201c3c4030403c44281028444c9090907c
    4464544c440008364100000077000000413608000201020402
"""

_FONT_HEX = _re.sub("[^0-9a-fA-F]", "", _FONT_HEX_RAW)

_COLUMNS = bytes.fromhex(_FONT_HEX)


def glyph_columns(codepoint: int) -> bytes:
    """The five column bytes of ``codepoint`` (blanks when not covered)."""
    if 0x20 <= codepoint <= 0x7E:
        off = (codepoint - 0x20) * 5
        return _COLUMNS[off : off + 5]
    return b"\x00" * 5


def glyph_scale(size: float) -> int:
    """Bitmap font pixel size matching a text ``size``'s cap height."""
    return max(1, round(size / 8))


def advance(size: float) -> float:
    """Per-character advance distance for ``size``."""
    return size * 0.75
