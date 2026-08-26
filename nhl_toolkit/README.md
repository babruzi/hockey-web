# NHL Toolkit — Phase 1 & 2: Schedule, Travel, Odds, and Scoring

## Setup
```bash
pip install requests pyyaml
```
(SQLite, zoneinfo, and csv are in the Python standard library, no extra install needed.)

Odds ingestion needs a free API key from https://the-odds-api.com. Store it
as `export ODDS_API_KEY=...` in a repo-root `.env` (gitignored) and `source .env`
before running `fetch_odds.py`.

## Usage

### Quick start: one date, one command

```bash
source ../.env   # if ODDS_API_KEY is set there
python run_daily.py --date 2026-10-01
```

Runs every step below in order for that date and writes the report (console
table, CSV, and an HTML page under `../docs/reports/`). Safe to re-run.

`nhl.db` is meant to keep growing all season — nothing here resets it, `games`
only gets upserted into, and `schedule_context`/`metric_values` are rebuilt
from all the games on record each run, not just the ones just fetched. If
you're starting mid-season, backfill once, then let `run_daily.py` keep it
current day to day:

```bash
python fetch_schedule.py --start 2026-10-01 --end 2026-10-31   # one-time backfill
python run_daily.py --date 2026-10-15                           # then daily going forward
```

`run_daily.py` also re-fetches a trailing `--lookback-days` window (default 3)
so recently-finished games get their final score upserted even after they're
no longer "today."

### Running it on a schedule (cron)

`run_daily.sh` is a cron-safe wrapper — it uses absolute paths (not your
shell's `$PATH`/cwd), sources `.env`, and logs to `nhl_toolkit/logs/`
(gitignored). Add a line like this via `crontab -e`:

```
0 9 * * * /Users/babruzi/Documents/VSCODE/GITHUB/hockey-web/nhl_toolkit/run_daily.sh
```

That runs it every day at 9am for "today." Adjust the time, or add a second
line with an explicit `--date`/older date if you want a second daily catch-up
run.

### Step by step

1. Initialize the DB (also runs automatically from every script below):
   ```bash
   python db.py
   ```

2. Pull the schedule/scores for a date range (e.g. the first month of the season):
   ```bash
   python fetch_schedule.py --start 2026-10-01 --end 2026-10-31
   ```
   Re-run this daily to pick up final scores as games complete — it's an
   upsert, so it's always safe to re-run over the same range.

3. Compute rest days, game density, distance traveled, timezone shifts,
   and back-to-back flags for every team/game:
   ```bash
   python travel_metrics.py
   ```
   Re-run this after every fetch_schedule.py run to keep it current.

4. Bridge those schedule metrics into the generic metrics/metric_values schema:
   ```bash
   python metrics.py
   ```
   Re-run this after every travel_metrics.py run.

5. Rebuild recent form (win % over the last 10 completed games) and goal
   differential, straight from `games` scores:
   ```bash
   python form_metrics.py
   ```
   Only completed games (`game_state = "OFF"`) update the trailing window;
   future/in-progress games still get a value computed from games already
   played, so upcoming games can be scored too.

6. Pull current NHL odds (moneyline, puck line, totals) from The Odds API:
   ```bash
   source .env
   python fetch_odds.py
   ```
   Each run appends a new snapshot per (game, bookmaker) rather than
   overwriting — safe, and expected, to re-run often to track line movement.

7. Score a date's games against `policy.yaml`:
   ```bash
   python score.py --date 2026-10-01
   ```

8. Build the Top-10 picks report (console table + CSV + HTML) and log picks for backtesting:
   ```bash
   python report.py --date 2026-10-01
   ```
   Writes a local CSV (`reports/`, gitignored) and a static HTML page
   (`../docs/reports/picks_{date}.html`, git-tracked) plus a regenerated
   `../docs/index.html` linking every report. `docs/` is meant to be served
   by GitHub Pages, though Pages itself isn't enabled yet (see repo Settings
   → Pages) — the repo is currently private and Pages sites are public by
   default on the free plan.

9. Regenerate the policy reference page (every metric's weight, normalization
   method, and description in one place — handy while tuning weights):
   ```bash
   python policy_page.py
   ```
   Writes `../docs/policy.html`, linked from the reports index. Reads
   straight from `policy.yaml`, so it always reflects the current config —
   there's nothing to keep in sync manually. `run_daily.py` regenerates it
   automatically each run.

## Files
- `arenas.py` — static reference table: 32 teams, arena lat/lon, IANA timezone, and a full-team-name → abbrev lookup for odds feeds
- `db.py` — SQLite schema (`games`, `schedule_context`, `odds`, `metrics`, `metric_values`, `policy_weights`, `daily_scores`, `picks_log`)
- `fetch_schedule.py` — pulls from the NHL Web API (`api-web.nhle.com/v1/schedule/{date}`)
- `travel_metrics.py` — derives rest/travel/timezone metrics from the raw schedule
- `metrics.py` — seeds the metrics catalog and populates `metric_values` from `schedule_context`
- `form_metrics.py` — computes `recent_form`/`goal_differential` from `games` scores
- `fetch_odds.py` — pulls odds from The Odds API and matches events to `games` rows
- `policy.yaml` — the weighted scoring config; edit this to reweight or add/drop metrics
- `score.py` — normalizes metric values and applies `policy.yaml` to produce `daily_scores`
- `report.py` — ranks games by score gap, prints/writes the Top-10 CSV + HTML, and logs picks
- `policy_page.py` — renders `docs/policy.html`, a reference page of every metric's weight/normalize/description
- `run_daily.py` — runs every step above (including the policy page) in order for one date
- `run_daily.sh` — cron-safe wrapper around `run_daily.py`

## Next up (Phase 3+)
- `injuries` table (deferred as the messiest data source — likely needs scraping)
- Grading script (mark `picks_log` results win/loss/push from final scores) + ROI dashboard — worth waiting on until there are a few weeks of real picks to grade
- A weight-tuning/backtest tool: regress actual results against each game's `metric_values` to see which metrics are actually predictive vs. dead weight in `policy.yaml`. No new data needed — everything already joins on `game_id`
- Head-to-head record and starting-goalie quality, feeding into the same generic `metrics` schema

Further out (see `../betting-toolkit-design.md` section 10, not yet designed): player-level stats from MoneyPuck.com (especially goalie data), and eventually tracking/placing real bets rather than just paper picks.
