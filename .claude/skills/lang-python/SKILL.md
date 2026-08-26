---
name: lang-python
description: Use when developing, reviewing, or debugging Python code. Invoke for Python-specific patterns, idioms, type hints, docstrings, and PEP compliance.
status: experimental
---

# Python Development

Actionable guidance for Python development workflows including code review, formatting, debugging, and design patterns.

**Announce at start:** "Using lang-python skill."

## When to Use

- Writing new Python code
- Reviewing Python code for style and correctness
- Debugging Python applications
- Optimizing Python performance
- Designing Python classes or modules
- Enforcing [PEP 8](https://peps.python.org/pep-0008/), PEP 257, type hints, and Sphinx docstrings

## Tool Discovery

On first invocation, discover the project's Python tooling.

Phase 1: Config files (stop at first match)
1. **CLAUDE.md / AGENTS.md** in the project root
2. **pyproject.toml** — `[tool.*]` sections
3. **tox.ini / tox.toml** — lint/format/type-check environments
4. **noxfile.py** — session definitions
5. **CI pipeline files** — `.github/workflows/*.yml` or `.gitlab-ci.yml`
6. **Makefile** — lint/format/check targets

Phase 2: Environment (**MANDATORY** — always run regardless of Phase 1 results)
Check for a local virtual environment:
1. **Virtual environment** — `.venv/`, `venv/`, or `$VIRTUAL_ENV`; inspect installed packages via `pip list` or `pip freeze`

Do NOT skip Phase 2. Even if Phase 1 found config, the venv reveals what is actually installed and runnable.

See [references/tool-discovery.md](references/tool-discovery.md) for detailed extraction rules.

### Tool Roles

| Role | Examples | Fallback Default |
|------|----------|-----------------|
| Linter | ruff check, flake8, pylint | `flake8 src/ tests/` |
| Formatter | ruff format, black, autopep8 | _(none)_ |
| Type checker | mypy, pyright, pytype | _(none)_ |
| Debugger | pdb, ipdb, pudb | `python3 -m pdb` |
| Profiler | cProfile, py-spy, scalene | `python3 -m cProfile -s cumulative` |
| Python version | `requires-python` in pyproject.toml, CI matrix | 3.10 (assumed) |

### Python Version Discovery

Extract `requires-python` from `[project]` in `pyproject.toml`. Parse the minimum version (e.g., `>=3.9` → 3.9). If not found, check `python_requires` in `setup.cfg` or the CI test matrix for the lowest version. Use this to gate type hint syntax recommendations throughout the session.

### After Discovery

1. **Announce** — "Discovered tools: {role}: {tool} from {source}."
2. **Use discovered commands** for all lint, format, and type-check operations.
3. **If no config found** — Fall back to defaults and notify: "No project tool configuration found. Using defaults. Consider adding tool config to pyproject.toml or CLAUDE.md."
4. **Offer to persist** — If tools were discovered from pyproject.toml/tox/CI but not CLAUDE.md, offer to add a `## Python Tools` section to the project's CLAUDE.md with the discovered commands.

### Verify Availability

```bash
which python3 && python3 --version
which <discovered-linter>
which <discovered-formatter>    # if found
which <discovered-type-checker> # if found
```

If a tool is not installed, inform the user and suggest installation.

## Reference Reading (Required Before Writing or Reviewing Code)

Before writing new Python code or producing any review findings, read every reference listed under "Code Review Checklist" below. Then, in your first reply, include a "Reference rules applied" section: one bullet per reference, citing the specific rule(s) from that file that informed your work. If a reference has no applicable rules for the code at hand, write "no applicable rules" — do not omit the bullet.

This section must precede any code or findings. If you cannot produce it, you have not read the references.

The inline checklist that follows is a summary, not an exhaustive list. Each linked reference contains additional rules not repeated here.

## Code Review Checklist

When reviewing Python code, verify each of these. See [references/code-examples.md](references/code-examples.md) for detailed examples.

### Error Handling

- [ ] **Errors are handled** — Every exception is caught or propagated intentionally
- [ ] **Error messages are descriptive** — Include context for debugging
- [ ] **No bare `except:`** — Always catch specific exceptions
- [ ] **No silent failures** — Exceptions are logged or re-raised

### Naming Conventions

Read and enforce all rules in [references/pep8-naming.md](references/pep8-naming.md) — the items below are highlights only.

- [ ] **snake_case** for functions, methods, variables, modules
- [ ] **PascalCase** for classes
- [ ] **UPPER_SNAKE_CASE** for module-level constants
- [ ] **Descriptive names** — Names reveal intent
- [ ] **Descriptive iteration variables** — Use `line for line in lines`, not `l for l in lines`
- [ ] **No shadowing** — Names don't hide builtins or outer scope variables

### Type Hints

- [ ] **All function signatures have type hints** — Parameters and return types
- [ ] **Variables typed where not obvious** — Complex assignments are annotated
- [ ] **Modern type hint syntax** — Use the most concise syntax supported by the project's minimum Python version: 3.10+ uses `X | None` and `list[str]`; 3.9+ uses `list[str]` but `Optional[X]` for unions; 3.8 and below uses `List[str]` and `Optional[X]`. If no minimum version is discoverable, default to 3.10+ syntax.
- [ ] **No `Any` without justification** — Explicit types preferred

### Docstrings

- [ ] **Every public module, class, method, and function has a docstring**
- [ ] **Triple double quotes** (`"""`) used
- [ ] **Sphinx format** for fields (`:param:`, `:returns:`, `:raises:`)
- [ ] **No type duplication** — Types come from hints, not docstring fields
- [ ] **One-line docstrings** on single line; multi-line have summary, blank line, body

### Code Organization

- [ ] **Single responsibility** — Functions and classes do one thing
- [ ] **Minimal imports** — Only import what's needed
- [ ] **Logical grouping** — Related code is together
- [ ] **No circular imports** — Module dependency graph is acyclic

### Python-Specific Checks

Read and enforce all rules in [references/pep8-layout.md](references/pep8-layout.md), [references/pep8-whitespace.md](references/pep8-whitespace.md), and [references/pep8-programming.md](references/pep8-programming.md) — the items below are highlights only.

- [ ] **String quotes** — Follow the project's formatter convention (Black and ruff default to double quotes). If no formatter is configured, be consistent within each file
- [ ] **[PEP 8](https://peps.python.org/pep-0008/) compliance** — Line length, spacing, blank lines
- [ ] **No mutable default arguments** — Use `None` + assignment in body
- [ ] **Context managers** — `with` used for resource management
- [ ] **List/dict/set comprehensions** — Preferred over `map`/`filter` where readable

## Docstring Format

Follow [PEP 257](https://peps.python.org/pep-0257/) for structure and formatting. Use Sphinx format without types in fields (types come from hints):

```python
def connect(host: str, port: int, timeout: float = 30.0) -> Connection:
    """Establish a connection to the remote server.

    :param host: Hostname or IP address of the server.
    :param port: Port number to connect to.
    :param timeout: Maximum time to wait for the connection in seconds.
    :returns: An active connection to the server.
    :raises ConnectionError: If the server is unreachable.
    """
```

### Key Rules

- One-line docstrings: opening and closing `"""` on the same line.
- Multi-line: summary line, blank line, body, closing `"""` on its own line.
- Do NOT duplicate type information in `:param:` or `:returns:` fields.

## Anti-Patterns

Read and enforce all rules in [references/pep8-programming.md](references/pep8-programming.md) — the table below covers common cases only.

| Anti-Pattern | Problem | Fix |
|--------------|---------|-----|
| Bare `except:` | Catches `SystemExit`, `KeyboardInterrupt` | Catch specific exceptions |
| Mutable default args (`def f(x=[])`) | Shared state across calls | Use `None`, assign in body |
| `import *` | Namespace pollution, unclear origins | Import specific names |
| Type in docstring AND hint | Maintenance burden, drift | Types in hints only |
| Nested try/except 3+ deep | Unreadable error flow | Refactor into smaller functions |
| `isinstance` chains | Often means missing polymorphism | Consider dispatch or protocol |
| String concatenation in loops | O(n^2) memory | Use `"".join()` or f-strings |

## Performance Optimization

### Profile Before Optimizing

Use the project's discovered profiler, or fall back to stdlib:

```bash
python3 -m cProfile -s cumulative your_script.py
python3 -m timeit -s "setup" "statement"
```

If the project uses `py-spy`, `scalene`, or `line_profiler`, prefer those.

### Key Optimizations

| Issue | Solution |
|-------|----------|
| Slow string building | `"".join(parts)` instead of `+=` |
| Repeated attribute lookup in loop | Assign to local variable before loop |
| Large list when only iterating | Use generator expression |
| Repeated dictionary creation | Move to module level or `functools.cache` |

See [references/code-examples.md](references/code-examples.md) for optimization examples.

## Project Layout

Preferred for new projects. For legacy codebases, adopt incrementally when refactoring allows — do not force a restructure solely for compliance.

```
myproject/
├── src/
│   └── package_name/
│       ├── __init__.py
│       └── module.py
├── tests/
│   └── test_module.py
├── docs/
├── pyproject.toml
└── README.md
```

## Debugging

Use the project's discovered debugger, or fall back to stdlib pdb:

```bash
python3 -m pdb your_script.py
```

If the project uses `ipdb` or `pudb`, prefer those (same commands below).

| Command | Action |
|---------|--------|
| `n` | Next line |
| `s` | Step into |
| `c` | Continue |
| `p expr` | Print expression |
| `l` | List source around current line |
| `bt` | Print backtrace |
| `b file:line` | Set breakpoint |

## Design Questions

When designing Python applications, ask:

1. **Data flow** — Where does data enter, transform, and exit? Are boundaries clear?
2. **Error boundaries** — Where should exceptions be caught vs. propagated?
3. **Mutability** — Should this be a dataclass, namedtuple, or class with methods?
4. **Testing** — How will this be tested? What needs to be mockable?
5. **Dependencies** — What external dependencies? Are they injectable?

## Integration with Code Review

When a code review workflow encounters Python files, it delegates language-specific checks to this skill:

1. Run through Code Review Checklist above
2. Flag violations with specific file:line references
3. Suggest idiomatic Python alternatives

## Skill Delegation

When the current task involves writing or modifying test files (`test_*.py` or `*_test.py`), delegate to the `lang-python-testing` skill for:

- Test structure and naming conventions
- Fixture design and coverage workflows
- Test-specific verification steps

Continue using this skill for the production code being tested.

## Quick Reference

Commands shown with defaults — replace with discovered tools when available:

| Task | Default Command | Adapts to |
|------|----------------|-----------|
| Lint | `flake8 src/ tests/` | ruff check, pylint, project-specific |
| Format | _(not configured)_ | ruff format, black, project-specific |
| Type check | _(not configured)_ | mypy, pyright, project-specific |
| Profile | `python3 -m cProfile -s cumulative script.py` | py-spy, scalene |
| Debug | `python3 -m pdb script.py` | ipdb, pudb |

## Reflection Gate

Before marking complete, ask the user: "Would you like me to log insights to `docs/insights.md`?" If yes (or if the file already exists and has prior entries), append a row:

| Date | Skill | Worked Well | Unexpected | Do Differently |
|------|-------|-------------|------------|----------------|
| YYYY-MM-DD | lang-python | _answer_ | _answer_ | _answer_ |

If declined or if the project has no `docs/` directory, skip silently.
