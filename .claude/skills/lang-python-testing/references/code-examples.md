# Python Testing Code Examples

Detailed code examples for the lang-python-testing skill.

## Basic Test Structure

### Functional Style (Preferred)

```python
def test_parse_returns_tokens_for_valid_input():
    """Valid input is split into expected tokens."""
    result = parse("hello world")

    assert result == ["hello", "world"]


def test_parse_returns_empty_list_for_blank_input():
    """Blank input produces an empty token list."""
    result = parse("")

    assert result == []


def test_parse_raises_on_none_input():
    """None input raises TypeError."""
    with pytest.raises(TypeError):
        parse(None)
```

### With Type Hints (Python 3.12)

```python
def test_build_query_includes_all_filters():
    """All provided filters appear in the generated query."""
    filters: dict[str, str] = {"status": "active", "region": "us-east"}

    query: str = build_query(filters)

    assert "status=active" in query
    assert "region=us-east" in query
```

## Mocking External Dependencies

### Patching a Network Call

```python
from unittest.mock import patch, Mock


def test_fetch_user_returns_parsed_response():
    """Successful API response is parsed into a User object."""
    mock_response = Mock()
    mock_response.json.return_value = {"id": 1, "name": "Alice"}
    mock_response.raise_for_status = Mock()

    with patch("package_name.client.get", return_value=mock_response):
        user = fetch_user(1)

    assert user.name == "Alice"
    assert user.id == 1


def test_fetch_user_raises_on_http_error():
    """HTTP 404 is raised as LookupError."""
    mock_response = Mock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Not Found", request=Mock(), response=Mock(status_code=404)
    )

    with patch("package_name.client.get", return_value=mock_response):
        with pytest.raises(LookupError, match="not found"):
            fetch_user(999)
```

### When NOT to Mock

```python
# Good — real objects are cheap and reliable
def test_user_full_name_concatenates_first_and_last():
    """Full name is first + last separated by a space."""
    user = User(first="Jane", last="Doe")

    assert user.full_name == "Jane Doe"


# Bad — unnecessary mock adds complexity without value
def test_user_full_name_with_mock():
    """Overly mocked test that doesn't verify real behavior."""
    user = Mock()
    user.full_name = "Jane Doe"
    assert user.full_name == "Jane Doe"  # Tests nothing
```

## Fixtures

### Simple Setup/Teardown

```python
@pytest.fixture
def temp_config(tmp_path: Path) -> Path:
    """Create a temporary config file with valid defaults."""
    config_path = tmp_path / "config.toml"
    config_path.write_text('[server]\nhost = "localhost"\nport = 8080\n')
    return config_path


def test_read_config_parses_valid_file(temp_config: Path):
    """Valid config file is parsed into expected dictionary."""
    result = read_config(str(temp_config))

    assert result["server"]["host"] == "localhost"
    assert result["server"]["port"] == 8080
```

### Scoped Fixture (Use Sparingly)

```python
@pytest.fixture(scope="module")
def db_connection():
    """Provide a module-scoped DB connection, closed after all tests."""
    conn = create_test_database()
    yield conn
    conn.drop()
    conn.close()
```

## Builder Functions (Preferred Over Fixtures for Data)

```python
# tests/util/builders.py
def build_order(
    item_count: int = 3,
    status: str = "pending",
    customer: str = "test-customer",
) -> Order:
    """Create an Order with sensible defaults for testing."""
    items = [build_item(index=i) for i in range(item_count)]
    return Order(items=items, status=status, customer=customer)


def build_item(index: int = 0, price: float = 9.99) -> Item:
    """Create an Item with sensible defaults for testing."""
    return Item(name=f"item-{index}", price=price)
```

Usage in tests:

```python
def test_order_total_sums_item_prices():
    """Order total is the sum of all item prices."""
    order = build_order(item_count=3)

    assert order.total == pytest.approx(29.97)


def test_cancel_order_sets_status_to_cancelled():
    """Cancelling a pending order sets its status."""
    order = build_order(status="pending")

    order.cancel()

    assert order.status == "cancelled"
```

## Parametrized Tests

```python
@pytest.mark.parametrize(
    ("input_value", "expected"),
    [
        ("hello", "HELLO"),
        ("", ""),
        ("already UPPER", "ALREADY UPPER"),
        ("mixed Case", "MIXED CASE"),
    ],
)
def test_normalize_uppercases_input(input_value: str, expected: str):
    """Input string is converted to uppercase."""
    assert normalize(input_value) == expected
```

## Testing Exceptions

```python
def test_withdraw_raises_on_insufficient_funds():
    """Withdrawing more than the balance raises InsufficientFunds."""
    account = Account(balance=100.0)

    with pytest.raises(InsufficientFunds, match="Requested 150.00.*available 100.00"):
        account.withdraw(150.0)


def test_withdraw_does_not_modify_balance_on_failure():
    """Failed withdrawal leaves balance unchanged."""
    account = Account(balance=100.0)

    with pytest.raises(InsufficientFunds):
        account.withdraw(150.0)

    assert account.balance == 100.0
```

## Coverage Interpretation

```
Name                          Stmts   Miss Branch BrPart  Cover   Missing
-------------------------------------------------------------------------
src/package_name/auth.py         42      3     12      2    90%   35-37, 42->45
src/package_name/pipeline.py     68      0     20      0   100%
-------------------------------------------------------------------------
TOTAL                           110      3     32      2    95%
```

- **Stmts** — Total executable statements
- **Miss** — Statements not executed by any test
- **Branch** — Total branch points (if/else, loops)
- **BrPart** — Branches only partially covered
- **Missing** — Line numbers or branch arrows not covered
