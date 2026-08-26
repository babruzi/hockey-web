# Python Code Examples

Detailed code examples for the lang-python skill.

## Error Handling

### Basic Pattern

```python
def read_config(path: str) -> dict[str, str]:
    """Read configuration from a TOML file.

    :param path: Path to the configuration file.
    :returns: Parsed configuration as a dictionary.
    :raises FileNotFoundError: If the config file does not exist.
    :raises ValueError: If the file content is not valid TOML.
    """
    try:
        with open(path) as f:
            return tomllib.loads(f.read())
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"Invalid TOML in {path}: {e}") from e
```

### With Context Wrapping

```python
def fetch_user(user_id: int) -> User:
    """Fetch a user by ID from the remote service.

    :param user_id: The user's numeric identifier.
    :returns: The resolved user object.
    :raises LookupError: If the user cannot be found or the service fails.
    """
    try:
        response = client.get(f"/users/{user_id}")
        response.raise_for_status()
        return User.from_dict(response.json())
    except httpx.HTTPStatusError as e:
        raise LookupError(f"User {user_id} not found: {e.response.status_code}") from e
    except httpx.RequestError as e:
        raise LookupError(f"Service unreachable while fetching user {user_id}") from e
```

## Type Hints

### Python 3.12 Syntax

```python
# Preferred — built-in generics and union syntax
def process(items: list[str], fallback: str | None = None) -> dict[str, int]:
    ...

# Avoid — legacy typing module
from typing import List, Optional, Dict
def process(items: List[str], fallback: Optional[str] = None) -> Dict[str, int]:
    ...
```

### Protocols

```python
from typing import Protocol


class Serializable(Protocol):
    def to_dict(self) -> dict[str, str]: ...


def save(obj: Serializable, path: str) -> None:
    """Serialize and write an object to disk."""
    data = obj.to_dict()
    with open(path, "w") as f:
        json.dump(data, f)
```

## Docstring Examples

### One-Line

```python
def is_valid(token: str) -> bool:
    """Check whether the token is syntactically valid."""
    return TOKEN_PATTERN.match(token) is not None
```

### Multi-Line with Sphinx Fields

```python
class Pipeline:
    """Orchestrates a sequence of processing stages.

    Stages are executed in order. If any stage raises, the pipeline
    halts and propagates the exception.

    :param stages: Ordered list of callables to execute.
    :param strict: If True, treat warnings as errors.
    """

    def __init__(self, stages: list[Callable], strict: bool = False) -> None:
        self._stages = stages
        self._strict = strict
```

## Anti-Pattern Fixes

### Mutable Default Argument

```python
# Bad — shared mutable state
def append_item(item: str, target: list[str] = []) -> list[str]:
    target.append(item)
    return target

# Good — None sentinel
def append_item(item: str, target: list[str] | None = None) -> list[str]:
    if target is None:
        target = []
    target.append(item)
    return target
```

### String Building in Loops

```python
# Bad — O(n^2)
result = ""
for line in lines:
    result += line + "\n"

# Good — O(n)
result = "\n".join(lines) + "\n"
```

## Performance Patterns

### Generator vs List

```python
# Memory-heavy — builds full list
total = sum([compute(x) for x in large_dataset])

# Memory-efficient — generator expression
total = sum(compute(x) for x in large_dataset)
```

### Local Variable in Tight Loop

```python
# Slow — repeated attribute lookup
for item in items:
    self.container.registry.process(item)

# Faster — hoist lookup
process = self.container.registry.process
for item in items:
    process(item)
```
