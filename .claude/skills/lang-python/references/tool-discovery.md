# Tool Discovery — Extraction Rules

How to extract tool configuration from each source. Stop at the first source that provides definitive configuration for a given role.

## CLAUDE.md / AGENTS.md

Look for sections titled "Tools", "Linting", "Development", "Commands", or fenced code blocks containing lint/format/type-check commands. Extract commands verbatim — these take highest priority since they represent explicit project decisions.

## pyproject.toml

Parse `[tool.*]` section headers to identify configured tools:

| Section | Role(s) | Inferred Command |
|---------|---------|-----------------|
| `[tool.ruff]` or `[tool.ruff.lint]` | Linter + Formatter | `ruff check .` / `ruff format .` |
| `[tool.black]` | Formatter | `black .` |
| `[tool.mypy]` | Type checker | `mypy .` |
| `[tool.pyright]` | Type checker | `pyright` |
| `[tool.pylint]` | Linter | `pylint src/` |
| `[tool.flake8]` | Linter | `flake8 src/ tests/` |
| `[tool.isort]` | Import sorter | `isort .` |
| `[tool.autopep8]` | Formatter | `autopep8 --in-place --recursive .` |

Also check `[project.optional-dependencies]` for `dev` or `lint` groups — tool names in dependency lists confirm which tools the project uses.

## tox.ini / tox.toml

Look for environments named `lint`, `format`, `type`, `typecheck`, `style`, `check`.

Extract `commands` values from matching environments. Example:

```ini
[testenv:lint]
commands =
    ruff check src/ tests/
    mypy src/
```

This yields: Linter → `ruff check src/ tests/`, Type checker → `mypy src/`.

## noxfile.py

Look for `@nox.session` decorated functions named `lint`, `format`, `typecheck`, `style`.

Extract `session.run(...)` calls within those functions. Example:

```python
@nox.session
def lint(session):
    session.install("ruff")
    session.run("ruff", "check", "src/")
```

This yields: Linter → `ruff check src/`.

## CI Pipeline Files

### GitHub Actions (`.github/workflows/*.yml`)

Look for steps with `run:` containing tool commands. Focus on jobs/steps named `lint`, `format`, `type-check`, `style`, or within a job named `quality`/`checks`.

### GitLab CI (`.gitlab-ci.yml`)

Look for jobs named `lint`, `format`, `type-check`, `style`, `quality`. Extract `script:` lines containing tool commands.

## Makefile

Look for targets named `lint`, `format`, `check`, `typecheck`, `style`, `quality`.

Extract the recipe commands. Example:

```makefile
lint:
	ruff check src/ tests/
	mypy src/
```

This yields: Linter → `ruff check src/ tests/`, Type checker → `mypy src/`.

## Priority & Conflict Resolution

If multiple sources define tools for the same role, prefer the highest-priority source:

CLAUDE.md > pyproject.toml > tox > nox > CI > Makefile

If a single source defines multiple tools for the same role (e.g., both flake8 and ruff as linters in a tox environment), use all of them in the order listed — the project likely runs both.
