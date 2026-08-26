# PEP 8 — Whitespace in Expressions

Source: [PEP 8 — Whitespace in Expressions and Statements](https://peps.python.org/pep-0008/#whitespace-in-expressions-and-statements)

## Inside Brackets

**Rule:** No whitespace immediately inside parentheses, brackets, or braces.

```python
# Good
spam(ham[1], {eggs: 2})
foo = (0,)

# Bad
spam( ham[ 1 ], { eggs: 2 } )
foo = (0, )
```

## Before Commas, Semicolons, Colons

**Rule:** No whitespace immediately before a comma, semicolon, or colon.

```python
# Good
if x == 4: print(x, y); x, y = y, x

# Bad
if x == 4 : print(x , y) ; x , y = y , x
```

## Slice Colons

**Rule:** In slices, colons act as binary operators — equal amounts of space around them (usually none).

```python
# Good
ham[1:9], ham[1:9:3], ham[:9:3], ham[1::3]
ham[lower::step]
ham[lower+offset : upper+offset]

# Bad
ham[lower + offset:upper + offset]
ham[1: 9], ham[1 :9], ham[1:9 :3]
```

## Around Operators

**Rule:** Surround binary operators with a single space on each side. Exception: group higher-priority operators more tightly.

```python
# Good
x = 1
y = x + 1
z = x*2 + y*3  # tighter binding is acceptable
hypot = x*x + y*y

# Bad
x=1
y = x+1
z = x * 2+y * 3
```

## Function Annotations

**Rule:** Use normal colon rules and surround `->` with spaces.

```python
# Good
def munge(input: str) -> str:
    pass

def munge(sep: str = None) -> None:
    pass

# Bad
def munge(input:str) -> str:
    pass

def munge(input: str)->str:
    pass
```

## Default Values

**Rule:** No spaces around `=` when used for keyword arguments or default parameter values.

```python
# Good
def connect(host: str, port: int = 443) -> None:
    pass

connect(host="example.com", port=8080)

# Bad
def connect(host: str, port: int =443) -> None:
    pass

connect(host = "example.com", port = 8080)
```

**Rationale:** Distinguishes assignment (`x = 1`) from keyword/default syntax (`port=443`).

## Trailing Whitespace

**Rule:** Avoid trailing whitespace anywhere. It is invisible and can cause noise in diffs.

## Compound Statements

**Rule:** Generally discourage multiple statements on one line.

```python
# Good
if foo == "bar":
    do_something()

# Discouraged
if foo == "bar": do_something()

# Bad
if foo == "bar": do_something(); do_another()
```

**Rationale:** One statement per line aids debugging and diff readability.
