---
license: cc-by-4.0
pretty_name: ATP and WTA 2025 Closing Odds and Results
language:
- en
tags:
- sports
- tennis
- atp
- wta
- odds
- closing-line
- sports-analytics
- backtesting
task_categories:
- tabular-classification
- tabular-regression
size_categories:
- 1K<n<10K
configs:
- config_name: default
  data_files: atp_wta_2025_closing_odds.csv
---

# ATP and WTA 2025 closing odds and results

**5,791 singles matches of the 2025 ATP and WTA tours** (main draws of 148 tournaments, the Grand Slams
included) with the betting market's **consensus opening and closing match-winner odds**, the best price available at the
close, the line movement and the result. One row per match, ready for pandas, R, SQL or a spreadsheet.

Built for backtesting tennis models, closing line value (CLV) research, upset analysis and sports-analytics teaching.

## Quick look

| | |
|---|---|
| Matches (ATP / WTA) | 5,791 (2,949 / 2,842) |
| Closing favourites winning (walkovers excluded) | 68.8% |
| … on hard / clay / grass | 67.0% / 68.9% / 68.2% |
| Underdogs at fair closing odds of 3.00+ who won | 20.6% of 2,754 matches |
| Bookmakers per match (median) | 21 |
| Median bookmaker margin | 5.7% |

```python
import pandas as pd
df = pd.read_csv("hf://datasets/minmaxxxer/atp-wta-closing-odds-2025/atp_wta_2025_closing_odds.csv")
df.groupby(["tour", "surface"]).favorite_won.mean().unstack()     # how often the favourite wins, by surface
```

## Columns

| Column | Meaning |
|---|---|
| `match_id` | Stable match ID (Flashscore) |
| `date_utc`, `start_time_utc` | Match day and start, UTC |
| `season`, `tour` | Season; `ATP` or `WTA` |
| `tournament`, `tournament_country`, `surface` | Tournament, host country, `hard` / `clay` / `grass` (indoor hard courts are `hard`) |
| `player1`, `player2`, `player1_country`, `player2_country`, `player1_id`, `player2_id` | Players as listed by the source (player 1 = the first-named), countries and stable IDs |
| `status` | `finished`; `retired` and `walkover` matches are kept and marked |
| `winner`, `sets_won1`, `sets_won2`, `score` | Winner (1 or 2), sets won, score by set |
| `bookmakers` | Bookmaker brands in the consensus |
| `open_prob1`, `close_prob1` | No-vig probability that player 1 wins, at the opening and at the close |
| `open_fair_odds1`, `open_fair_odds2`, `close_fair_odds1`, `close_fair_odds2` | Fair (no-vig) decimal odds of both players at the opening and the close |
| `best_close_odds1`, `best_close_odds2` | Best decimal price on each player among the bookmakers at the close |
| `prob_move_pts` | Move of player 1's probability from the opening to the close, in percentage points |
| `margin_pct` | Median bookmaker margin on the match |
| `favorite`, `favorite_won` | Closing favourite (1 or 2) and whether it won |

## How it was made

Opening and latest (= closing, once the match started) match-winner odds of every bookmaker that priced the match were
collected; each bookmaker's margin was removed proportionally and the **median across bookmaker brands** taken (a brand
listed under several licences counts once). Qualifying rounds, doubles and matches no bookmaker priced are not included.

## Want more?

This file is a free sample. The **[Tennis Odds Actor](https://minmaxxxer.dev/hf-tennis2025)** produces the same data — plus the **opening and closing
price of each bookmaker**, live scores, current ATP/WTA rankings, match statistics and point-by-point — for ATP, WTA,
Challenger and ITF events, today's and upcoming matches, and **any tournament back to 2009**. Python and API access,
CSV / Excel / JSON export, pay per match.

Data compiled from publicly available match and odds information; not affiliated with the ATP, the WTA, Flashscore or any
bookmaker. For research and analysis.
