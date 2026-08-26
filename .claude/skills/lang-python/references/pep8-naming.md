# PEP 8 — Naming Conventions

Source: [PEP 8 — Naming Conventions](https://peps.python.org/pep-0008/#naming-conventions)

## Overriding Principle

**Rule:** Names that are visible to the user as public parts of the API should reflect usage rather than implementation.

## Modules and Packages

**Rule:** Modules should have short, all-lowercase names. Underscores are acceptable for readability. Packages should also be all-lowercase, preferably without underscores.

```python
# Good
import utilities
import my_module
import mypackage

# Bad
import MyModule
import my-module
```

## Classes

**Rule:** Use PascalCase (CapWords). Acronyms in class names should be all-caps (e.g., `HTTPClient`).

```python
# Good
class HTTPClient:
    pass

class DataProcessor:
    pass

# Bad
class data_processor:
    pass

class httpClient:
    pass
```

## Exceptions

**Rule:** Follow class naming (PascalCase) and add the suffix `Error` for exceptions that are errors.

```python
# Good
class ValidationError(Exception):
    pass

class ConnectionTimeoutError(IOError):
    pass
```

## Functions and Methods

**Rule:** Use `snake_case` — lowercase with words separated by underscores.

```python
# Good
def calculate_total(items: list[Item]) -> float:
    pass

# Bad
def calculateTotal(items: list[Item]) -> float:
    pass

def CalculateTotal(items: list[Item]) -> float:
    pass
```

## Constants

**Rule:** Use `UPPER_SNAKE_CASE` — all capitals with underscores separating words. Define at module level.

```python
# Good
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30.0
BASE_URL = "https://api.example.com"

# Bad
max_retries = 3
MaxRetries = 3
```

## Method and Instance Variable Naming

**Rule:** Use `snake_case`. Use one leading underscore for non-public methods/attributes. Use double leading underscore only to invoke name mangling (rarely needed).

```python
class Connection:
    def __init__(self, host: str) -> None:
        self.host = host           # public
        self._socket = None        # internal
        self.__secret = "key"      # name-mangled (avoid unless needed)

    def connect(self) -> None:     # public
        pass

    def _validate(self) -> bool:   # internal
        pass
```

## Dunder Names

**Rule:** "Magic" objects like `__init__`, `__repr__`, `__enter__` are defined by the language. Never invent new dunders — use them only as documented.

## Leading and Trailing Underscores

| Convention | Meaning |
|-----------|---------|
| `_single_leading` | Weak "internal use" indicator; not imported by `from M import *` |
| `single_trailing_` | Used to avoid conflicts with Python keywords (`class_`, `type_`) |
| `__double_leading` | Triggers name mangling in classes |
| `__double_both__` | "Dunder" — language-defined special attributes/methods |

## Type Variables

**Rule:** Use PascalCase, short names. Typically single letters or short descriptors.

```python
from typing import TypeVar

T = TypeVar("T")
KT = TypeVar("KT")  # key type
VT = TypeVar("VT")  # value type
```

## Avoid Single-Character Names

**Rule:** Never use `l` (lowercase L), `O` (uppercase O), or `I` (uppercase I) as single-character variable names — they are indistinguishable from digits in some fonts.

## Iteration Variable Naming

**Rule:** Use descriptive iteration variable names, especially in comprehensions and for-loops. When the iterable name implies a natural singular form, use it. Avoid single-character abbreviations that force the reader to mentally map the variable back to its source.

```python
# Good — the variable name communicates what each element represents
lines = [line.strip() for line in raw_lines]
results = {key: value for key, value in mapping.items()}
for path in file_paths:
    process(path)

# Bad — ambiguous single-letter variables reduce readability
lines = [l.strip() for l in raw_lines]
results = {k: v for k, v in mapping.items()}
for p in file_paths:
    process(p)
```

**Exception:** Single-character variables are acceptable for trivial numeric iteration (`for i in range(n)`) or well-established mathematical conventions in computational code (`x`, `y`, `z` for coordinates).
