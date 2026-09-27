#!/usr/bin/env python3
"""
piet2pgmpiet.py -- convert a Piet program (PPM, P3 or P6) to pgmpiet (PGM).

The substitution is one-to-one: each of Piet's 20 canonical colours maps
to its pgmpiet grey, preserving hue/lightness order, so every colour
transition (and so every command) is unchanged. Codel size is untouched.

Usage:
    python3 piet2pgmpiet.py input.ppm output.pgm [--p2] [--unknown white|black]

--p2         write ASCII PGM (P2) instead of binary (P5)
--unknown    how to treat non-canonical colours (default: white, as most
             Piet interpreters do)
"""
import sys

PIET_ORDER = [
    (255, 192, 192), (255, 0, 0), (192, 0, 0),      # light / normal / dark red
    (255, 255, 192), (255, 255, 0), (192, 192, 0),  # yellow
    (192, 255, 192), (0, 255, 0), (0, 192, 0),      # green
    (192, 255, 255), (0, 255, 255), (0, 192, 192),  # cyan
    (192, 192, 255), (0, 0, 255), (0, 0, 192),      # blue
    (255, 192, 255), (255, 0, 255), (192, 0, 192),  # magenta
]
GRAY_STEPS = [112, 131, 134, 148, 155, 162, 170, 177, 184,
              191, 198, 205, 212, 219, 226, 233, 240, 247]
BLACK, WHITE = 33, 255

MAPPING = dict(zip(PIET_ORDER, GRAY_STEPS))
MAPPING[(0, 0, 0)] = BLACK
MAPPING[(255, 255, 255)] = WHITE


def read_ppm(path):
    data = open(path, 'rb').read()
    pos = 0

    def token():
        nonlocal pos
        while True:
            while pos < len(data) and data[pos] in b' \t\r\n':
                pos += 1
            if pos < len(data) and data[pos] == ord('#'):
                while pos < len(data) and data[pos] != ord('\n'):
                    pos += 1
            else:
                break
        start = pos
        while pos < len(data) and data[pos] not in b' \t\r\n':
            pos += 1
        return data[start:pos]

    magic = token()
    if magic not in (b'P3', b'P6'):
        raise ValueError('not a PPM file (magic %r)' % magic)
    w, h, maxval = int(token()), int(token()), int(token())
    n = w * h * 3
    if magic == b'P6':
        pos += 1  # single whitespace byte after maxval
        if maxval < 256:
            vals = list(data[pos:pos + n])
        else:
            raw = data[pos:pos + 2 * n]
            vals = [(raw[i] << 8) | raw[i + 1] for i in range(0, 2 * n, 2)]
    else:
        vals = [int(token()) for _ in range(n)]
    if len(vals) < n:
        raise ValueError('truncated pixel data')
    if maxval != 255:  # normalise to 8-bit
        vals = [round(v * 255 / maxval) for v in vals]
    pixels = [tuple(vals[i:i + 3]) for i in range(0, n, 3)]
    return w, h, pixels


def convert(pixels, unknown):
    fallback = WHITE if unknown == 'white' else BLACK
    out, bad = [], {}
    for rgb in pixels:
        g = MAPPING.get(rgb)
        if g is None:
            bad[rgb] = bad.get(rgb, 0) + 1
            g = fallback
        out.append(g)
    return out, bad


def write_pgm(path, w, h, grays, ascii_p2):
    if ascii_p2:
        lines = ['P2', '# pgmpiet P2', '%d %d' % (w, h), '255']
        for y in range(h):
            lines.append(' '.join(str(v) for v in grays[y * w:(y + 1) * w]))
        with open(path, 'w', newline='\n') as f:
            f.write('\n'.join(lines) + '\n')
    else:
        with open(path, 'wb') as f:
            f.write(('P5\n# pgmpiet P5\n%d %d\n255\n' % (w, h)).encode('ascii'))
            f.write(bytes(grays))


def main(argv):
    args = [a for a in argv[1:] if not a.startswith('--')]
    ascii_p2 = '--p2' in argv
    unknown = 'white'
    if '--unknown' in argv:
        unknown = argv[argv.index('--unknown') + 1]
        args = [a for a in args if a != unknown]
        if unknown not in ('white', 'black'):
            sys.exit('--unknown must be white or black')
    if len(args) != 2:
        sys.exit(__doc__)
    src, dst = args
    w, h, pixels = read_ppm(src)
    grays, bad = convert(pixels, unknown)
    write_pgm(dst, w, h, grays, ascii_p2)
    print('converted %s -> %s (%dx%d, %s)' % (src, dst, w, h, 'P2' if ascii_p2 else 'P5'))
    if bad:
        print('note: %d non-canonical colour(s) treated as %s:' % (len(bad), unknown), file=sys.stderr)
        for rgb, count in sorted(bad.items(), key=lambda kv: -kv[1])[:10]:
            print('  rgb%s x%d' % (rgb, count), file=sys.stderr)


if __name__ == '__main__':
    main(sys.argv)
