# NHL Paper Betting Analysis Toolkit — Project Design

## 1. Goal
A Python-driven pipeline (no LLM tokens needed for daily runs) that:
- Pulls NHL schedule, results, injuries, travel/rest metadata, and betting lines (spreads/moneyline/totals) daily
- Stores everything in a database for fast querying and historical analysis
- Scores every game/team against a **flexible, weighted policy engine**
- Outputs a daily "Top 10" ranked list of bets
- Logs outcomes so you can backtest and tune weights over time

---

## 2. Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌───────────────────┐
│  Data Fetchers   │ --> │   SQLite/Postgres │ --> │  Scoring Engine    │
│ (NHL API, Odds   │     │   Database         │     │ (weighted policy   │
│  API, scrapers)  │     │                    │     │  config, .yaml)    │
└─────────────────┘     └──────────────────┘     └───────────────────┘
                                                          │
                                                          v
                                                ┌───────────────────┐
                                                │  Daily Report      │
                                                │ (Top 10 picks CSV/ │
                                                │  HTML + DB log)    │
                                                └───────────────────┘
                                                          │
                                                          v
                                                ┌───────────────────┐
                                                │  Results Tracker   │
                                                │ (grades picks next │
                                                │  day, computes ROI)│
                                                └───────────────────┘
```

Everything runs as a scheduled Python script (cron / Task Scheduler / GitHub Actions). No Claude/LLM calls required in the daily loop — this doc and any code we write together is a one-time build.

---

## 3. Data Sources

| Data | Source | Notes |
|---|---|---|
| Schedule, scores, standings | NHL's public API (`api-web.nhle.com`, `statsapi.web.nhl.com` successor) | Free, unofficial but stable, widely used by open-source NHL projects |
| Team/player injuries | NHL API injury reports, or scrape a site like Rotowire/CBS if not covered | May need light scraping (BeautifulSoup) with caution around ToS |
| Venue lat/long & time zones | Static reference table you build once (32 arenas) | Used to compute distance traveled & time zone shifts |
| Odds / point spreads (puck line), moneyline, totals | **The Odds API** (has a free tier, clean JSON, includes NHL puck lines) or OddsJam / SportsDataIO (paid, more depth) | This is the one piece that usually needs a paid API for reliability |

---

## 4. Database Schema (starting point, Postgres or SQLite)

**teams** — team_id, name, abbrev, arena_lat, arena_lon, timezone

**games** — game_id, date, home_team_id, away_team_id, home_score, away_score, status (scheduled/final)

**odds** — odds_id, game_id, source, timestamp, home_spread, away_spread, home_ml, away_ml, total, over_odds, under_odds

**schedule_context** — game_id, team_id, rest_days, games_last_7, games_last_14, games_last_30, distance_traveled_km, timezones_crossed, back_to_back (bool)

**injuries** — injury_id, team_id, player_name, position, status (out/day-to-day), impact_score (optional manual/derived rating)

**metrics** *(the flexible part)* — metric_id, name, description, unit, active (bool)

**metric_values** — game_id, team_id, metric_id, value (numeric)

**policy_weights** — policy_version, metric_id, weight (numeric, can be negative)

**daily_scores** — date, game_id, team_id, total_score, rank, policy_version

**picks_log** — date, game_id, pick (team/side), predicted_edge, spread_at_pick, result (win/loss/push), graded_at

This design means adding a new metric is just: insert a row into `metrics`, populate `metric_values`, add a weight to `policy_weights` — **no schema changes, no code changes** to the scoring engine itself.

---

## 5. Metrics Catalog (starter set — all configurable)

| Metric | Type | Example Weight |
|---|---|---|
| Rest days since last game | numeric | +0.15 |
| Games in last 7 days | numeric (fatigue) | -0.10 |
| Games in last 14 days | numeric | -0.08 |
| Distance traveled (km) since last game | numeric | -0.05 |
| Time zones crossed | numeric | -0.12 |
| Back-to-back game flag | 0/1 | -0.20 |
| Key player injuries (weighted by role) | numeric | -0.25 |
| Home/away | 0/1 | +0.10 |
| Recent form (last 10 games win %) | numeric | +0.20 |
| Head-to-head record this season | numeric | +0.10 |
| Goal differential (last 10) | numeric | +0.15 |
| Power play / penalty kill % | numeric | +0.08 |
| Market line movement (steam) | numeric | +0.10 |

Every metric gets normalized (e.g., z-score or 0–1 scaling) before weighting, so a "distance traveled" number and a "win %" number combine fairly into one total score.

---

## 6. Policy Engine (config-driven, not code-driven)

A `policy.yaml` file like:

```yaml
policy_version: "2026-08-v1"
metrics:
  rest_days:
    weight: 0.15
    normalize: minmax
  games_last_7:
    weight: -0.10
    normalize: zscore
  distance_traveled_km:
    weight: -0.05
    normalize: zscore
  timezones_crossed:
    weight: -0.12
    normalize: linear
  back_to_back:
    weight: -0.20
    normalize: none
  injury_impact:
    weight: -0.25
    normalize: minmax
  recent_form:
    weight: 0.20
    normalize: minmax
```

To add/remove a policy factor, you just edit this file — the engine reads it, computes `total_score = Σ(normalized_value × weight)` per team per game, and re-ranks. This gives you the flexibility you asked for without touching the database or core code.

---

## 7. Daily Pipeline (single Python script, cron job)

1. **Fetch**: pull today's + tomorrow's schedule, latest odds, injury updates
2. **Compute context**: rest days, travel distance (haversine from arena coords), timezone deltas, recent form
3. **Score**: apply `policy.yaml` weights → total_score per game/side
4. **Rank**: sort, take Top 10 (highest edge vs. the market spread)
5. **Log**: write picks to `picks_log` with the spread at time of pick
6. **Report**: output a simple HTML/CSV daily digest
7. **Grade yesterday's picks**: pull final scores, mark win/loss/push, update running ROI stats

This whole thing is one scheduled script — zero LLM cost after we build it.

---

## 8. Backtesting & Tuning

Because every score and every actual result is logged, you can later:
- Replay the season with a different `policy.yaml` and compare ROI
- Isolate which metrics actually predict cover margin (simple regression against `picks_log` results)
- A/B test policy versions side by side (the `policy_version` field supports this natively)

---

## 9. Suggested Build Order (Phase 1)

1. Static reference data: 32 teams, arenas, lat/lon, timezones
2. Schedule + score ingestion from NHL API → `games` table
3. Travel/rest metric computation → `schedule_context`
4. Odds ingestion (pick one provider) → `odds`
5. Basic policy engine + `policy.yaml` → `daily_scores`
6. Top-10 daily report + `picks_log`
7. Grading script + ROI dashboard

Injuries can slot in as a Phase 2 add-on since it's the messiest data source (may require scraping).

---

## 10. Future Directions (noted, not yet designed)

Beyond the phases above, two bigger directions have come up that would each need their own design pass before building:

- **Player-level stats via MoneyPuck.com** — a free, well-regarded advanced-stats site in the open-source hockey analytics community, with strong goalie data (e.g. goals saved above expected) and individual skater data (xG, on-ice impact) that the NHL API doesn't surface. This would slot in as a new data source alongside odds/injuries, but player-level stats mean a schema step up from today's team-level-only tables — likely a `players` table plus a `player_game_stats` or similar, distinct from the team-level `metrics`/`metric_values` schema (or an extension of it, keyed by player_id instead of team_id). Worth it mainly for starting-goalie quality, which is probably the single highest-signal metric currently missing (see the metrics catalog gap noted in section 5 and the toolkit's roadmap).
- **Real bets, not just paper picks** — everything in this design is explicitly paper-trading analysis (see section 1's goal and every report's disclaimer). Actually placing or tracking real wagers is a materially different feature: it would mean bet placement/tracking, bankroll management, and probably per-sportsbook account integration, none of which this design has addressed. This is a scope expansion to think through separately whenever it's actually tackled, not an extension of the current `picks_log`/grading design.
