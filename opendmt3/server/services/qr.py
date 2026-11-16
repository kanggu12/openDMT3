"""A QR code for the site's address, the invite a player scans: the admin's Players tab shows it, the API gives it
(GET /api/v1/server/invite), and the server's own command line prints it in a terminal (invite).

Plain Python, nothing to install: byte mode, error correction level M (a code still reads with about 15% of it
covered or smudged), versions 1 to 10 (up to 213 bytes, far more than an address needs), and the mask chosen by the
standard's four penalty rules, as ISO/IEC 18004 describes them.

    python -m opendmt3.server.services.qr http://192.168.0.5:4730/    (prints it with the terminal's block letters)
"""

import sys

# Per version, level M: (error correction bytes per block, [(blocks, data bytes per block), ...]) (ISO/IEC 18004,
# table 9). Every version's total is the number of bytes its modules hold.
BLOCKS = {1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]), 5: (24, [(2, 43)]),
          6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]), 9: (22, [(3, 36), (2, 37)]),
          10: (26, [(4, 43), (1, 44)])}
# The centres of each version's alignment patterns, on both axes (ISO/IEC 18004, annex E).
ALIGNMENT = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
             9: [6, 26, 46], 10: [6, 28, 50]}
# Level M's two bits in the format information.
LEVEL_M = 0b00
# The quiet zone around the code, in modules: the four the standard asks for, so a phone finds the code's edge.
QUIET = 4


class QRError(ValueError):
    """Text too long for the largest version kept here."""


# ---------------------------------------------------------------------------------------------- Reed-Solomon

def _gf_tables():
    """The field GF(256) with the standard's polynomial x^8 + x^4 + x^3 + x^2 + 1 (0x11D): exponents and logarithms."""
    exp, log = [0] * 512, [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    # Doubled, so a product's exponent needs no modulo.
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


EXP, LOG = _gf_tables()


def _multiply(a, b):
    """a times b in GF(256)."""
    return 0 if a == 0 or b == 0 else EXP[LOG[a] + LOG[b]]


def _generator(degree):
    """The generator polynomial (x - a^0)(x - a^1)...(x - a^(degree-1)), its coefficients from the highest power."""
    poly = [1]
    for i in range(degree):
        # Times (x + a^i): each coefficient moves up a power, plus a^i times itself.
        poly = [c ^ _multiply(p, EXP[i]) for c, p in zip(poly + [0], [0] + poly)]
    return poly


def error_correction(data, degree):
    """The `degree` error correction bytes of one block: the remainder of data * x^degree by the generator."""
    generator = _generator(degree)
    rest = list(data) + [0] * degree
    for i in range(len(data)):
        factor = rest[i]
        if factor:
            for j, g in enumerate(generator):
                rest[i + j] ^= _multiply(g, factor)
    return rest[len(data):]


# ---------------------------------------------------------------------------------------------- the bits

def version_for(data):
    """The smallest version whose data bytes hold `data` in byte mode (QRError when none does)."""
    for version in sorted(BLOCKS):
        capacity = sum(n * size for n, size in BLOCKS[version][1]) * 8
        # Mode (4 bits) and the length: 8 bits up to version 9, 16 from version 10 on.
        if 4 + (8 if version < 10 else 16) + 8 * len(data) <= capacity:
            return version
    raise QRError("%d bytes are too many for a QR code here (213 at most)" % len(data))


def codewords(data, version):
    """The data's bytes with their error correction, interleaved block by block as the symbol holds them."""
    degree, groups = BLOCKS[version]
    capacity = sum(n * size for n, size in groups)
    bits = [0, 1, 0, 0]
    # The byte mode's length field, then every byte, most significant bit first.
    for value, width in [(len(data), 8 if version < 10 else 16)] + [(b, 8) for b in data]:
        bits += [(value >> i) & 1 for i in range(width - 1, -1, -1)]
    # The terminator (up to four zero bits), then zeros to a whole byte.
    bits += [0] * min(4, capacity * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    stream = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    # The standard's two padding bytes, in turn, up to the data's whole room.
    pads = [0xEC, 0x11]
    while len(stream) < capacity:
        stream.append(pads[(len(stream) - len(bits) // 8) % 2])
    blocks, at = [], 0
    for n, size in groups:
        for _ in range(n):
            blocks.append(stream[at:at + size])
            at += size
    corrections = [error_correction(block, degree) for block in blocks]
    out = []
    # The data bytes column by column across the blocks (the longer blocks' last byte at the end), then the error
    # correction bytes the same way.
    for i in range(max(len(b) for b in blocks)):
        out += [b[i] for b in blocks if i < len(b)]
    for i in range(degree):
        out += [c[i] for c in corrections]
    return out


def _bch(value, generator, bits):
    """value followed by the remainder of value * x^bits divided by the generator (the format and version codes)."""
    rest = value << bits
    top = generator.bit_length() - 1
    for shift in range(rest.bit_length() - 1, top - 1, -1):
        if rest & (1 << shift):
            rest ^= generator << (shift - top)
    return (value << bits) | rest


# ---------------------------------------------------------------------------------------------- the symbol

class _Symbol:
    """The module grid of one version: dark modules (True) and which are the fixed patterns' (never masked)."""

    def __init__(self, version):
        self.version = version
        self.size = 17 + 4 * version
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.fixed = [[False] * self.size for _ in range(self.size)]
        self._patterns()

    def set(self, row, col, dark, fixed=True):
        self.dark[row][col] = dark
        self.fixed[row][col] = fixed

    def _patterns(self):
        size = self.size
        # The three finder patterns, each with its light separator around it.
        for top, left in ((0, 0), (0, size - 7), (size - 7, 0)):
            for r in range(-1, 8):
                for c in range(-1, 8):
                    row, col = top + r, left + c
                    if 0 <= row < size and 0 <= col < size:
                        ring = max(abs(r - 3), abs(c - 3))
                        self.set(row, col, ring != 2 and ring != 4)
        # The timing patterns between them, dark on even modules.
        for i in range(8, size - 8):
            self.set(6, i, i % 2 == 0)
            self.set(i, 6, i % 2 == 0)
        # The alignment patterns, but at the three corners a finder pattern takes (over the timing patterns
        # elsewhere: the two agree where they cross).
        centres = ALIGNMENT[self.version]
        last = len(centres) - 1
        for i, row in enumerate(centres):
            for j, col in enumerate(centres):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for r in range(-2, 3):
                    for c in range(-2, 3):
                        self.set(row + r, col + c, max(abs(r), abs(c)) != 1)
        # The format information's places (filled for each mask), and the dark module beside the lower finder.
        for i in range(9):
            self.fixed[8][i] = self.fixed[i][8] = True
        for i in range(8):
            self.fixed[8][size - 1 - i] = self.fixed[size - 1 - i][8] = True
        self.set(size - 8, 8, True)
        if self.version >= 7:
            # The version information, twice: 6 x 3 beside the upper right and the lower left finders.
            code = _bch(self.version, 0x1F25, 12)
            for i in range(18):
                bit = bool((code >> i) & 1)
                self.set(i // 3, size - 11 + i % 3, bit)
                self.set(size - 11 + i % 3, i // 3, bit)

    def place(self, data):
        """The codewords' bits in the standard's zigzag: two columns at a time from the right, up then down."""
        bits = [(byte >> i) & 1 for byte in data for i in range(7, -1, -1)]
        at, size = 0, self.size
        col = size - 1
        while col > 0:
            if col == 6:
                # The vertical timing pattern's column is skipped whole.
                col -= 1
            upward = ((size - 1 - col) // 2) % 2 == 0
            for i in range(size):
                row = size - 1 - i if upward else i
                for c in (col, col - 1):
                    if not self.fixed[row][c]:
                        # Past the last bit (the remainder bits), light.
                        self.dark[row][c] = bool(bits[at]) if at < len(bits) else False
                        at += 1
            col -= 2

    def format_bits(self, mask):
        """The format information for level M and this mask, in its two places."""
        code = _bch((LEVEL_M << 3) | mask, 0x537, 10) ^ 0x5412
        size = self.size
        for i in range(15):
            bit = bool((code >> i) & 1)
            # Around the upper left finder: down column 8 then along row 8 (skipping the timing pattern).
            if i < 6:
                self.dark[i][8] = bit
            elif i < 8:
                self.dark[i + 1][8] = bit
            else:
                self.dark[8][14 - i if i > 8 else 7] = bit
            # And split between the other two finders.
            if i < 8:
                self.dark[8][size - 1 - i] = bit
            else:
                self.dark[size - 15 + i][8] = bit


# The standard's eight masks: a module is flipped where the condition holds.
MASKS = [lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0,
         lambda r, c: (r + c) % 3 == 0, lambda r, c: (r // 2 + c // 3) % 2 == 0,
         lambda r, c: (r * c) % 2 + (r * c) % 3 == 0, lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
         lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0]


def penalty(grid):
    """The standard's four penalty scores of a masked symbol, summed: the lower, the easier it reads."""
    size, score = len(grid), 0
    lines = grid + [list(col) for col in zip(*grid)]
    for line in lines:
        # Rule 1: five or more modules of one colour in a row: 3, plus 1 for each beyond five.
        run, last = 0, None
        for module in line:
            if module == last:
                run += 1
            else:
                if run >= 5:
                    score += run - 2
                run, last = 1, module
        if run >= 5:
            score += run - 2
        # Rule 3: the finder's 1:1:3:1:1 with four light modules before or after: 40 each.
        text = "".join("1" if m else "0" for m in line)
        for pattern in ("10111010000", "00001011101"):
            at = text.find(pattern)
            while at != -1:
                score += 40
                at = text.find(pattern, at + 1)
    # Rule 2: each 2 x 2 block of one colour: 3.
    for r in range(size - 1):
        for c in range(size - 1):
            if grid[r][c] == grid[r][c + 1] == grid[r + 1][c] == grid[r + 1][c + 1]:
                score += 3
    # Rule 4: 10 for each 5% the dark share is away from half.
    dark = sum(sum(row) for row in grid)
    score += 10 * (abs(dark * 20 - size * size * 10) // (size * size))
    return score


def encode(text, mask=None):
    """The QR code of `text` (UTF-8) as rows of booleans, True dark, without the quiet zone. `mask` forces one of the
    eight masks (the tests compare with a reference); otherwise the one with the lowest penalty."""
    data = text.encode("utf-8")
    version = version_for(data)
    symbol = _Symbol(version)
    symbol.place(codewords(data, version))
    best = None
    for m in ([mask] if mask is not None else range(8)):
        grid = [[symbol.dark[r][c] ^ (not symbol.fixed[r][c] and MASKS[m](r, c)) for c in range(symbol.size)]
                for r in range(symbol.size)]
        # The format information goes in after the mask (it is never masked itself).
        saved = symbol.dark
        symbol.dark = grid
        symbol.format_bits(m)
        symbol.dark = saved
        score = penalty(grid)
        if best is None or score < best[0]:
            best = (score, grid)
    return best[1]


def svg(text, module=6):
    """The code as an SVG picture: dark modules as one path, on a white square with the quiet zone (a phone reads a
    QR code dark on light, whatever the page's theme)."""
    grid = encode(text)
    side = len(grid) + 2 * QUIET
    # One rectangle per run of dark modules in a row: a few hundred path steps, not a few thousand squares.
    steps = []
    for r, row in enumerate(grid):
        c = 0
        while c < len(row):
            if row[c]:
                start = c
                while c < len(row) and row[c]:
                    c += 1
                steps.append("M%d %dh%dv1h-%dz" % (start + QUIET, r + QUIET, c - start, c - start))
            else:
                c += 1
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {s} {s}" width="{p}" height="{p}" '
            'shape-rendering="crispEdges" role="img"><rect width="{s}" height="{s}" fill="#fff"/>'
            '<path fill="#000" d="{d}"/></svg>').format(s=side, p=side * module, d="".join(steps))


def terminal(text):
    """The code for a terminal, two rows of modules per line with the half-block letters, for light letters on a dark
    background (the Windows console's and most terminals' colours): a light module is a lit letter cell, a dark one
    is left blank, so the code shows dark on light as printed codes are."""
    grid = encode(text)
    side = len(grid) + 2 * QUIET
    # The quiet zone around it, light (False) like the code's light modules; one row more below, so the rows pair up
    # (the code's side is odd) and the last line still shows the whole zone.
    padded = [[False] * side for _ in range(QUIET)] + [[False] * QUIET + row + [False] * QUIET for row in grid] + [
        [False] * side for _ in range(QUIET + 1)]
    # Reverse video (ESC [7m) would depend on the terminal; plain letters instead: a full block is a light pair.
    glyph = {(False, False): "█", (False, True): "▀", (True, False): "▄", (True, True): " "}
    return "\n".join("".join(glyph[(padded[r][c], padded[r + 1][c])] for c in range(side))
                     for r in range(0, len(padded) - 1, 2))


if __name__ == "__main__":
    # The code of the address given, for a quick look on the server PC (./dmt3 invite and opendmt3-server invite
    # print it with the address).
    print(terminal(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4730/"))
