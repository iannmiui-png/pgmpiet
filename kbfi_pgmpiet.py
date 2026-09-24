#!/usr/bin/env python3
"""
kbfi_pgmpiet.py -- standalone, dependency-free generator for a pgmpiet
compilation of Keymaker's brainfuck-in-brainfuck interpreter (kbfi.b).

No imports beyond the standard library, no companion files needed --
the interpreter's source and the whole compiler are embedded below.
Running it with no arguments writes kbfi.pgm: a ~104,000 x 460 pixel
pgmpiet program that is itself a general Brainfuck interpreter, reading
"program|input" from stdin.

WARNING: actually *running* the resulting kbfi.pgm through a Python
pgmpiet interpreter is extremely slow -- building the block map alone
takes well over a minute, and full execution of even a trivial guest
BF program is a many-hour undertaking. This script only generates the
image; it doesn't attempt to run it. If you have serious compute (a
fast native pgmpiet interpreter, ideally), this is the file to throw
at it.

Usage:
    python3 kbfi_pgmpiet.py                  # writes kbfi.pgm (T=1000)
    python3 kbfi_pgmpiet.py program.bf 500   # compile something else instead
"""
import sys, os

STEPS = [112,131,134,148,155,162,170,177,184,191,198,205,212,219,226,233,240,247]
BLACK, WHITE = 33, 255
CMD = {'push':1,'pop':2,'add':3,'subtract':4,'multiply':5,'divide':6,'mod':7,
       'not':8,'greater':9,'pointer':10,'switch':11,'duplicate':12,'roll':13,
       'in_number':14,'in_char':15,'out_number':16,'out_char':17}

def col(step): return STEPS[step % 18]
def chain_deltas(r):
    d = [CMD['push']]
    for b in bin(r)[3:]:
        d += [CMD['duplicate'], CMD['add']]
        if b == '1': d += [CMD['push'], CMD['add']]
    d.append(CMD['pointer'])
    return d

class Compiler:
    def __init__(self, tape_size=300):
        self.T, self.row, self.cur = tape_size, [0], 0

    def emit(self, delta):
        self.cur = (self.cur + delta) % 18
        self.row.append(self.cur)
        return len(self.row) - 1

    def emit_free(self):
        self.row.append(self.cur)
        return len(self.row) - 1

    def push_literal(self, n):
        self.emit(CMD['push'])
        for b in bin(n)[3:]:
            self.emit(CMD['duplicate']); self.emit(CMD['add'])
            if b == '1': self.emit(CMD['push']); self.emit(CMD['add'])

    def init_tape(self):
        for _ in range(self.T):
            self.emit(CMD['push']); self.emit(CMD['not'])

    def gt(self): self.push_literal(self.T); self.push_literal(1); self.emit(CMD['roll'])
    def lt(self): self.push_literal(self.T); self.push_literal(self.T - 1); self.emit(CMD['roll'])
    def plus(self): self.push_literal(1); self.emit(CMD['add'])
    def minus(self): self.push_literal(1); self.emit(CMD['subtract'])
    def dot(self): self.emit(CMD['duplicate']); self.emit(CMD['out_char'])
    def comma(self): self.emit(CMD['pop']); self.emit(CMD['in_char'])

    def compile(self, bf):
        self.init_tape()
        open_stack, self.loops, depth, self.max_depth = [], [], 0, 0
        for c in bf:
            if c == '>': self.gt()
            elif c == '<': self.lt()
            elif c == '+': self.plus()
            elif c == '-': self.minus()
            elif c == '.': self.dot()
            elif c == ',': self.comma()
            elif c == '[':
                depth += 1; self.max_depth = max(self.max_depth, depth)
                self.emit(CMD['duplicate']); self.emit(CMD['not'])
                x_ptr = self.emit(CMD['pointer'])
                self.row.append('WHITE'); self.cur = 0
                x_body = self.emit_free()
                open_stack.append({'x_open_ptr': x_ptr, 'x_body': x_body, 'depth': depth})
            elif c == ']':
                info = open_stack.pop()
                self.emit(CMD['duplicate']); self.emit(CMD['not']); self.emit(CMD['not'])
                x_ptr2 = self.emit(CMD['pointer'])
                self.row.append('WHITE'); self.cur = 0
                x_after = self.emit_free()
                info['x_close_ptr'], info['x_after'] = x_ptr2, x_after
                self.loops.append(info); depth -= 1
        return self.row, self.loops


class GridBuilder:
    ROW_MAIN, ROW_APPROACH, DEPTH_BUDGET = 0, 1, 12

    def __init__(self, row, loops):
        self.row0, self.loops, self.width, self.cells = row, loops, len(row), {}

    def turn_start_row(self, depth): return 3 + (depth - 1) * self.DEPTH_BUDGET
    def set(self, x, y, g): self.cells[(x, y)] = g; self.width = max(self.width, x + 1)

    def build(self):
        for x, step in enumerate(self.row0):
            self.set(x, self.ROW_MAIN, WHITE if step == 'WHITE' else col(step))
        targets = {}
        for lp in self.loops:
            targets[lp['x_body']] = self.row0[lp['x_body']]
            targets[lp['x_after']] = self.row0[lp['x_after']]
        for lp in self.loops:
            self._skip_forward(lp); self._loop_back(lp)
        for x, m in targets.items():
            c2 = (m - CMD['pointer']) % 18
            c1 = (c2 - CMD['push']) % 18
            self.set(x, 2, col(c1)); self.set(x, 1, col(c2))
        for y in (1, 2):
            for x in range(self.width):
                if (x, y) not in self.cells: self.set(x, y, WHITE)
        return self._to_grid()

    def _lay_v(self, x, y0, r, base):
        cur, y = base, y0
        self.set(x, y, col(cur)); y += 1
        for d in chain_deltas(r):
            cur = (cur + d) % 18; self.set(x, y, col(cur)); y += 1
        return y - 1

    def _lay_h(self, x0, y, r, dirn, base):
        cur, x = base, x0
        self.set(x, y, col(cur)); x += dirn
        for d in chain_deltas(r):
            cur = (cur + d) % 18; self.set(x, y, col(cur)); x += dirn
        return x - dirn

    def _wv(self, x, y0, y1):
        for y in range(min(y0,y1), max(y0,y1)+1):
            if (x, y) not in self.cells: self.set(x, y, WHITE)

    def _wh(self, y, x0, x1):
        for x in range(min(x0,x1), max(x0,x1)+1):
            if (x, y) not in self.cells: self.set(x, y, WHITE)

    def _skip_forward(self, lp):
        x_open, x_t = lp['x_open_ptr'], lp['x_after']
        base = self.row0[x_open]; rs = self.turn_start_row(lp['depth'])
        for y in range(3, rs):
            if (x_open, y) not in self.cells: self.set(x_open, y, WHITE)
        end = self._lay_v(x_open, rs, 3, base)
        t2 = x_t - 2
        self._wh(end, x_open + 1, t2 - 1)
        self._lay_h(t2, end, 1, +1, 0)
        self._wv(x_t, 3, end - 1)

    def _loop_back(self, lp):
        x_close, x_t = lp['x_close_ptr'], lp['x_body']
        base = self.row0[x_close]; rs = self.turn_start_row(lp['depth'])
        for y in range(3, rs):
            if (x_close, y) not in self.cells: self.set(x_close, y, WHITE)
        end = self._lay_v(x_close, rs, 1, base)
        t2 = x_t + 2
        self._wh(end, t2 + 1, x_close - 1)
        self._lay_h(t2, end, 1, -1, 0)
        self._wv(x_t, 3, end - 1)

    def _to_grid(self):
        H = max(y for _, y in self.cells) + 3
        W = self.width
        grid = [[BLACK] * W for _ in range(H)]
        for (x, y), v in self.cells.items(): grid[y][x] = v
        return W, H, grid


def write_pgm(path, grid, W, H, last_colour):
    PAD = 3
    x_white, x_e = W, W + PAD
    W2, H2 = x_e + 2, H + 2
    g = [[BLACK] * W2 for _ in range(H2)]
    for y in range(H):
        for x in range(W): g[y][x] = grid[y][x]
    for x in range(x_white, x_e): g[0][x] = WHITE
    g[0][x_e] = col(last_colour)
    g[1][x_e] = col(last_colour)
    g[1][x_e - 1] = col(last_colour)
    header = f"P5\n# pgmpiet P5\n{W2} {H2}\n255\n".encode('ascii')
    with open(path, 'wb') as f:
        f.write(header)
        for row in g: f.write(bytes(row))


KBFI_SOURCE = """;; Keymaker's brainfuck interpreter
;; a brainfuck interpreter written in brainfuck
;; the memory cells can hold any value from zero to infinity
;; written by Keymaker


>>+[>>[>]>+>,[>>++++[>++++++++<-]>[<<<[>+>+<<-]>[<+>-]>[<<->>[-]
]>-]<<<<->[<+>-[<->-[-[-[-[-[-[-[-[-[<+>-[-[-[-[<->-[-[-[-[-[-[-
[-[-[-[-[-[-[<+>-[<->-[<+>-[<->>>+++[>+++++++++<-]>+[<<<[>+>+<<-
]>[<+>-]>[<<->>[-]]>-]<<<[<+>-[<->-[<+>-[<->[-]]<[-<++>]>]]<[-<+
>]>]]<[-<++++++>]>]]]]]]]]]]]]]]]<[-<+++++>]>]<[-<++++++++>]>]<[
-<++++>]>]<[-<+++++++>]>]]]]]]]]]]<[-<+++>]>]]<[-<<[<]<->>[>]>]>
]<[-<<[<]<->>[>]>]<<[<]<]>>[>]>>>>>>+<<<<<<<[<]>[[<<[<]<<+>+>>[>
]>-]<<[<]<[>>[>]>+<<[<]<-]+<-[-[-[-[-[-[-[->->>[>]>[>]>>>>>[>[>>
]>>>]>>[<<<<+>>+>>-]<<[>>+<<-]>>>[<<<<+>+>>>-]<<<[>>>+<<<-]<[->>
>>>[<<<<<+>+>>>>-]<<<<[>>>>+<<<<-]<[<++++++++++>-]]>>>>>>[<<<<<<
+>+>>>>>-]<<<<<[>>>>>+<<<<<-]<[->>>>>>>[<<<<<<<+>+>>>>>>-]<<<<<<
[>>>>>>+<<<<<<-]<[<<++++++++++[>++++++++++<-]>>-]]<.[-]<<<[<<]>[
<<<<<[<<]>]<<[<]>[<+>-]<[<]<<]>[->>[>]>[>]>>>>>[>[>>]>>>]>[>>]<<
[->[-]>>>>[<<+>>->[<<+>>->[<<+>>-]>]>>>]<<<<<<<[<<]>[<<<<<[<<]>]
>[>>]<<]>>>>>[>[>>]>>>]<<<<<[<<]>[>[>>]<<[->>+<[>>+<<-]<<<]>->>+
<<<<<<<[<<]>]>+>>>>>[>[>>]>>>]>,[>+>+<<-]>[<+>-]>[[>+>+<<-]>>[<<
+>>-]<[-<->[-<->[-<->[-<->[-<->[-<->[-<->[-<->[-<->[[-]<-><<<---
------->+>>]]]]]]]]]]<]<[>+>+<<-]>[<+>-]>[-[-[-[-[-[-[-[-[-[-<<-
--------->+>[-[-[-[-[-[-[-[-[-[[-]<<---------->+>]]]]]]]]]]]]]]]
]]]]]<<[>>+>+<<<-]>>[<<+>>-]+>[<<<+>>->[-]]<[-<[>+>+<<-]>[<+>-]>
[<<<+>>>[-]]<]<[>+>+<<-]>[<+>-]>[<<+>>[-]]<<<<+[-[<<<<<<[<<]>[<<
<<<[<<]>]>[>>]<+>>>>[>[>>]>>>]>-]>[>]<[[>+<-]<]<<<<<<[<<]>[>[>>]
<<[>[>>+<<-]>+<<-<<]>->>+<<<<<<<[<<]>]>[>>]+>>>>>[>[>>]>>>]>]<<<
<<<[<<]>[<<<<<[<<]>]>[>>]<<->>>>>[<<+>>->[<<+>>->[<<+>>-]>]>>>]<
<<<<<<[<<]>[<<<<<[<<]>]<<<<<[<<]>[<<<<<[<<]>]<<[<]>[<+>-]<[<]<]<
]>[->>[>]>[>]>>>>>[>[>>]>>>]+>[>>]>>>[-]>[-]+<<<<<<[<<]>[<<<<<[<
<]>]<<[<]>[<+>-]<[<]<]<]>[->>[>]>[>]>>>>>[>[>>]>>>]+<<<<<[<<]>-<
<<<<[<<]>[<<<<<[<<]>]<<[<]>[<+>-]<[<]<]<]>[->>[>]>[>]>>>>>[>[>>]
>>>]>[->[<<<[<<]<<+>+>>>[>>]>-]<<<[<<]<[>>>[>>]>+<<<[<<]<-]+<[[-
]>->>>[>>]>-<+[<<]<<]>[->>>[>>]>+++++++++<<<[<<]<]>>>[>>]+>>]<<-
<<<<[>>>>+>+<<<<<-]>>>>[<<<<+>>>>-]>[-<<[>+>+<<-]>[<+>-]>>+<[[-]
>-<]>[-<<<<->[-]>>>>[<<+>>->[<<+>>->[<<+>>-]>]>>>]<<<<<<<[<<]>[<
<<<<[<<]>]>[>>]>>]<]<<<[<<]<<<<[<<]>[<<<<<[<<]>]<<[<]>[<+>-]<[<]
<]<]>[->>[>]>[>]>>>>>[>[>>]>>>]>>+<[->[<<<[<<]<<+>+>>>[>>]>-]<<<
[<<]<[>>>[>>]>+<<<[<<]<-]<[-[-[-[-[-[-[-[-[-[->>>>[>>]>[-]>[-]+>
+<<<<<[<<]<<]]]]]]]]]]>>>>[>>]+>>]>[-<<<[<<]<<+>+>>>[>>]>]<<<[<<
]<[>>>[>>]>+<<<[<<]<-]<[->>>>[>>]>[>[>>]<<[>[>>+<<-]>+<<-<<]>->>
+>[>>]>]<<<[<<]>[<<<<<[<<]>]<<<]<<[<<]>[<<<<<[<<]>]<<[<]>[<+>-]<
[<]<]<]>[->>[>]>[>]>>>>>[>[>>]>>>]>[>>]>>>[>[>>]>>>]>+[<<<<<<[<<
]>[<<<<<[<<]>]<<<<<[<<]>[<<<<<[<<]>]<<[<]<[>+<-]>[<<[<]<<+>+>>[>
]>-]<<[<]<[>>[>]>+<<[<]<-]+<-[-[>-<[-]]>[->>[>]>[>]>>>>>[>[>>]>>
>]>[>>]>>>[>[>>]>>>]>[>]+[<]<<<<<[<<]>[<<<<<[<<]>]<<<<<[<<]>[<<<
<<[<<]>]<<[<]<[<]<]<]>[->>[>]>[>]>>>>>[>[>>]>>>]>[>>]>>>[>[>>]>>
>]>[>]<-<[<]<<<<<[<<]>[<<<<<[<<]>]<<<<<[<<]>[<<<<<[<<]>]<<[<]<[<
]<]>>[>]>[>]>>>>>[>[>>]>>>]>[>>]>>>[>[>>]>>>]>]<<<<<<[<<]>[<<<<<
[<<]>]<<<<<[<<]>[<<<<<[<<]>]<<[<]<[<]<]<]>[->>[>]>[>]>>>>>[>[>>]
>>>]>>[<<<+>+>>-]<<[>>+<<-]>>>[<<<<+>+>>>-]<<<[>>>+<<<-]<<+>[[-]
<-<<<[<<]>[<<<<<[<<]>]<<[<]>[<+>-]>[>]>>>>>[>[>>]>>>]<]<[->>>[>>
]>>>[>[>>]>>>]>+[<<<<<<[<<]>[<<<<<[<<]>]<<<<<[<<]>[<<<<<[<<]>]<<
[<]>[<+>-]>[<<[<]<<+>+>>[>]>-]<<[<]<[>>[>]>+<<[<]<-]+<-[-[>-<[-]
]>[->>[>]>[>]>>>>>[>[>>]>>>]>[>>]>>>[>[>>]>>>]>[>]<-<[<]<<<<<[<<
]>[<<<<<[<<]>]<<<<<[<<]>[<<<<<[<<]>]<<[<]<[<]<]<]>[->>[>]>[>]>>>
>>[>[>>]>>>]>[>>]>>>[>[>>]>>>]>[>]+[<]<<<<<[<<]>[<<<<<[<<]>]<<<<
<[<<]>[<<<<<[<<]>]<<[<]<[<]<]>>[>]>[>]>>>>>[>[>>]>>>]>[>>]>>>[>[
>>]>>>]>]<<<<<<[<<]>[<<<<<[<<]>]<<<<<[<<]>[<<<<<[<<]>]<<[<]>[<+>
-]>[>]>>>>>[>[>>]>>>]<<]<<<[<<]>[<<<<<[<<]>]<<[<]<[<]<]>>[>]>]"""


if __name__ == '__main__':
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        bf = open(arg).read() if os.path.isfile(arg) else arg
        T = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
        out = 'bf_test.pgm'
    else:
        bf, T, out = KBFI_SOURCE, 1000, 'kbfi.pgm'

    c = Compiler(tape_size=T)
    row, loops = c.compile(bf)
    gb = GridBuilder(row, loops)
    W, H, grid = gb.build()
    last = row[-1] if row[-1] != 'WHITE' else 0
    write_pgm(out, grid, W, H, last)
    print(f"wrote {out}: {W+5}x{H+2}, {len(loops)} loop(s), max depth {c.max_depth}")
