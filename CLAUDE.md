# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

The repository root has no top-level app yet (just this file and a placeholder `README.md`). The only real code lives in `nhl_toolkit/`, a Python toolkit now spanning Phase 1 (schedule ingestion + travel/rest metrics) and Phase 2 (odds ingestion, the generic policy-driven scoring engine, and the daily Top-10 report). There is no test suite yet — dependencies are managed by hand (`pip install requests pyyaml`; everything else is stdlib).

Use a repo-root `.venv` (not a per-subdirectory one) even though `nhl_toolkit/` is the only Python code today — see `.gitignore` (`.venv/`, `*.db`, `.env`, and `nhl_toolkit/reports/` are excluded from version control).

`betting-toolkit-design.md` (repo root) is the full project design doc — read it before planning any new work here. It lays out the end goal: a scheduled, no-LLM Python pipeline that fetches NHL schedule/odds/injury/travel data into a database, scores every game through a config-driven weighted policy engine (`policies/policy.yaml`), outputs a daily Top-10 picks report, and logs outcomes for backtesting. `nhl_toolkit/` now covers build-order steps 1–7 of that design (arenas, schedule ingestion, travel/rest metrics, odds ingestion, the policy engine, the Top-10 report/`picks_log`, and grading) — only the `injuries` table and the ROI/weight-tuning analysis remain design-only.

Odds ingestion requires a free API key from https://the-odds-api.com, stored as `export ODDS_API_KEY=...` in a repo-root `.env` (gitignored, never commit it) and loaded with `source .env` before running `lib/fetch_odds.py`.

## Commands

Run all commands from `nhl_toolkit/`. `bin/` holds the two scripts meant for cron/`run_daily.py` (which also run standalone); `lib/` holds schedule/metrics/scoring infrastructure; `picks/` holds everything about a specific pick (report, grading, backtesting); `policies/` holds the scoring config itself (`policy.yaml`) and its reference-page renderer. All four are plain sibling directories under `nhl_toolkit/`, not Python packages — cross-directory imports work via a small `sys.path` bootstrap at the top of whichever script needs it (see `bin/run_daily.py` for the pattern).

```bash
pip install requests pyyaml                                # third-party dependencies

source .env && python bin/run_daily.py --date 2026-10-01   # run the full pipeline for one date and build its report
```

`bin/run_daily.py` is the normal way to produce a day's report: it runs every step below in order (fetching just that date's game-week, so it's cheap even run daily) and skips the odds step gracefully if `ODDS_API_KEY` isn't set. Each stage can also be run standalone:

```bash
python lib/db.py                                          # create nhl.db + schema (also runs automatically from every script below)
python lib/fetch_schedule.py --start 2026-10-01 --end 2026-10-31   # upsert schedule/scores for a date range (defaults to today's game week)
python picks/grade.py                                     # grade any newly-final picks_log rows (result + straight_up_result)
python lib/travel_metrics.py                              # rebuild schedule_context (rest/travel/timezone metrics) from `games`
python lib/metrics.py                                     # bridge schedule_context into the generic metrics/metric_values schema
python lib/form_metrics.py                                # rebuild recent_form/goal_differential metric_values from `games` scores
source .env && python lib/fetch_odds.py                   # append an odds snapshot per (game, bookmaker) from The Odds API
python lib/score.py --date 2026-10-01                     # apply policies/policy.yaml to metric_values -> daily_scores
python picks/report.py --date 2026-10-01                  # rank by score gap, print/write Top-10 CSV + HTML, log to picks_log
python picks/backtest.py                                  # not part of run_daily.py -- a manual tuning aid, see below
```

`fetch_schedule.py` is an upsert and safe to re-run daily to pick up final scores. `travel_metrics.py`, `metrics.py`, and `form_metrics.py` fully delete-and-rebuild the metric_values rows they own each run — always re-run them in order (`travel_metrics.py` then `metrics.py`/`form_metrics.py`, either order between those two) after `fetch_schedule.py`, since none of them rebuild automatically (`run_daily.py` handles this ordering for you). `fetch_odds.py` only appends (never deletes), so re-running it accumulates a quote history rather than duplicating in an upsert sense. `score.py` and `report.py` are each idempotent per `(date, policy_version)` — rerunning replaces that date's rows rather than duplicating them. `grade.py` only touches `picks_log` rows that are still ungraded (`result IS NULL OR straight_up_result IS NULL`), so it's safe to re-run as often as you like and never re-grades or overwrites an already-graded row.

`report.py` writes three outputs: a local CSV (`nhl_toolkit/reports/`, gitignored), a static HTML page (`docs/reports/picks_{date}.html`, git-tracked), and a regenerated `docs/index.html` linking every report newest-first. The `docs/` folder is meant to be served via GitHub Pages (repo root or `/docs` on `main`) — Pages itself isn't enabled yet since this repo is currently private and Pages sites are public by default on the free plan; enable it in repo Settings → Pages once you're ready to publish (or upgrade/make the repo public first).

`policy_page.py` renders `docs/policy.html`, a reference table of every metric in `policies/policy.yaml` (weight, normalize method, description/unit from the `metrics` catalog) — linked from the reports index, meant to make weight-tuning easier without opening the YAML. It reads `policies/policy.yaml` directly each time, so it's always current; nothing needs to be kept in sync by hand. `run_daily.py` regenerates it every run.

### Running this daily / accumulating a season's data

`nhl.db` is meant to be a long-lived, ever-growing local database, not something reset between runs — nothing in this pipeline drops or replaces the whole DB (`*.db` is gitignored deliberately; GitHub is for code backup only, not data). One-time backfill for a season already in progress, then run daily from there:

```bash
python lib/fetch_schedule.py --start 2026-10-01 --end 2026-10-31   # backfill however far the season has gotten
python bin/run_daily.py --date 2026-10-01                           # then run_daily.py daily going forward
```

`run_daily.py` re-fetches a trailing `--lookback-days` window (default 3) behind `--date` in addition to that date's game-week, so games that finished in the last few days get their final score upserted even after they're no longer "today" — without this, a game played yesterday would stay stuck at its pre-game state forever once `--date` moves past it. If you ever miss several days of runs, re-run the backfill command above to close the gap (upserts are idempotent, so overlapping ranges are harmless).

For unattended daily runs, `run_daily_cron.sh` is a cron-safe wrapper (absolute paths, sources `.env`, logs to `nhl_toolkit/logs/`, both gitignored):

```
0 9 * * * /Users/babruzi/Documents/VSCODE/GITHUB/hockey-web/nhl_toolkit/bin/run_daily_cron.sh
```

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

Data flows through a pipeline of scripts, each its own file, all sharing one SQLite DB (`nhl_toolkit/nhl.db`). They're split across four sibling directories under `nhl_toolkit/`: `bin/` (the two scripts meant to be invoked directly — `run_daily.py` and its cron wrapper), `lib/` (schedule/travel/odds/metrics/scoring infrastructure), `picks/` (building, grading, and backtesting a day's picks), and `policies/` (the scoring config and its reference-page renderer). None of these are Python packages — a script that imports a sibling in a different directory adds that directory to `sys.path` at the top of the file before the import (see `bin/run_daily.py`, which needs all three of `lib/`, `picks/`, and `policies/`).

**Phase 1 — schedule and travel:**
1. **`lib/db.py`** — owns the schema (all tables below). `games` is raw schedule/score data keyed by the NHL's own `game_id`. `schedule_context` is one row per `(game_id, team_id)` holding derived metrics (rest days, games in trailing 7/14/30 days, distance traveled, timezones crossed, back-to-back flag), FK'd to `games`.
2. **`lib/fetch_schedule.py`** — pulls from the NHL Web API (`api-web.nhle.com/v1/schedule/{date}`), which returns a ~7-day "game week" per call. Walks a date range one game-week at a time and upserts into `games` (`ON CONFLICT(game_id) DO UPDATE` on score/state/start-time — never inserts duplicates).
3. **`lib/travel_metrics.py`** — reads `games` per-team in chronological order and derives `schedule_context` by walking each team's game history once, carrying rolling state (previous venue, previous date, trailing played-dates window). Distance and timezone-shift math depends on `lib/arenas.py`.

**Phase 2 — odds, generic metrics, and policy-driven scoring:**
4. **`lib/metrics.py`** — bridges `schedule_context`'s fixed columns into the design doc's generic `metrics`/`metric_values` tables (one row per name in `metrics`, one row per `(game_id, team_id, metric_id)` in `metric_values`). This is what lets new scoring factors (injuries, recent form, odds movement) get added later as data instead of schema/code changes.
5. **`lib/form_metrics.py`** — derives two more metrics straight from `games` (no separate context table needed): `recent_form` (win % over a team's last 10 completed games) and `goal_differential` (average goal margin over that same window). Walks each team's full game history chronologically, but only updates its rolling window on completed games — **the NHL Web API marks a completed game's `game_state` as `"OFF"`, not `"FINAL"`** (the `games.game_state` column comment used to claim otherwise; that was wrong and silently broke this until it was caught by checking against a real, already-completed season's scores). A metric_values row is written for every game including future ones, using only games already played, so there's no lookahead into the game being scored.
6. **`lib/fetch_odds.py`** — pulls moneyline/puck-line/totals from The Odds API (`icehockey_nhl` sport key) and appends snapshot rows to `odds`, one per `(game, bookmaker)` per run — it's an append-only time series, not an upsert, so re-running frequently is how line-movement gets tracked later. Since the feed identifies teams by full name, not abbrev, matching a quote to a `games` row goes through `arenas.TEAM_NAME_TO_ABBREV` and then a `(home_abbrev, away_abbrev, local_game_date)` lookup — the local date is computed by converting the feed's UTC `commence_time` into the home arena's timezone.
7. **`policies/policy.yaml`** (repo: `nhl_toolkit/policies/policy.yaml`) — the only file you edit to change scoring: a `policy_version` plus a `metrics:` map of `{weight, normalize}` per metric name. `normalize` is one of `minmax` / `zscore` / `linear` / `none` (`linear` and `none` are currently the same pass-through — kept as separate labels for documentation intent).
8. **`lib/score.py`** — loads `policies/policy.yaml`, syncs it into `policy_weights` (replacing any existing rows for that `policy_version`), then for a given date normalizes each metric's values **across that date's slate only** (not the whole season) before applying weights, and writes one summed `total_score` row per `(game_id, team_id)` to `daily_scores`. Missing metric values (e.g. a team's first game of the season has no `rest_days`, or no completed games yet for `recent_form`) simply don't contribute to the sum rather than erroring.
9. **`picks/report.py`** — for each game, whichever team's `daily_scores.total_score` is higher is "the pick"; games are ranked by the score gap between the two teams (not by raw score), the top N are printed as a table, written to CSV + HTML (see above), and logged into `picks_log` (spread pulled from `odds` as an average across bookmakers' latest quote per source). Re-running for a date replaces that date's *ungraded* `picks_log` rows only, so grading results already recorded aren't clobbered.
10. **`policies/policy_page.py`** — renders `docs/policy.html` straight from `policies/policy.yaml` plus the `metrics` catalog; a read-only reference, not a data output.
11. **`picks/grade.py`** — grades every `picks_log` row whose game is final (`game_state = 'OFF'`, both scores present) and still ungraded: `result` ('win'/'loss'/'push') against the puck-line spread in `spread_at_pick`, and `straight_up_result` ('win'/'loss') for whether the picked team won the game outright. Tracked separately because `spread_at_pick` is often `NULL` (no odds fetched that day) — those rows still get a `straight_up_result`, which is also the cleaner signal for judging the scoring engine's own picks independent of the betting market's line. Safe to re-run; only touches rows still missing a result.
12. **`bin/run_daily.py`** — orchestrates steps 2–11 for one date by inserting `lib/`, `picks/`, and `policies/` onto `sys.path` and importing/calling each module's entrypoint function directly (no subprocesses). Since every stage is either an upsert or a full rebuild, there's no "only run what's needed" logic — it just runs everything every time, which is simpler and still cheap. Its schedule fetch uses a `--lookback-days` window (default 3) behind the target date so recently-completed games' final scores get upserted even after they've aged out of being "today," and grading runs right after that fetch so those newly-final scores get graded the same run.
13. **`bin/run_daily_cron.sh`** — cron-safe wrapper around `run_daily.py` for unattended daily runs (absolute paths, sources `.env`, logs to `nhl_toolkit/logs/`).

`lib/arenas.py` is static reference data (lat/lon + IANA timezone per team, keyed by the 3-letter abbrev the NHL API uses), plus `TEAM_NAME_TO_ABBREV`, a reverse lookup built from that same data for feeds (like odds) that identify teams by full name. Note the ARI→UTA relocation: `ARENAS["ARI"]` is aliased to the same record as `ARENAS["UTA"]` so historical pre-2024-25 data still resolves.

`picks/backtest.py` is a standalone, read-only diagnostic (`python picks/backtest.py`, not wired into `run_daily.py`) for tuning `policies/policy.yaml` weights: it correlates each metric's home-minus-away differential against the actual final goal margin across every completed game, and prints `picks_log`'s real straight-up/ATS record per `policy_version`. It never hardcodes a metric name — it reads whatever rows exist in the `metrics` table, so a future metric (injuries, head-to-head, goalie quality) shows up here automatically the first time something populates its `metric_values`, with zero changes to this file. It's purely advisory (never writes to `policies/policy.yaml`); a metric's correlation sign/magnitude is a hint for hand-tuning its weight, not a verdict, especially early in a season when sample sizes are tiny (see `--min-n`). Note `home_ice` always correlates as `n/a`: its home-minus-away differential is definitionally constant (1 for every game), so this particular diagnostic can't say anything about it.

SQLite was chosen deliberately for zero-config local development; the schema is kept plain enough that a future Postgres migration is meant to be a straight port, not a rewrite (see `lib/db.py` docstring).

## Roadmap (not yet implemented)

Per `nhl_toolkit/README.md` and `betting-toolkit-design.md`:

- An `injuries` table (deferred as the messiest data source — likely needs scraping) and injury-derived metrics.
- An ROI dashboard over the now-graded `picks_log` (win/loss/push record, cumulative edge, streaks, etc.) — `picks/grade.py` populates `result`/`straight_up_result`, but nothing aggregates them into a report yet. (A bare per-policy-version win/loss summary is now in `picks/backtest.py`'s output, but it's not its own report.)
- Head-to-head record and starting-goalie quality — the generic `metrics`/`metric_values` schema already supports adding these without touching `score.py` or `picks/backtest.py`, but nothing populates them yet. (`recent_form`/`goal_differential` are now implemented, in `form_metrics.py`.)

Further out, not yet designed — see `betting-toolkit-design.md` section 10: player-level stats sourced from MoneyPuck.com (especially goalie data), which would need a schema step up from today's team-level-only tables; and eventually tracking/placing real bets, a materially different feature from the current paper-trading `picks_log`/grading design.

Don't assume any of this exists — check the actual code before referencing it.
