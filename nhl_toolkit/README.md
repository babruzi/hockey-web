# NHL Toolkit — Phase 1 & 2: Schedule, Travel, Odds, and Scoring

## Setup
```bash
pip install requests pyyaml
```
(SQLite, zoneinfo, and csv are in the Python standard library, no extra install needed.)

Odds ingestion needs a free API key from https://the-odds-api.com. Store it
as `export ODDS_API_KEY=...` in a repo-root `.env` (gitignored) and `source .env`
before running `lib/fetch_odds.py`.

Entry-point scripts you run directly live in `bin/`; everything they import
lives in `lib/`. Run all commands below from `nhl_toolkit/`.

## Usage

### Quick start: one date, one command

```bash
source ../.env   # if ODDS_API_KEY is set there
python bin/run_daily.py --date 2026-10-01
```

Runs every step below in order for that date and writes the report (console
table, CSV, and an HTML page under `../docs/reports/`). Safe to re-run. As
its last step it also commits and pushes any changed `../docs/` files to
`origin/main`, so the published site stays in sync automatically -- pass
`--no-push` to skip this (e.g. while testing a change locally before it's
ready to publish).

`nhl.db` is meant to keep growing all season — nothing here resets it, `games`
only gets upserted into, and `schedule_context`/`metric_values` are rebuilt
from all the games on record each run, not just the ones just fetched. If
you're starting mid-season, backfill once, then let `run_daily.py` keep it
current day to day:

```bash
python lib/fetch_schedule.py --start 2026-10-01 --end 2026-10-31   # one-time backfill
python bin/run_daily.py --date 2026-10-15                           # then daily going forward
```

`run_daily.py` also re-fetches a trailing `--lookback-days` window (default 3)
so recently-finished games get their final score upserted even after they're
no longer "today."

### Running it on a schedule (cron)

`bin/run_daily_cron.sh` is a cron-safe wrapper — it uses absolute paths (not your
shell's `$PATH`/cwd), sources `.env`, and logs to `nhl_toolkit/logs/`
(gitignored). Add a line like this via `crontab -e`:

```
0 9 * * * /Users/babruzi/Documents/VSCODE/GITHUB/hockey-web/nhl_toolkit/bin/run_daily_cron.sh
```

That runs it every day at 9am for "today." Adjust the time, or add a second
line with an explicit `--date`/older date if you want a second daily catch-up
run.

### Step by step

1. Initialize the DB (also runs automatically from every script below):
   ```bash
   python lib/db.py
   ```

2. Pull the schedule/scores for a date range (e.g. the first month of the season):
   ```bash
   python lib/fetch_schedule.py --start 2026-10-01 --end 2026-10-31
   ```
   Re-run this daily to pick up final scores as games complete — it's an
   upsert, so it's always safe to re-run over the same range.

3. Grade any `picks_log` rows whose game is now final:
   ```bash
   python lib/grade.py
   ```
   Grades all three independent bet types a picks page can recommend
   (Money Line, Puck Line, Over/Under -- see step 10): `result`
   ('win'/'loss'/'push' against the spread recorded at pick time),
   `straight_up_result` ('win'/'loss', ignoring the spread -- still gets
   filled in even on games with no odds), and `profit_10` ($ profit/loss a
   flat $10 moneyline bet on the pick would have made, settled on
   `straight_up_result` since that's how moneyline bets actually pay out)
   for Money Line; `puck_line_result`/`puck_line_profit_10` the same way
   but for whichever team the Puck Line recommendation actually named
   (which can differ from the Money Line pick); `total_result`/
   `total_profit_10` for the Over/Under recommendation. The stake for all
   three is `grade.py`'s `STAKE` constant, imported wherever else it's
   needed. Safe to re-run; only touches rows still missing a gradeable
   result.

4. Compute rest days, game density, distance traveled, timezone shifts,
   and back-to-back flags for every team/game:
   ```bash
   python lib/travel_metrics.py
   ```
   Re-run this after every fetch_schedule.py run to keep it current.

5. Bridge those schedule metrics into the generic metrics/metric_values schema:
   ```bash
   python lib/metrics.py
   ```
   Re-run this after every travel_metrics.py run.

6. Rebuild recent form (win % over the last 10 completed games), goal
   differential, and average goals for/against, straight from `games` scores:
   ```bash
   python lib/form_metrics.py
   ```
   Only completed games (`game_state = "OFF"`) update the trailing window;
   future/in-progress games still get a value computed from games already
   played, so upcoming games can be scored too. `goals_for_avg`/
   `goals_against_avg` feed `report.py`'s Over/Under recommendation (see
   step 10) — they're never added to `policy.yaml`, so they don't affect
   `score.py`'s Money Line pick.

7. Pull current NHL odds (moneyline, puck line, totals) from The Odds API:
   ```bash
   source .env
   python lib/fetch_odds.py
   ```
   Each run appends a new snapshot per (game, bookmaker) rather than
   overwriting — safe, and expected, to re-run often to track line movement.
   Captures a price for every market, including the spread's own
   (`home_spread_price`/`away_spread_price`) -- not just the puck-line
   number and the separate moneyline.

8. Derive `market_edge` (each team's devigged, market-implied win
   probability, from the moneyline) from whatever odds are on record:
   ```bash
   python lib/market_metrics.py
   ```
   This is what actually puts the betting market into the weighted scoring
   equation -- previously the spread only showed up in the report and in
   after-the-fact ATS grading, never in `total_score`. Uses the moneyline,
   not the puck-line spread: NHL puck lines are fixed at 1.5 goals in
   practice (every quote ever recorded here is exactly -1.5 or +1.5), so a
   spread-based version of this metric barely varies game to game -- the
   moneyline (e.g. -218/+180 vs. -115/-105) is where the market's actual
   opinion about *how much* it favors a team lives. Uses DraftKings'
   moneyline directly when it has one -- that's the book these picks are
   actually meant to be bet on -- falling back to a cross-book average only
   for a game DraftKings hasn't posted a line for yet. Works even without a
   fresh `fetch_odds.py` run this time, using whatever quotes are already
   saved; a team with no quote on record for a game just gets no value,
   same as any other metric.

9. Score a date's games against `policy.yaml`:
   ```bash
   python lib/score.py --date 2026-10-01
   ```

10. Build the full picks report, every game ranked by edge (console table + CSV + HTML), and log picks for backtesting:
   ```bash
   python lib/report.py --date 2026-10-01
   ```
   Writes a local CSV (`reports/`, gitignored) and a static HTML page
   (`../docs/reports/picks/picks_{date}.html`, git-tracked) plus a regenerated
   `../docs/index.html` linking every report. If `--date` is today, also
   writes `../docs/reports/picks/current.html` -- a duplicate at a stable
   filename (not a symlink; GitHub Pages' build ignores those) so a
   bookmarked URL always shows the latest picks. The HTML table is laid out
   like a sportsbook board: two rows per game (away team on top, home team
   below, its name lightly shaded so which team is home is visible at a
   glance), each game's pair of rows boxed off with a thicker top/bottom
   border than the 1px border between every other cell, with **Puck Line /
   Over-Under / Money Line** columns for each
   side's price, each followed by its devigged implied probability in parens
   (e.g. "-1.5 +154 (37.8%)"). Only on today's page, an **Est. Winnings**
   column plus a Money Line/Puck Line dropdown let you see the payout on a
   $10 bet on the pick for either market, recalculated instantly by a small
   inline script when you switch the dropdown -- the only JavaScript on the
   site, and only shown for today since it's a forward-looking "if this pick
   wins" number that doesn't make sense once a date is already graded. The
   green highlight in each of the three columns is that column's own,
   independent recommendation, not one pick repeated three times: Money Line
   is the overall pick (policy.yaml's weighted `total_score`); Puck Line
   projects each team's own recent average goal differential against the
   other's to see whether the favorite's margin clears the fixed 1.5-goal
   line, recommending the underdog (+1.5) instead when it doesn't;
   Over/Under projects a total from each team's recent average goals
   for/against (`goals_for_avg`/`goals_against_avg`) and compares it to the
   market's own total. All three can (and often do) disagree on the same
   game -- see `puck_line_recommendation()`/`total_recommendation()` in
   `report.py`. The page header only shows the date and (on today's page)
   the dropdown -- the full explanation of how to read the table lives in a
   `<p class="legend">` below the table instead, right before the
   disclaimer/timestamp footer, so the reader gets straight to the table
   first. Every
   page's "Last updated" footer is US Eastern (EDT/EST, auto-detected via
   `zoneinfo` -- not a hardcoded label), not UTC. The page is sized at
   `max-width: 1400px` so the full table fits on a typical desktop browser
   without horizontal scrolling; the horizontal-scroll fallback (for
   anything narrower, e.g. a phone) only engages below that width, and the
   table header freezes in place while scrolling down the page
   (`position: sticky`) everywhere the scroll fallback isn't active.
   Below the table, an **If You Bet Every Pick** table shows that day's
   actual $ outcome per bet type -- Money Line, Puck Line, Over/Under --
   if every one of that type's recommendations on the slate had been bet
   at a flat $10. It only has a real number once a game is graded; before
   that it says "Not yet graded," and if the games are final but there was
   never a price on record for that bet type (e.g. a date before
   `fetch_odds.py` started capturing puck-line prices) it says "No odds on
   record" instead -- those are different situations and the page doesn't
   conflate them. `docs/` is served live by GitHub Pages at
   https://babruzi.github.io/hockey-web/.

11. Regenerate the policy reference page (every metric's weight, normalization
    method, and description in one place — handy while tuning weights):
    ```bash
    python lib/policy_page.py
    ```
    Writes `../docs/reports/policies/policy.html`, linked from the reports
    index. Reads straight from `policy.yaml`, so it always reflects the
    current config — there's nothing to keep in sync manually. `run_daily.py`
    regenerates it automatically each run.

12. Regenerate the performance/ROI record page:
    ```bash
    python lib/record_page.py
    ```
    Writes `../docs/reports/record.html` -- picks_log's overall record and
    ROI for all three bet types (Money Line, Puck Line, Over/Under), each
    as its own row, plus a per-`policy_version` breakdown for Money Line
    only (Puck Line/Over-Under aren't policy.yaml-driven, so grouping those
    by policy_version wouldn't mean anything). Reuses `backtest.py`'s
    `policy_performance()`/`bet_type_totals()` rather than re-deriving the
    numbers. Linked from the reports index as "Performance record & ROI,"
    only once the page actually exists (same dead-link guard as "Today's
    Picks"). `run_daily.py` regenerates it right after grading, before the
    per-date report refresh runs.

### Tuning weights: backtesting

```bash
python lib/backtest.py                 # defaults to flagging metrics with < 10 completed games
python lib/backtest.py --min-n 20      # raise the sample-size bar for the "too thin" flag
```

Not part of `run_daily.py` — a manual, on-demand diagnostic for when you're
reviewing `policy.yaml`. For every metric in the `metrics` table it
correlates that metric's home-minus-away differential against the actual
final goal margin across every completed game, and flags weights whose sign
disagrees with the correlation. It also prints `picks_log`'s real
moneyline/against-the-puck-line record *and* moneyline ROI (summed
`profit_10` on a flat $10 stake per pick) per `policy_version`, plus the
same record/ROI for the Puck Line and Over/Under recommendations as one
overall total each (independent of `policy_version`, since neither is
policy.yaml-driven). Never
writes to `policy.yaml` — correlation is a hint for hand-tuning, not an
answer, and early in a season the sample sizes are too small to trust
(that's what `--min-n` flags). It never hardcodes a metric name, so a future
metric (injuries, head-to-head, goalie quality) appears here automatically
as soon as it has `metric_values`, with zero code changes to this script --
that's exactly how `market_edge`'s correlation went from `n/a` (under the
old spread-based version) to a real number (once reworked onto the
moneyline), without touching `backtest.py` either time.

## Files
- `bin/run_daily.py` — runs every step below (including the policy page) in order for one date, then commits/pushes any changed `docs/` files to GitHub (`--no-push` to skip); the normal way to run this toolkit
- `bin/run_daily_cron.sh` — cron-safe wrapper around `bin/run_daily.py`
- `lib/arenas.py` — static reference table: 32 teams, arena lat/lon, IANA timezone, and a full-team-name → abbrev lookup for odds feeds
- `lib/db.py` — SQLite schema (`games`, `schedule_context`, `odds`, `metrics`, `metric_values`, `policy_weights`, `daily_scores`, `picks_log`)
- `lib/fetch_schedule.py` — pulls from the NHL Web API (`api-web.nhle.com/v1/schedule/{date}`)
- `lib/grade.py` — grades final games' `picks_log` rows for all three bet types (Money Line, Puck Line, Over/Under): `result`/`straight_up_result`/`profit_10`, `puck_line_result`/`puck_line_profit_10`, `total_result`/`total_profit_10`; owns the `STAKE` constant and the shared `odds_profit()` P&L helper everything else imports
- `lib/travel_metrics.py` — derives rest/travel/timezone metrics from the raw schedule
- `lib/metrics.py` — seeds the metrics catalog and populates `metric_values` from `schedule_context`
- `lib/form_metrics.py` — computes `recent_form`/`goal_differential` from `games` scores
- `lib/fetch_odds.py` — pulls odds from The Odds API and matches events to `games` rows
- `lib/market_metrics.py` — derives `market_edge` (devigged implied win probability, from the moneyline) from `odds`, so the betting market is an actual weighted input to scoring, not just a display/grading detail
- `policy.yaml` — the weighted scoring config; edit this to reweight or add/drop metrics
- `lib/score.py` — normalizes metric values and applies `policy.yaml` to produce `daily_scores`
- `lib/report.py` — ranks every game by score gap, prints/writes CSV + HTML, and logs picks
- `lib/policy_page.py` — renders `docs/reports/policies/policy.html`, a reference page of every metric's weight/normalize/description
- `lib/backtest.py` — standalone diagnostic: correlates each metric against actual goal margin, prints picks_log's real record per policy_version
- `lib/record_page.py` — renders `docs/reports/record.html`, the published overall straight-up/ATS record and moneyline ROI (reuses `backtest.py`'s numbers, not its own analysis)

## Next up (Phase 3+)
- `injuries` table (deferred as the messiest data source — likely needs scraping)
- A cumulative-edge/streaks view over `picks_log` beyond the win/loss/ROI record `lib/record_page.py` now publishes -- e.g. a running bankroll chart, current streak, best/worst single pick
- Head-to-head record and starting-goalie quality, feeding into the same generic `metrics` schema

Further out (see `../betting-toolkit-design.md` section 10, not yet designed): player-level stats from MoneyPuck.com (especially goalie data), and eventually tracking/placing real bets rather than just paper picks.
