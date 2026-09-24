"""
Brainfuck-to-pgmpiet compiler with full loop support.

Layout (fixed, only 8 rows total regardless of loop count/nesting):
  row0: main program.
  row1: dedicated "approach" row -- one push-cell per unique x_body/
        x_after column (colour backward-derived so its Delta into that
        marker is exactly 'pointer'), white everywhere else.
  rows2-7: shared turn infrastructure for ALL loops. Since every [/]
        check-point and marker occupies a unique column (they're just
        sequential positions in row0), different loops' detours never
        collide even though they share these rows.

Skip-forward (from `[`, isZero=1): forced to start heading down (the
pointer rotates by exactly the popped 0/1 flag). Detour: turn down->
right (r=3, needs a 6-cell push+double+add chain), travel right via
white to just before the target column, turn right->up (r=1), climb
via white, arrive at the approach row exactly below the target,
final push+pointer lands on the target marker.

Loop-back (from `]`, flag=current!=0): same idea, but turn down->left
(r=1) and travel left.
"""
import sys
sys.path.insert(0, '.')
import pgmpiet as P

BLACK = P.DEFAULT_BLACK
WHITE = P.DEFAULT_WHITE
STEPS = P.DEFAULT_PALETTE
CMD = {'push':1,'pop':2,'add':3,'subtract':4,'multiply':5,'divide':6,'mod':7,
       'not':8,'greater':9,'pointer':10,'switch':11,'duplicate':12,'roll':13,
       'in_number':14,'in_char':15,'out_number':16,'out_char':17}

def col(step):
    return STEPS[step % 18]

def chain_deltas(r):
    """push_literal(r) + pointer, as a list of CMD deltas."""
    deltas = [CMD['push']]
    bits = bin(r)[2:]
    for b in bits[1:]:
        deltas.append(CMD['duplicate'])
        deltas.append(CMD['add'])
        if b == '1':
            deltas.append(CMD['push'])
            deltas.append(CMD['add'])
    deltas.append(CMD['pointer'])
    return deltas


class Compiler:
    def __init__(self, tape_size=300):
        self.T = tape_size
        self.row = [0]
        self.cur = 0

    def emit(self, delta):
        self.cur = (self.cur + delta) % 18
        self.row.append(self.cur)
        return len(self.row) - 1

    def emit_free(self):
        """Place a fresh pixel with no incoming Delta constraint (used
        right after a white gap); self.cur is whatever the caller set."""
        self.row.append(self.cur)
        return len(self.row) - 1

    def push_literal(self, n):
        self.emit(CMD['push'])
        bits = bin(n)[2:]
        for b in bits[1:]:
            self.emit(CMD['duplicate']); self.emit(CMD['add'])
            if b == '1':
                self.emit(CMD['push']); self.emit(CMD['add'])

    def init_tape(self):
        for _ in range(self.T):
            self.emit(CMD['push']); self.emit(CMD['not'])

    def gt(self):
        self.push_literal(self.T); self.push_literal(1); self.emit(CMD['roll'])

    def lt(self):
        self.push_literal(self.T); self.push_literal(self.T - 1); self.emit(CMD['roll'])

    def plus(self):
        self.push_literal(1); self.emit(CMD['add'])

    def minus(self):
        self.push_literal(1); self.emit(CMD['subtract'])

    def dot(self):
        self.emit(CMD['duplicate']); self.emit(CMD['out_char'])

    def comma(self):
        self.emit(CMD['pop']); self.emit(CMD['in_char'])

    def compile(self, bf_source):
        self.init_tape()
        open_stack = []
        self.loops = []  # {'x_open_ptr','x_body','x_close_ptr','x_after','depth'}
        self.max_depth = 0
        depth = 0
        for c in bf_source:
            if c == '>': self.gt()
            elif c == '<': self.lt()
            elif c == '+': self.plus()
            elif c == '-': self.minus()
            elif c == '.': self.dot()
            elif c == ',': self.comma()
            elif c == '[':
                depth += 1
                self.max_depth = max(self.max_depth, depth)
                self.emit(CMD['duplicate']); self.emit(CMD['not'])
                x_ptr = self.emit(CMD['pointer'])
                self.row.append('WHITE')
                self.cur = 0
                x_body = self.emit_free()
                open_stack.append({'x_open_ptr': x_ptr, 'x_body': x_body, 'depth': depth})
            elif c == ']':
                info = open_stack.pop()
                self.emit(CMD['duplicate']); self.emit(CMD['not']); self.emit(CMD['not'])
                x_ptr2 = self.emit(CMD['pointer'])
                self.row.append('WHITE')
                self.cur = 0
                x_after = self.emit_free()
                info['x_close_ptr'] = x_ptr2
                info['x_after'] = x_after
                self.loops.append(info)
                depth -= 1
        assert not open_stack, "unbalanced brackets"
        return self.row, self.loops


class GridBuilder:
    ROW_MAIN, ROW_APPROACH = 0, 1
    DEPTH_BUDGET = 12  # rows reserved per nesting depth for turn chains

    def turn_start_row(self, depth):
        return 3 + (depth - 1) * self.DEPTH_BUDGET

    def __init__(self, row, loops):
        self.row0 = row
        self.loops = loops
        self.width = len(row)
        self.cells = {}  # (x,y) -> gray value (int)

    def set(self, x, y, gray):
        self.cells[(x, y)] = gray
        self.width = max(self.width, x + 1)

    def build(self):
        # row0: main program (row0 entries are either int step values or
        # the string 'WHITE' for the fall-through gaps)
        for x, step in enumerate(self.row0):
            if step == 'WHITE':
                self.set(x, self.ROW_MAIN, WHITE)
            else:
                self.set(x, self.ROW_MAIN, col(step))

        approach_targets = {}  # column -> fixed marker colour (step)
        for lp in self.loops:
            approach_targets[lp['x_body']] = self.row0[lp['x_body']]
            approach_targets[lp['x_after']] = self.row0[lp['x_after']]

        for lp in self.loops:
            self._build_skip_forward(lp)
            self._build_loop_back(lp)

        # Final approach, per target column: row2 = free cell (climb's
        # white slide ends here, command-less), row1 = push cell (its
        # own exit fires push, using row2's size=1), row0 = the marker
        # itself (entered via pointer from row1). Both row1/row2 values
        # are derived BACKWARD from the marker's already-fixed colour.
        for x, marker_step in approach_targets.items():
            cell2 = (marker_step - CMD['pointer']) % 18
            cell1 = (cell2 - CMD['push']) % 18
            self.set(x, 2, col(cell1))
            self.set(x, 1, col(cell2))

        # fill remaining row1/row2 cells with white (horizontal/vertical
        # slide paths use whatever's left over)
        for y in (1, 2):
            for x in range(self.width):
                if (x, y) not in self.cells:
                    self.set(x, y, WHITE)

        return self._to_grid()

    def _lay_chain_vertical(self, x, y0, r, base_colour):
        """A white-entered cell first (its colour is `base_colour`,
        arbitrary -- no real Delta fires getting here), THEN the real
        push_literal(r)+pointer chain, whose deltas fire on each
        subsequent transition. Returns the row of the final (pointer)
        cell."""
        cur = base_colour
        self.set(x, y0, col(cur))
        y = y0 + 1
        for d in chain_deltas(r):
            cur = (cur + d) % 18
            self.set(x, y, col(cur))
            y += 1
        return y - 1

    def _lay_chain_horizontal(self, x0, y, r, direction, base_colour):
        """Same fix, horizontally: a white-entered free cell, then the
        real chain."""
        cur = base_colour
        self.set(x0, y, col(cur))
        x = x0 + direction
        for d in chain_deltas(r):
            cur = (cur + d) % 18
            self.set(x, y, col(cur))
            x += direction
        return x - direction

    def _white_vrange(self, x, y_from, y_to):
        lo, hi = sorted((y_from, y_to))
        for y in range(lo, hi + 1):
            if (x, y) not in self.cells:
                self.set(x, y, WHITE)

    def _white_hrange(self, y, x_from, x_to):
        lo, hi = sorted((x_from, x_to))
        for x in range(lo, hi + 1):
            if (x, y) not in self.cells:
                self.set(x, y, WHITE)

    def _build_skip_forward(self, lp):
        x_open = lp['x_open_ptr']
        x_target = lp['x_after']
        base_colour = self.row0[x_open]
        row_start = self.turn_start_row(lp['depth'])
        # descent from row3 down to row_start-1 passes through shallower
        # depths' row-bands, which default to black; must be explicitly
        # whited at this specific (unique) column.
        for y in range(3, row_start):
            if (x_open, y) not in self.cells:
                self.set(x_open, y, WHITE)
        # turn1: down -> right, r=3, at column x_open (free-entry + 6-cell chain)
        end_row = self._lay_chain_vertical(x_open, row_start, 3, base_colour)
        # turn2 (right -> up) now needs 3 cells (free-entry+push+pointer),
        # ending exactly at x_target, so it must START at x_target-2.
        t2_start = x_target - 2
        self._white_hrange(end_row, x_open + 1, t2_start - 1)
        self._lay_chain_horizontal(t2_start, end_row, 1, +1, 0)
        # climb white from just below the approach cells up to just above turn2
        self._white_vrange(x_target, 3, end_row - 1)

    def _build_loop_back(self, lp):
        x_close = lp['x_close_ptr']
        x_target = lp['x_body']
        base_colour = self.row0[x_close]
        row_start = self.turn_start_row(lp['depth'])
        for y in range(3, row_start):
            if (x_close, y) not in self.cells:
                self.set(x_close, y, WHITE)
        # turn1: down -> left, r=1, at column x_close (free-entry + 2-cell chain)
        end_row = self._lay_chain_vertical(x_close, row_start, 1, base_colour)
        # turn2 (left -> up), 3 cells, ending exactly at x_target, starts at x_target+2
        t2_start = x_target + 2
        self._white_hrange(end_row, t2_start + 1, x_close - 1)
        self._lay_chain_horizontal(t2_start, end_row, 1, -1, 0)
        # climb white
        self._white_vrange(x_target, 3, end_row - 1)

    def _colour_before(self, x, y):
        """Colour of whatever's immediately 'before' (x,y) in its own
        chain -- since (x,y) itself is about to be white (approached via
        slide), we just need *a* valid free starting colour; 0 is fine,
        it's never entered via a real Delta."""
        return 0

    def _peek(self, x, y):
        return self.cells.get((x, y))

    def _to_grid(self):
        H = max(y for (_, y) in self.cells) + 3
        W = self.width
        grid = [[BLACK] * W for _ in range(H)]
        for (x, y), v in self.cells.items():
            grid[y][x] = v
        return W, H, grid


def col_to_step(gray):
    return STEPS.index(gray) if gray in STEPS else None


def write_pgm(path, grid, W, H, last_colour):
    """Same L-shaped halting trap as hello.pgm (E entered via white, D
    below E, C left of D), but pushed a few extra columns past the
    program's own width so C's left-neighbour lands safely beyond the
    approach row's white-flooded zone (row1 is white for x < W to
    support the loop-approach mechanism; C needs a genuinely black
    neighbour, not an accidental white one one column short)."""
    PAD = 3
    x_white = W
    x_e = W + PAD
    W2 = x_e + 2
    H2 = H + 2
    new_grid = [[BLACK] * W2 for _ in range(H2)]
    for y in range(H):
        for x in range(W):
            new_grid[y][x] = grid[y][x]
    for x in range(x_white, x_e):
        new_grid[0][x] = WHITE
    new_grid[0][x_e] = col(last_colour)
    new_grid[1][x_e] = col(last_colour)      # D, below E
    new_grid[1][x_e - 1] = col(last_colour)  # C, left of D
    header = f"P5\n# pgmpiet P5\n{W2} {H2}\n255\n".encode('ascii')
    with open(path, 'wb') as f:
        f.write(header)
        for row in new_grid:
            f.write(bytes(row))


if __name__ == '__main__':
    import os
    arg = sys.argv[1] if len(sys.argv) > 1 else "++++++++[>++++++++<-]>."
    if os.path.isfile(arg):
        with open(arg) as f:
            bf = f.read()
        print(f"read program from {arg}")
    else:
        bf = arg
    T = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    c = Compiler(tape_size=T)
    row, loops = c.compile(bf)
    gb = GridBuilder(row, loops)
    W, H, grid = gb.build()
    last_colour = row[-1] if row[-1] != 'WHITE' else 0
    write_pgm('bf_test.pgm', grid, W, H, last_colour)
    print(f"compiled (T={T}), {len(loops)} loop(s) -> bf_test.pgm")
