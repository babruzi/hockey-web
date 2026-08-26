---
name: lang-python-testing
description: Use when creating, updating, running, or reviewing Python tests. Invoke for pytest patterns, coverage workflows, test structure, and verification steps.
status: experimental
---

# Python Testing

Actionable guidance for writing and verifying Python tests. Inherits coding standards and tool configuration from the `lang-python` skill — all code within tests must follow those conventions unless explicitly overridden below.

**Announce at start:** "Using lang-python-testing skill."

## When to Use

- Writing new Python tests
- Reviewing existing test code
- Running tests and interpreting results
- Measuring and improving code coverage
- Debugging test failures
- Structuring test directories for a project

## Tool Discovery

On first invocation, discover the project's test tooling.

Phase 1: Config files (stop at first match)
1. **CLAUDE.md / AGENTS.md** — look for test commands or "Testing" sections
2. **pyproject.toml** — `[tool.pytest.ini_options]`, `[tool.coverage]`, or `[project.scripts]` with test entries
3. **tox.ini / tox.toml** — `[testenv]` default or environments named `test`, `tests`, `py`
4. **noxfile.py** — sessions named `test`, `tests`
5. **CI pipeline files** — steps running test commands
6. **Makefile** — targets named `test`, `tests`, `check`

Phase 2: Environment (**MANDATORY** — always run regardless of Phase 1 results)
Check for a local virtual environment:
1. **Virtual environment** — `.venv/`, `venv/`, or `$VIRTUAL_ENV`; inspect installed packages via `pip list` or `pip freeze`

Do NOT skip Phase 2. Even if Phase 1 found config, the venv reveals what is actually installed and runnable.

See [references/test-tool-discovery.md](references/test-tool-discovery.md) for detailed extraction rules.

### Test Tool Roles

| Role | Examples | Fallback Default |
|------|----------|-----------------|
| Test runner | pytest, unittest, nose2, ward | `pytest` |
| Coverage | pytest-cov, coverage.py | `pytest --cov` |

### Inherited Tool Roles (from lang-python)

| Role | Examples | Ownership |
|------|----------|-----------|
| Linter | ruff check, flake8, pylint | lang-python Tool Discovery |
| Formatter | ruff format, black | lang-python Tool Discovery |
| Type checker | mypy, pyright | lang-python Tool Discovery |
| Python version | `requires-python` in pyproject.toml | lang-python Tool Discovery |

### After Discovery

1. **Announce** — "Discovered test tools: {role}: {tool} from {source}."
2. **Use discovered commands** for all test, coverage, and verification operations.
3. **If no test config found** — Fall back to pytest and notify: "No test configuration found. Using pytest. Consider adding `[tool.pytest.ini_options]` to pyproject.toml."
4. **For inherited tools** — If `lang-python` has not been invoked in this session, run its Tool Discovery procedure before verification steps requiring a linter or type checker.

### Verify Availability

```bash
which <discovered-test-runner> && <discovered-test-runner> --version
python3 -c "import pytest_cov" 2>/dev/null  # if coverage role uses pytest-cov
```

If a tool is not installed, inform the user and suggest installation.

## Reference Reading (Required Before Writing or Reviewing Tests)

Before writing new tests or producing any review findings, read every reference listed under "Code Review Checklist" below, plus the references in `lang-python` (which apply to test code too). Then, in your first reply, include a "Reference rules applied" section: one bullet per reference, citing the specific rule(s) from that file that informed your work. If a reference has no applicable rules for the code at hand, write "no applicable rules" — do not omit the bullet.

This section must precede any code or findings. If you cannot produce it, you have not read the references.

The inline checklist that follows is a summary, not an exhaustive list. Each linked reference contains additional rules not repeated here.

## Code Review Checklist

When reviewing test code, verify each of these. See [references/code-examples.md](references/code-examples.md) for detailed examples.

### Test Design

Read and enforce all rules in [references/code-examples.md](references/code-examples.md) — the items below are highlights only.

- [ ] **Behavioral tests** — Tests verify behavior of our code, not implementation details
- [ ] **No third-party testing** — Do not test behavior of third-party dependencies
- [ ] **One logical behavior per test** — Each test verifies a single thing
- [ ] **Real objects when cheap** — Mock only slow or external dependencies
- [ ] **Descriptive test names** — `test_<behavior>` pattern reveals intent

### Test Structure

Read and enforce all rules in [references/code-examples.md](references/code-examples.md) — the items below are highlights only.

- [ ] **Arrange-Act-Assert** — Clear separation of setup, action, and verification
- [ ] **No test interdependence** — Tests pass in any order
- [ ] **No shared mutable state** — Tests don't modify global state
- [ ] **Minimal setup** — Only set up what the test needs

### Overrides from lang-python

Read and enforce all rules in [references/code-examples.md](references/code-examples.md) — the items below are highlights only. For naming, layout, whitespace, and programming rules that apply to test code, also read and enforce all rules in the `lang-python` references: `references/pep8-naming.md`, `references/pep8-layout.md`, `references/pep8-whitespace.md`, and `references/pep8-programming.md`.

- [ ] **One-line docstrings only** — Tests use single-line docstrings per PEP 257
- [ ] **No Sphinx fields in test docstrings** — Plain description only
- [ ] **Functional style** — Prefer functions over test classes where possible
- [ ] **Modern type hint syntax** — Type hints use the most concise syntax supported by the project's minimum Python version (see lang-python for version rules)

## Test File Organization

### Directory Mapping

Tests live next to the code or under `tests/`. Map submodules to directories:

```
src/
└── package_name/
    ├── __init__.py
    ├── auth.py
    └── pipeline/
        ├── __init__.py
        ├── parser.py
        └── transform.py

tests/
├── test_auth.py
├── pipeline/
│   ├── test_parser.py
│   └── test_transform.py
└── util/
    └── helpers.py
```

### Rules

- One test file per source file
- `<package_name>.<sub1>.<sub2>` maps to `tests/<sub1>/test_<sub2>.py`
- Shared helpers go in `tests/util/`
- Submodule-specific helpers go in `tests/<submodule>/util/`

## Testing Patterns

See [references/code-examples.md](references/code-examples.md) for full examples.

### Test Naming

```python
# Good — describes behavior
def test_parse_returns_empty_list_for_blank_input(): ...
def test_connect_raises_on_invalid_host(): ...

# Bad — describes implementation
def test_parser_calls_split(): ...
def test_function_returns_true(): ...
```

### Test Docstrings

```python
def test_timeout_raises_after_threshold():
    """Connection attempt raises TimeoutError after configured threshold."""
    ...
```

One line only. No Sphinx fields. No multi-line docstrings.

### Code Sharing

Prefer native Python for sharing test utilities:

```python
# tests/util/builders.py
def build_user(name: str = "test", active: bool = True) -> User:
    """Create a User instance with sensible defaults."""
    return User(name=name, active=active, created=datetime.now())
```

Use pytest fixtures only to:
- Manage complex objects requiring setup and teardown
- Control scope (per-test, per-module, per-session)

```python
@pytest.fixture
def db_connection():
    """Provide a database connection, rolled back after each test."""
    conn = create_test_connection()
    yield conn
    conn.rollback()
    conn.close()
```

### Fixture Organization (`conftest.py`)

- `tests/conftest.py` — shared fixtures available to all test files
- `tests/<submodule>/conftest.py` — fixtures scoped to that submodule only
- Keep fixtures close to their consumers; avoid a monolithic root conftest
- Never import from `conftest.py` directly — pytest discovers it automatically
- Use `conftest.py` for hooks (`pytest_configure`, `pytest_collection_modifyitems`) and shared markers

## Anti-Patterns

| Anti-Pattern | Problem | Fix |
|--------------|---------|-----|
| Testing third-party behavior | Brittle, not our responsibility | Test our code's use of the dependency |
| Multiple assertions testing different behaviors | Unclear what failed | Split into separate tests |
| Fixtures for simple data | Over-engineering, harder to read | Use helper functions or inline |
| Mocking everything | Tests pass but code is broken | Use real objects when cheap |
| Test names like `test_1`, `test_it_works` | No signal on failure | Name the behavior being tested |
| Shared mutable state between tests | Order-dependent failures | Isolate per test |

## Verification Workflow

For each updated test file, run these steps in order. Fix issues before proceeding to the next step. See [references/test-commands.md](references/test-commands.md) for the full command reference.

### 1. Run Tests

```bash
<test-runner> tests/path/to/test_file.py -v
```

All tests must pass. Fix failures before continuing.

### 2. Verify Style

Run the project's discovered linter (from `lang-python` Tool Discovery) against the test file:

```bash
<discovered-linter> tests/path/to/test_file.py
```

Fix any style violations. If no linter was discovered, skip this step.

### 3. Measure Coverage

```bash
<test-runner> tests/path/to/test_file.py --cov=src/package_name/module --cov-branch --cov-report=term-missing
```

Target the project's configured coverage threshold (check `--cov-fail-under` in pytest config or `[tool.coverage.report] fail_under` in pyproject.toml). If no threshold is configured, aim for meaningful branch coverage of logic paths and document intentional exclusions with `# pragma: no cover`. If using coverage.py directly: `coverage run -m <test-runner> tests/path/to/test_file.py && coverage report`.

### 4. Run Static Analysis

Run the project's discovered type checker or static analysis tool against the test file:

```bash
<discovered-type-checker> tests/path/to/test_file.py
```

Fix any violations. If no type checker was discovered, skip this step.

## Performance Optimization

Use `<test-runner> --durations=10` to identify slow tests. See [references/debugging-tests.md](references/debugging-tests.md) for debugger commands and flag comparison.

| Issue | Solution |
|-------|----------|
| Slow fixtures repeated per test | Scope to `module` or `session` if safe |
| Network calls in tests | Mock with `unittest.mock.patch` |
| Large file I/O in tests | Use `tmp_path` fixture with minimal data |
| Expensive object creation | Use builder functions with defaults |

## Design Questions

When designing tests, ask:

1. **What behavior am I verifying?** — Not "what code am I covering"
2. **What's the simplest input that triggers this behavior?**
3. **What are the edge cases?** — Empty input, None, boundaries
4. **Is this testing our code or a dependency?**
5. **Will this test break if I refactor the implementation?** — If yes, test is too coupled

## Integration with Code Review

When a code review workflow encounters test files:

1. Run through Code Review Checklist above
2. Verify test names describe behavior
3. Check for over-testing and test duplication
4. Confirm coverage is measured

## Quick Reference

| Task | Resource |
|------|----------|
| Test commands | [references/test-commands.md](references/test-commands.md) |
| Debugging | [references/debugging-tests.md](references/debugging-tests.md) |
| Style check | `<discovered-linter> tests/` (via lang-python) |
| Static analysis | `<discovered-type-checker> tests/` (via lang-python) |

## Reflection Gate

Before marking complete, ask the user: "Would you like me to log insights to `docs/insights.md`?" If yes (or if the file already exists and has prior entries), append a row:

| Date | Skill | Worked Well | Unexpected | Do Differently |
|------|-------|-------------|------------|----------------|
| YYYY-MM-DD | lang-python-testing | _answer_ | _answer_ | _answer_ |

If declined or if the project has no `docs/` directory, skip silently.
