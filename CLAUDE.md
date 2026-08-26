# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

The repository root has no top-level app yet (just this file and a placeholder `README.md`). The only real code lives in `nhl_toolkit/`, a Python toolkit now spanning Phase 1 (schedule ingestion + travel/rest metrics) and Phase 2 (odds ingestion, the generic policy-driven scoring engine, and the daily Top-10 report). There is no test suite yet — dependencies are managed by hand (`pip install requests pyyaml`; everything else is stdlib).

Use a repo-root `.venv` (not a per-subdirectory one) even though `nhl_toolkit/` is the only Python code today — see `.gitignore` (`.venv/`, `*.db`, `.env`, and `nhl_toolkit/reports/` are excluded from version control).

`betting-toolkit-design.md` (repo root) is the full project design doc — read it before planning any new work here. It lays out the end goal: a scheduled, no-LLM Python pipeline that fetches NHL schedule/odds/injury/travel data into a database, scores every game through a config-driven weighted policy engine (`policy.yaml`), outputs a daily Top-10 picks report, and logs outcomes for backtesting. `nhl_toolkit/` now covers build-order steps 1–6 of that design (arenas, schedule ingestion, travel/rest metrics, odds ingestion, the policy engine, and the Top-10 report/`picks_log`) — only the `injuries` table and the grading/ROI script (step 7) remain design-only.

Odds ingestion requires a free API key from https://the-odds-api.com, stored as `export ODDS_API_KEY=...` in a repo-root `.env` (gitignored, never commit it) and loaded with `source .env` before running `fetch_odds.py`.

## Commands

Run all commands from `nhl_toolkit/`.

```bash
pip install requests pyyaml                            # third-party dependencies

source .env && python run_daily.py --date 2026-10-01   # run the full pipeline for one date and build its report
```

`run_daily.py` is the normal way to produce a day's report: it runs every step below in order (fetching just that date's game-week, so it's cheap even run daily) and skips the odds step gracefully if `ODDS_API_KEY` isn't set. Each stage can also be run standalone:

```bash
python db.py                                           # create nhl.db + schema (also runs automatically from every script below)
python fetch_schedule.py --start 2026-10-01 --end 2026-10-31   # upsert schedule/scores for a date range (defaults to today's game week)
python travel_metrics.py                               # rebuild schedule_context (rest/travel/timezone metrics) from `games`
python metrics.py                                      # bridge schedule_context into the generic metrics/metric_values schema
source .env && python fetch_odds.py                    # append an odds snapshot per (game, bookmaker) from The Odds API
python score.py --date 2026-10-01                      # apply policy.yaml to metric_values -> daily_scores
python report.py --date 2026-10-01                     # rank by score gap, print/write Top-10 CSV + HTML, log to picks_log
```

`fetch_schedule.py` is an upsert and safe to re-run daily to pick up final scores. `travel_metrics.py` and `metrics.py` fully delete-and-rebuild their tables each run — always re-run them in order (`travel_metrics.py` then `metrics.py`) after `fetch_schedule.py`, since neither rebuilds automatically (`run_daily.py` handles this ordering for you). `fetch_odds.py` only appends (never deletes), so re-running it accumulates a quote history rather than duplicating in an upsert sense. `score.py` and `report.py` are each idempotent per `(date, policy_version)` — rerunning replaces that date's rows rather than duplicating them.

`report.py` writes three outputs: a local CSV (`nhl_toolkit/reports/`, gitignored), a static HTML page (`docs/reports/picks_{date}.html`, git-tracked), and a regenerated `docs/index.html` linking every report newest-first. The `docs/` folder is meant to be served via GitHub Pages (repo root or `/docs` on `main`) — Pages itself isn't enabled yet since this repo is currently private and Pages sites are public by default on the free plan; enable it in repo Settings → Pages once you're ready to publish (or upgrade/make the repo public first).

## Python Tools

Configured in root `pyproject.toml`, target Python 3.9+ (matches the installed `python3`):

```bash
source .venv/bin/activate
pip install ruff pytest       # dev tools (not committed as a requirements file yet)

ruff check .                  # lint
ruff format .                 # format
pytest                        # tests (none written yet)
```

No type checker (mypy/pyright) is configured — add one if type-checking becomes a priority.

## Architecture

Data flows through a pipeline of scripts, each its own file, all sharing one SQLite DB (`nhl_toolkit/nhl.db`):

**Phase 1 — schedule and travel:**
1. **`db.py`** — owns the schema (all tables below). `games` is raw schedule/score data keyed by the NHL's own `game_id`. `schedule_context` is one row per `(game_id, team_id)` holding derived metrics (rest days, games in trailing 7/14/30 days, distance traveled, timezones crossed, back-to-back flag), FK'd to `games`.
2. **`fetch_schedule.py`** — pulls from the NHL Web API (`api-web.nhle.com/v1/schedule/{date}`), which returns a ~7-day "game week" per call. Walks a date range one game-week at a time and upserts into `games` (`ON CONFLICT(game_id) DO UPDATE` on score/state/start-time — never inserts duplicates).
3. **`travel_metrics.py`** — reads `games` per-team in chronological order and derives `schedule_context` by walking each team's game history once, carrying rolling state (previous venue, previous date, trailing played-dates window). Distance and timezone-shift math depends on `arenas.py`.

**Phase 2 — odds, generic metrics, and policy-driven scoring:**
4. **`metrics.py`** — bridges `schedule_context`'s fixed columns into the design doc's generic `metrics`/`metric_values` tables (one row per name in `metrics`, one row per `(game_id, team_id, metric_id)` in `metric_values`). This is what lets new scoring factors (injuries, recent form, odds movement) get added later as data instead of schema/code changes.
5. **`fetch_odds.py`** — pulls moneyline/puck-line/totals from The Odds API (`icehockey_nhl` sport key) and appends snapshot rows to `odds`, one per `(game, bookmaker)` per run — it's an append-only time series, not an upsert, so re-running frequently is how line-movement gets tracked later. Since the feed identifies teams by full name, not abbrev, matching a quote to a `games` row goes through `arenas.TEAM_NAME_TO_ABBREV` and then a `(home_abbrev, away_abbrev, local_game_date)` lookup — the local date is computed by converting the feed's UTC `commence_time` into the home arena's timezone.
6. **`policy.yaml`** — the only file you edit to change scoring: a `policy_version` plus a `metrics:` map of `{weight, normalize}` per metric name. `normalize` is one of `minmax` / `zscore` / `linear` / `none` (`linear` and `none` are currently the same pass-through — kept as separate labels for documentation intent).
7. **`score.py`** — loads `policy.yaml`, syncs it into `policy_weights` (replacing any existing rows for that `policy_version`), then for a given date normalizes each metric's values **across that date's slate only** (not the whole season) before applying weights, and writes one summed `total_score` row per `(game_id, team_id)` to `daily_scores`. Missing metric values (e.g. a team's first game of the season has no `rest_days`) simply don't contribute to the sum rather than erroring.
8. **`report.py`** — for each game, whichever team's `daily_scores.total_score` is higher is "the pick"; games are ranked by the score gap between the two teams (not by raw score), the top N are printed as a table, written to CSV + HTML (see above), and logged into `picks_log` (spread pulled from `odds` as an average across bookmakers' latest quote per source). Re-running for a date replaces that date's *ungraded* `picks_log` rows only, so grading results already recorded aren't clobbered.
9. **`run_daily.py`** — orchestrates steps 2–8 for one date by importing and calling each script's entrypoint function directly (no subprocesses). Since every stage is either an upsert or a full rebuild, there's no "only run what's needed" logic — it just runs everything every time, which is simpler and still cheap.

`arenas.py` is static reference data (lat/lon + IANA timezone per team, keyed by the 3-letter abbrev the NHL API uses), plus `TEAM_NAME_TO_ABBREV`, a reverse lookup built from that same data for feeds (like odds) that identify teams by full name. Note the ARI→UTA relocation: `ARENAS["ARI"]` is aliased to the same record as `ARENAS["UTA"]` so historical pre-2024-25 data still resolves.

SQLite was chosen deliberately for zero-config local development; the schema is kept plain enough that a future Postgres migration is meant to be a straight port, not a rewrite (see `db.py` docstring).

## Roadmap (not yet implemented)

Per `nhl_toolkit/README.md` and `betting-toolkit-design.md`, only the design's final build-order step is still design-only:

- An `injuries` table (deferred as the messiest data source — likely needs scraping) and injury-derived metrics.
- A grading script that marks `picks_log.result` (win/loss/push) from final scores, plus an ROI dashboard/backtesting analysis.
- Recent-form and head-to-head metrics — the generic `metrics`/`metric_values` schema already supports adding these without touching `score.py`, but nothing populates them yet.

Don't assume any of this exists — check the actual code before referencing it.
