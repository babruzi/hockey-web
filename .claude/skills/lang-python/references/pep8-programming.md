# PEP 8 — Programming Recommendations

Source: [PEP 8 — Programming Recommendations](https://peps.python.org/pep-0008/#programming-recommendations)

## None Comparisons

**Rule:** Always use `is` or `is not` to compare with `None`, never equality operators.

```python
# Good
if value is None:
    pass

if value is not None:
    pass

# Bad
if value == None:
    pass

if value != None:
    pass
```

**Rationale:** `None` is a singleton; identity comparison is both correct and faster.

## Boolean Comparisons

**Rule:** Do not compare boolean values with `==` or `is`.

```python
# Good
if greeting:
    pass

if not greeting:
    pass

# Bad
if greeting == True:
    pass

if greeting is True:
    pass
```

## Truthiness Checks

**Rule:** Use implicit truthiness for empty containers and None-like checks. Use explicit comparison only when you need to distinguish between `None`, `0`, `""`, and `[]`.

```python
# Good — check if sequence is non-empty
if items:
    process(items)

if not items:
    return

# Bad — unnecessary length check
if len(items) > 0:
    process(items)

if len(items) == 0:
    return
```

**Rationale:** Implicit truthiness is idiomatic and handles multiple falsy types uniformly.

## Membership Testing

**Rule:** Use `in` and `not in` operators.

```python
# Good
if name not in registry:
    pass

# Bad
if not name in registry:
    pass
```

## isinstance vs type()

**Rule:** Use `isinstance()` for type checks rather than `type()` comparison.

```python
# Good
if isinstance(obj, int):
    pass

# Also good — checking multiple types
if isinstance(obj, (int, float)):
    pass

# Bad
if type(obj) is int:
    pass
```

**Rationale:** `isinstance()` respects inheritance, which is the expected behavior.

## Exception Handling

**Rule:** Catch specific exceptions. Never use bare `except:`. Bind exceptions to a name and prefer minimal try blocks.

```python
# Good — specific, named, minimal
try:
    value = mapping[key]
except KeyError:
    return default

# Bad — bare except catches SystemExit, KeyboardInterrupt
try:
    risky_operation()
except:
    pass
```

## Return Statements

**Rule:** Be consistent — if any return in a function returns a value, all paths should explicitly return a value (`return None` rather than bare `return` or falling off the end).

## Context Managers

**Rule:** Use `with` statements for resource management whenever a context manager is available.

```python
# Good
with open(path) as f:
    data = f.read()

# Bad
f = open(path)
try:
    data = f.read()
finally:
    f.close()
```

**Rationale:** Context managers guarantee cleanup even when exceptions occur.

## Chained Comparisons

**Rule:** Use Python's chained comparisons for range checks.

```python
# Good
if 0 < x <= 10:
    pass

# Bad
if x > 0 and x <= 10:
    pass
```
