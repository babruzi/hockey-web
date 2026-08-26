# Test Tool Discovery — Extraction Rules

How to extract test tool configuration from each source. Stop at the first source that provides definitive configuration for a given role.

## CLAUDE.md / AGENTS.md

Look for sections titled "Testing", "Tests", "Commands", or fenced code blocks containing test/coverage commands. Extract commands verbatim — these take highest priority.

## pyproject.toml

Parse sections to identify configured test tools:

| Section | Role | Inferred Command |
|---------|------|-----------------|
| `[tool.pytest.ini_options]` | Test runner | `pytest` |
| `[tool.coverage]` | Coverage | `coverage run -m pytest` |
| `[tool.coverage.run]` | Coverage | `coverage run -m pytest` |
| `[tool.ward]` | Test runner | `ward` |

Also check `[project.optional-dependencies]` for `test` or `dev` groups — tool names in dependency lists confirm which tools the project uses (e.g., `pytest`, `pytest-cov`, `coverage`, `ward`, `nose2`).

If `pytest-cov` appears in dependencies alongside `[tool.pytest.ini_options]`, the coverage command is `pytest --cov` rather than `coverage run`.

## tox.ini / tox.toml

Look for `[testenv]` (default) or environments named `test`, `tests`, `py`, `py3`.

Extract `commands` values from matching environments. Example:

```ini
[testenv]
commands =
    pytest --cov=src/ --cov-branch {posargs}
```

This yields: Test runner → `pytest`, Coverage → `pytest --cov=src/ --cov-branch`.

## noxfile.py

Look for `@nox.session` decorated functions named `test`, `tests`, `check`.

Extract `session.run(...)` calls within those functions. Example:

```python
@nox.session
def tests(session):
    session.install("pytest", "pytest-cov")
    session.run("pytest", "--cov=src/")
```

This yields: Test runner → `pytest`, Coverage → `pytest --cov=src/`.

## CI Pipeline Files

### GitHub Actions (`.github/workflows/*.yml`)

Look for steps with `run:` containing test commands. Focus on jobs/steps named `test`, `tests`, `check`, or within a job named `ci`/`build`.

### GitLab CI (`.gitlab-ci.yml`)

Look for jobs named `test`, `tests`, `unit-test`, `integration-test`. Extract `script:` lines containing test commands.

## Makefile

Look for targets named `test`, `tests`, `check`, `unittest`.

Extract the recipe commands. Example:

```makefile
test:
	coverage run -m pytest tests/
	coverage report --fail-under=80
```

This yields: Test runner → `pytest`, Coverage → `coverage run -m pytest tests/`.

## Priority & Conflict Resolution

If multiple sources define tools for the same role, prefer the highest-priority source:

CLAUDE.md > pyproject.toml > tox > nox > CI > Makefile

If a single source defines multiple test commands (e.g., both unit and integration test commands in tox), note both — the project likely distinguishes between test types.
