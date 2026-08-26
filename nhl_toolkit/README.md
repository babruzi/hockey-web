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

5. Pull current NHL odds (moneyline, puck line, totals) from The Odds API:
   ```bash
   source .env
   python fetch_odds.py
   ```
   Each run appends a new snapshot per (game, bookmaker) rather than
   overwriting — safe, and expected, to re-run often to track line movement.

6. Score a date's games against `policy.yaml`:
   ```bash
   python score.py --date 2026-10-01
   ```

7. Build the Top-10 picks report (console table + CSV + HTML) and log picks for backtesting:
   ```bash
   python report.py --date 2026-10-01
   ```
   Writes a local CSV (`reports/`, gitignored) and a static HTML page
   (`../docs/reports/picks_{date}.html`, git-tracked) plus a regenerated
   `../docs/index.html` linking every report. `docs/` is meant to be served
   by GitHub Pages, though Pages itself isn't enabled yet (see repo Settings
   → Pages) — the repo is currently private and Pages sites are public by
   default on the free plan.

## Files
- `arenas.py` — static reference table: 32 teams, arena lat/lon, IANA timezone, and a full-team-name → abbrev lookup for odds feeds
- `db.py` — SQLite schema (`games`, `schedule_context`, `odds`, `metrics`, `metric_values`, `policy_weights`, `daily_scores`, `picks_log`)
- `fetch_schedule.py` — pulls from the NHL Web API (`api-web.nhle.com/v1/schedule/{date}`)
- `travel_metrics.py` — derives rest/travel/timezone metrics from the raw schedule
- `metrics.py` — seeds the metrics catalog and populates `metric_values` from `schedule_context`
- `fetch_odds.py` — pulls odds from The Odds API and matches events to `games` rows
- `policy.yaml` — the weighted scoring config; edit this to reweight or add/drop metrics
- `score.py` — normalizes metric values and applies `policy.yaml` to produce `daily_scores`
- `report.py` — ranks games by score gap, prints/writes the Top-10 CSV + HTML, and logs picks
- `run_daily.py` — runs every step above in order for one date

## Next up (Phase 3+)
- `injuries` table (deferred as the messiest data source — likely needs scraping)
- Grading script (mark `picks_log` results win/loss/push from final scores) + ROI dashboard
- Recent-form and head-to-head metrics feeding into the same generic `metrics` schema
