# Insights

| Date | Skill | Worked Well | Unexpected | Do Differently |
|------|-------|-------------|------------|-----------------|
| 2026-08-26 | lang-python | Tool discovery (checking `.venv` + `pyproject.toml`) correctly found the newly-added ruff config and applied its line-length setting instead of guessing a default. | `ruff format` handled the long hand-aligned `arenas.py` dict rows better than a manual per-line rewrite — worth trying the formatter before hand-editing E501s. | Run `ruff format` immediately after fixing E501s manually, rather than hand-wrapping lines first. |
