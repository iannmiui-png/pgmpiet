#!/usr/bin/env python3
"""
pgmpiet.py -- a reference interpreter for pgmpiet, the grayscale
derivative of the Piet programming language.

pgmpiet programs are stored strictly as .pgm (Portable GrayMap) files,
in either ASCII (P2) or binary (P5) form.

Canonical palette (default; override with --black/--white/--header/--palette):

    0   -> header  (free passage, like white, but each time the pointer
                    lands on it the program's own literal PGM header
                    bytes -- magic number, comments, dimensions, maxval,
                    up to the start of pixel data -- are printed to
                    stdout. No stack command is executed.)
    33  -> black   (wall: the pointer cannot enter this codel)
    255 -> white   (free passage: the pointer slides through with no
                    command executed)
    112, 131, 141, 148, 155, 162, 170, 177, 184, 191, 198, 205,
    212, 219, 226, 233, 240, 247
        -> the 18 "coloured" steps, in canonical Piet hue-major
           order: light/normal/dark red, yellow, green, cyan, blue,
           magenta. Moving from step a to step b executes the same
           command as classic Piet's colour table at offset
           (b - a) mod 18.

Usage:
    python3 pgmpiet.py program.pgm
    python3 pgmpiet.py program.pgm --trace
    python3 pgmpiet.py program.pgm --codel-size 4
    python3 pgmpiet.py program.pgm --max-steps 5000000
"""

import sys
import argparse
from math import gcd

DEFAULT_PALETTE = [112, 131, 141, 148, 155, 162, 170, 177, 184, 191,
                    198, 205, 212, 219, 226, 233, 240, 247]
DEFAULT_BLACK = 33
DEFAULT_WHITE = 255
DEFAULT_HEADER = 0

# command executed for (new_step - old_step) mod 18, in classic Piet order
COMMAND_TABLE = [
    None,          # 0  no-op (never triggered between two distinct blocks)
    'push', 'pop',
    'add', 'subtract', 'multiply', 'divide', 'mod', 'not', 'greater',
    'pointer', 'switch',
    'duplicate', 'roll',
    'in_number', 'in_char', 'out_number', 'out_char',
]

DP_VECTORS = [(1, 0), (0, 1), (-1, 0), (0, -1)]  # right, down, left, up


def rotate_cw(dp, n):
    return (dp + n) % 4


def toggle_cc(cc, n):
    return cc if n % 2 == 0 else 1 - cc


# ---------------------------------------------------------------- parsing --

def read_pgm(path):
    with open(path, 'rb') as f:
        data = f.read()
    pos = 0

    def skip_ws_and_comments():
        nonlocal pos
        while True:
            while pos < len(data) and data[pos:pos + 1].isspace():
                pos += 1
            if pos < len(data) and data[pos:pos + 1] == b'#':
                while pos < len(data) and data[pos:pos + 1] != b'\n':
                    pos += 1
            else:
                return

    def read_token():
        nonlocal pos
        skip_ws_and_comments()
        start = pos
        while pos < len(data) and not data[pos:pos + 1].isspace():
            pos += 1
        return data[start:pos]

    magic = read_token()
    if magic not in (b'P2', b'P5'):
        raise ValueError(f"'{path}' is not a PGM file (magic={magic!r})")
    width = int(read_token())
    height = int(read_token())
    maxval = int(read_token())

    if magic == b'P2':
        skip_ws_and_comments()
        header_bytes = data[:pos]
        pixels = []
        while len(pixels) < width * height:
            pixels.append(int(read_token()))
    else:
        pos += 1  # single whitespace byte separating header from binary data
        header_bytes = data[:pos]
        if maxval < 256:
            pixels = list(data[pos:pos + width * height])
        else:
            raw = data[pos:pos + width * height * 2]
            pixels = [(raw[2 * i] << 8) | raw[2 * i + 1]
                      for i in range(width * height)]

    if len(pixels) != width * height:
        raise ValueError(f"'{path}': expected {width * height} pixels, "
                          f"found {len(pixels)}")

    grid = [pixels[y * width:(y + 1) * width] for y in range(height)]
    return width, height, maxval, grid, header_bytes


def detect_codel_size(width, height, grid):
    """Largest N such that the whole image is aligned to an N x N grid
    of uniform blocks -- i.e. gcd of every same-colour run length."""
    g = 0
    for y in range(height):
        run = 1
        for x in range(1, width):
            if grid[y][x] == grid[y][x - 1]:
                run += 1
            else:
                g = gcd(g, run)
                run = 1
        g = gcd(g, run)
    for x in range(width):
        run = 1
        for y in range(1, height):
            if grid[y][x] == grid[y - 1][x]:
                run += 1
            else:
                g = gcd(g, run)
                run = 1
        g = gcd(g, run)
    return g if g > 0 else 1


def downsample(width, height, grid, size):
    if size == 1:
        return width, height, grid
    nw, nh = width // size, height // size
    out = [[grid[y * size][x * size] for x in range(nw)] for y in range(nh)]
    return nw, nh, out


# --------------------------------------------------------------- classify --

class Palette:
    def __init__(self, black, white, steps, header=DEFAULT_HEADER):
        self.black = black
        self.white = white
        self.header = header
        self.steps = steps
        self.candidates = [('black', black), ('white', white), ('header', header)]
        self.candidates += [(i, v) for i, v in enumerate(steps)]

    def classify(self, gray):
        """Return 'black', 'white', 'header', or a step index
        0..len(steps)-1, snapping to the nearest defined level (exact
        match for a spec-conformant file)."""
        best = min(self.candidates, key=lambda kv: abs(kv[1] - gray))
        return best[0]


# ------------------------------------------------------------- block map --

def label_blocks(width, height, grid, palette):
    """4-connected flood fill over coloured (non black/white) codels.
    Returns block_id_at[y][x] (or None) and blocks: {id: [(x,y), ...]}."""
    block_id_at = [[None] * width for _ in range(height)]
    blocks = {}
    next_id = 0

    for y0 in range(height):
        for x0 in range(width):
            if block_id_at[y0][x0] is not None:
                continue
            cls = palette.classify(grid[y0][x0])
            if cls in ('black', 'white', 'header'):
                continue
            bid = next_id
            next_id += 1
            stack = [(x0, y0)]
            block_id_at[y0][x0] = bid
            coords = []
            while stack:
                x, y = stack.pop()
                coords.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < width and 0 <= ny < height and block_id_at[ny][nx] is None:
                        if palette.classify(grid[ny][nx]) == cls:
                            block_id_at[ny][nx] = bid
                            stack.append((nx, ny))
            blocks[bid] = coords
    return block_id_at, blocks


# ------------------------------------------------------------ interpreter --

class Halt(Exception):
    pass


class Interpreter:
    def __init__(self, width, height, grid, palette, header_bytes=b'',
                 max_steps=2_000_000, trace=False):
        self.w, self.h, self.grid, self.palette = width, height, grid, palette
        self.header_text = header_bytes.decode('latin-1')
        self.block_id_at, self.blocks = label_blocks(width, height, grid, palette)
        self.stack = []
        self.dp = 0   # 0 right, 1 down, 2 left, 3 up
        self.cc = 0   # 0 left, 1 right
        self.max_steps = max_steps
        self.trace = trace
        self.in_buf = None
        self.in_pos = 0
        self.dead_on_arrival = False
        # execution starts in whichever block contains codel (0,0), per spec
        # -- even if that codel is white/header (slide immediately) or
        # black (the program can never start moving at all).
        cls0 = palette.classify(grid[0][0])
        if cls0 == 'black':
            self.dead_on_arrival = True
            self.pos = (0, 0)
        elif cls0 in ('white', 'header'):
            pos = self._slide_free(0, 0)
            self.pos = pos if pos is not None else (0, 0)
            self.dead_on_arrival = pos is None
        else:
            self.pos = (0, 0)

    def in_bounds(self, x, y):
        return 0 <= x < self.w and 0 <= y < self.h

    def classify(self, x, y):
        return self.palette.classify(self.grid[y][x])

    def exit_codel(self, block_coords, dp, cc):
        dpx, dpy = DP_VECTORS[dp]
        # CC left = 90 deg CCW of dp, CC right = 90 deg CW of dp
        if cc == 0:
            ccx, ccy = dpy, -dpx        # CCW
        else:
            ccx, ccy = -dpy, dpx        # CW
        best = None
        best_key = None
        for (x, y) in block_coords:
            key = (x * dpx + y * dpy, x * ccx + y * ccy)
            if best_key is None or key > best_key:
                best_key = key
                best = (x, y)
        return best

    # ---- stdin helpers ----
    def _ensure_input(self):
        if self.in_buf is None:
            self.in_buf = sys.stdin.read()
            self.in_pos = 0

    def in_number(self):
        self._ensure_input()
        buf = self.in_buf
        i = self.in_pos
        while i < len(buf) and buf[i] in ' \t\r\n':
            i += 1
        j = i
        if j < len(buf) and buf[j] in '+-':
            j += 1
        start_digits = j
        while j < len(buf) and buf[j].isdigit():
            j += 1
        if j == start_digits:
            return None  # no number available; command is skipped
        val = int(buf[i:j])
        self.in_pos = j
        return val

    def in_char(self):
        self._ensure_input()
        if self.in_pos < len(self.in_buf):
            ch = self.in_buf[self.in_pos]
            self.in_pos += 1
            return ord(ch)
        return None

    # ---- command execution ----
    def execute(self, cmd, exiting_block_size):
        s = self.stack
        if cmd is None:
            return
        if cmd == 'push':
            s.append(exiting_block_size)
        elif cmd == 'pop':
            if s: s.pop()
        elif cmd == 'add':
            if len(s) >= 2:
                b, a = s.pop(), s.pop(); s.append(a + b)
        elif cmd == 'subtract':
            if len(s) >= 2:
                b, a = s.pop(), s.pop(); s.append(a - b)
        elif cmd == 'multiply':
            if len(s) >= 2:
                b, a = s.pop(), s.pop(); s.append(a * b)
        elif cmd == 'divide':
            if len(s) >= 2 and s[-1] != 0:
                b, a = s.pop(), s.pop(); s.append(a // b)
        elif cmd == 'mod':
            if len(s) >= 2 and s[-1] != 0:
                b, a = s.pop(), s.pop(); s.append(a % b)
        elif cmd == 'not':
            if s:
                v = s.pop(); s.append(1 if v == 0 else 0)
        elif cmd == 'greater':
            if len(s) >= 2:
                b, a = s.pop(), s.pop(); s.append(1 if a > b else 0)
        elif cmd == 'pointer':
            if s:
                n = s.pop(); self.dp = rotate_cw(self.dp, n)
        elif cmd == 'switch':
            if s:
                n = s.pop(); self.cc = toggle_cc(self.cc, n)
        elif cmd == 'duplicate':
            if s: s.append(s[-1])
        elif cmd == 'roll':
            if len(s) >= 2:
                rolls = s[-1]; depth = s[-2]
                if depth >= 0 and depth <= len(s) - 2:
                    s.pop(); s.pop()
                    if depth > 0:
                        section = s[len(s) - depth:]
                        k = rolls % depth
                        section = section[-k:] + section[:-k] if k else section
                        s[len(s) - depth:] = section
                # negative depth, or depth too large: command is ignored
                else:
                    pass
        elif cmd == 'in_number':
            v = self.in_number()
            if v is not None:
                s.append(v)
        elif cmd == 'in_char':
            v = self.in_char()
            if v is not None:
                s.append(v)
        elif cmd == 'out_number':
            if s:
                sys.stdout.write(str(s.pop()))
        elif cmd == 'out_char':
            if s:
                v = s.pop()
                try:
                    sys.stdout.write(chr(v))
                except (ValueError, OverflowError):
                    pass

    # ---- main loop ----
    def run(self):
        if self.dead_on_arrival:
            return
        steps = 0
        attempts = 0
        while True:
            steps += 1
            if steps > self.max_steps:
                raise Halt(f"exceeded max-steps ({self.max_steps}); "
                            "possible infinite loop")

            x, y = self.pos
            bid = self.block_id_at[y][x]
            block_coords = self.blocks[bid]
            old_step = self.classify(x, y)
            ex, ey = self.exit_codel(block_coords, self.dp, self.cc)
            dpx, dpy = DP_VECTORS[self.dp]
            nx, ny = ex + dpx, ey + dpy

            if not self.in_bounds(nx, ny) or self.classify_safe(nx, ny) == 'black':
                attempts += 1
                if attempts >= 8:
                    return
                if attempts % 2 == 1:
                    self.cc = toggle_cc(self.cc, 1)
                else:
                    self.dp = rotate_cw(self.dp, 1)
                continue

            cls = self.classify(nx, ny)
            if cls in ('white', 'header'):
                new_pos = self._slide_free(nx, ny)
                if new_pos is None:
                    return  # stuck in a white/header loop with no exit
                self.pos = new_pos
                attempts = 0
                continue

            # entering a new coloured block: execute the command
            new_step = cls
            delta = (new_step - old_step) % 18
            cmd = COMMAND_TABLE[delta]
            if self.trace:
                sys.stderr.write(
                    f"[{steps}] ({x},{y}) step{old_step}->step{new_step} "
                    f"d{delta}:{cmd} dp={self.dp} cc={self.cc} "
                    f"stack={self.stack}\n")
            self.execute(cmd, len(block_coords))
            self.pos = (nx, ny)
            attempts = 0

    def classify_safe(self, x, y):
        return self.classify(x, y)

    def _slide_free(self, x, y):
        """Slide through consecutive white/header codels in the current
        DP direction until a coloured codel is reached (returned), or the
        pointer gets stuck (returns None, meaning the program halts).
        Every header codel landed on -- including (x, y) itself -- prints
        the program's own PGM header text to stdout."""
        dp, cc = self.dp, self.cc
        visited = set()
        attempts = 0
        if self.classify(x, y) == 'header':
            sys.stdout.write(self.header_text)
        while True:
            if (x, y, dp, cc) in visited:
                return None
            visited.add((x, y, dp, cc))
            dpx, dpy = DP_VECTORS[dp]
            nx, ny = x + dpx, y + dpy
            if not self.in_bounds(nx, ny) or self.classify(nx, ny) == 'black':
                attempts += 1
                if attempts >= 8:
                    return None
                if attempts % 2 == 1:
                    cc = toggle_cc(cc, 1)
                else:
                    dp = rotate_cw(dp, 1)
                continue
            cls = self.classify(nx, ny)
            if cls in ('white', 'header'):
                if cls == 'header':
                    sys.stdout.write(self.header_text)
                x, y = nx, ny
                continue
            self.dp, self.cc = dp, cc
            return (nx, ny)


# ------------------------------------------------------------------- CLI --

def main():
    ap = argparse.ArgumentParser(description="pgmpiet reference interpreter")
    ap.add_argument('program', help="path to a .pgm pgmpiet program")
    ap.add_argument('--black', type=int, default=DEFAULT_BLACK,
                     help=f"gray value used as black/wall (default {DEFAULT_BLACK})")
    ap.add_argument('--white', type=int, default=DEFAULT_WHITE,
                     help=f"gray value used as white/passage (default {DEFAULT_WHITE})")
    ap.add_argument('--header', type=int, default=DEFAULT_HEADER,
                     help=f"gray value that prints the file's own PGM header "
                          f"(default {DEFAULT_HEADER})")
    ap.add_argument('--palette', type=str, default=None,
                     help="comma-separated list of the 18 step gray values, "
                          "in ascending canonical order (overrides default)")
    ap.add_argument('--codel-size', type=int, default=None,
                     help="pixels per codel; default auto-detects")
    ap.add_argument('--max-steps', type=int, default=2_000_000,
                     help="abort after this many pointer moves")
    ap.add_argument('--trace', action='store_true',
                     help="print each executed command to stderr")
    args = ap.parse_args()

    steps_palette = DEFAULT_PALETTE
    if args.palette:
        steps_palette = [int(v) for v in args.palette.split(',')]
        if len(steps_palette) != 18:
            ap.error("--palette must list exactly 18 values")

    width, height, maxval, grid, header_bytes = read_pgm(args.program)

    size = args.codel_size or detect_codel_size(width, height, grid)
    if size > 1:
        width, height, grid = downsample(width, height, grid, size)
    if args.trace:
        sys.stderr.write(f"[pgmpiet] {args.program}: {width}x{height} codels "
                          f"(codel size {size})\n")

    palette = Palette(args.black, args.white, steps_palette, header=args.header)
    interp = Interpreter(width, height, grid, palette, header_bytes=header_bytes,
                          max_steps=args.max_steps, trace=args.trace)
    try:
        interp.run()
    except Halt as e:
        sys.stderr.write(f"[pgmpiet] halted: {e}\n")
        sys.exit(1)


if __name__ == '__main__':
    main()
