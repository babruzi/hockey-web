# PEP 8 — Code Layout

Source: [PEP 8 — Code Lay-out](https://peps.python.org/pep-0008/#code-lay-out)

## Indentation

**Rule:** Use 4 spaces per indentation level. Never mix tabs and spaces.

```python
# Good
def example():
    if condition:
        do_something()

# Good — continuation line aligned with delimiter
result = function_call(
    arg_one, arg_two,
    arg_three,
)

# Bad — under-indented
def example():
  if condition:
    do_something()
```

## Line Length

**Rule:** Limit all lines to 79 characters (code) or 72 characters (docstrings/comments). Teams may agree on 99 for code.

```python
# Good — break long expressions with backslash or parentheses
income = (gross_wages
          + taxable_interest
          + (dividends - qualified_dividends))

# Good — break before binary operator (W504)
total = (first_variable
         + second_variable
         - third_variable)
```

**Rationale:** Keeps code readable in side-by-side diffs and standard terminal widths.

## Blank Lines

**Rule:** Surround top-level definitions with two blank lines. Surround method definitions inside a class with one blank line.

```python
# Good
class MyClass:

    def method_one(self) -> None:
        pass

    def method_two(self) -> None:
        pass


def top_level_function() -> None:
    pass
```

**Rationale:** Visual separation signals logical boundaries.

## Imports

**Rule:** Imports are always at the top of the file, one per line, grouped in order: standard library, third-party, local. Separate groups with a blank line.

```python
# Good
import os
import sys

import httpx
import pydantic

from mypackage import helpers
from mypackage.models import User

# Bad — multiple imports on one line
import os, sys

# Bad — mixed groups without separation
import os
import httpx
from mypackage import helpers
```

**Rationale:** Predictable import ordering aids readability and prevents merge conflicts.

## Line Continuation

**Rule:** Prefer implicit continuation inside parentheses, brackets, or braces over backslash.

```python
# Good — implicit continuation
result = some_function(
    argument_one,
    argument_two,
    argument_three,
)

# Acceptable — backslash when no brackets available
with open("/path/to/file") as file_one, \
     open("/path/to/other") as file_two:
    pass
```

**Rationale:** Parenthesized continuation is less fragile (no trailing-space bugs).

## Closing Brackets

**Rule:** Closing bracket may line up under the first non-whitespace character of the last item, or under the first character of the construct.

```python
# Option 1 — lined up under first item
my_list = [
    1, 2, 3,
    4, 5, 6,
    ]

# Option 2 — lined up under construct
my_list = [
    1, 2, 3,
    4, 5, 6,
]
```
