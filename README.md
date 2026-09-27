<img width="9910" height="450" alt="99bottles" src="https://github.com/user-attachments/assets/236b2170-3798-4641-843c-5246d8a6f311" />

<br>https://esolangs.org/wiki/pgmpiet<br>

# interpreter for pgmpiet

usage:
```
python pgmpiet.py input.pgm
```

# bf to pgmpiet compiler

usage:
```
python pgmpiet_bf.py "bf source" [tape_size]
```

# kbfi.b generator 
this will generate kbfi.pgm (a brainfuck self-interpreter in pgmpiet)

usage:
```
python kbfi_pgmpiet.py
```

# piet2pgmpiet
converts .ppm piet programs to pgmpiet .pgm

usage:<br>
pietppm to pgmpiet P5 (binary pgm)
```
python3 piet2pgmpiet.py program.ppm program.pgm
```
pietppm to pgmpiet P2 (text pgm)
```
python3 piet2pgmpiet.py program.ppm program.pgm --p2
```
