# Historical match odds

## Required correction for recent feature odds

Join `recent_odds_corrections.csv` onto `recent_model_features.csv.gz` by `record_id`. For matched IDs, replace **all four** `odds_open_p1_decimal`, `odds_open_p2_decimal`, `odds_close_p1_decimal`, and `odds_close_p2_decimal` fields with the correction values, including blanks. Unmatched feature rows keep their prices. The supplement repairs 5,368 price fields across 2,713 rows without rewriting existing feature bytes. Decimal prices that are missing, nonfinite or at most 1 are blank. This is a correction overlay, not a missing-value fallback.

The original builder incorrectly duplicated one player's odds in some orientations. Future appends use explicit source-player indexing for each model side. `scripts/correct_recent_odds.py` compares every recent row with the provider's exact player-name pair, tour, result label and prices, appends missing corrections and rejects conflicts with earlier corrections. `--verify-only` checks the complete overlay and its hashes without modifying it. The daily workflow runs both modes and enforces append-only corrections. These are Valuebetennis prices joined to Sackmann-derived identities and retain the source obligations documented below. Market timing remains provider-reported.

`atp_wta_match_odds.csv` combines the yearly ATP/WTA singles odds files published by Valuebetennis, preserving their fields and rows while converting the semicolon-separated source files to one comma-separated CSV. `genre` identifies `atp` or `wta`.

- Coverage: 2021 onward, for the provider's captured and settled singles matches.
- Odds: Pinnacle opening and last pre-match decimal odds for both listed players.
- Other fields: event/tournament, category, surface, round, players, result, score, and match duration where supplied.
- This is a separate source dataset. Its player/match IDs are Valuebetennis IDs and should not be treated as Sackmann IDs.
- Attribution: **Valuebetennis, Résultats et cotes de tennis depuis 2021**, https://www.valuebetennis.com/donnees.htm, CC BY 4.0.

The source does not include doubles or matches before 2021. The manifest records the source season hashes as well as the current combined CSV row counts, per-tour/per-year counts, byte size, and SHA-256. Daily appends update those combined-file checksums and counts from the actual CSV, without changing previously stored odds rows.

The upstream feed can contain missing scores, nonterminal-looking scores, or future-dated rows despite its settled-match description. The raw export is preserved as published; the daily updater only appends rows with a winner ID tied to one listed player and either (a) a completed score with the winner agreeing with the set score, or (b) an explicit retirement, walkover, or default marker. The score check is a conservative heuristic because the feed does not provide a separate settlement-status field. The dataset validator reports score-state counts and future-dated rows so questionable rows can be excluded deliberately downstream.

`linked_odds_sackmann.csv.gz` is a conservative one-to-one crosswalk to the repository's match archive. Primary links require exact normalized tour, tournament, and player-pair matches, a nearest archive event date within 14 days, and agreement on winner and player-1-oriented set scores. A labeled fallback handles event-title differences only when there is no exact-title candidate for the same tour/player pair, the unique nearest date is within 14 days, and the winner and full oriented set score agree exactly. Existing exact-title links take priority; ties and archive collisions are excluded. `link_method` distinguishes the fallback. The crosswalk preserves original odds fields and adds the Sackmann `record_id` plus matched archive fields. Counts and excluded-candidate reasons are in `odds_link_report.json`.

Regenerate the crosswalk after rebuilding either input dataset with:

```powershell
python scripts/link_odds_to_sackmann.py
```

The crosswalk's coverage is lower than the full odds CSV because the results archive has uneven ITF/Challenger coverage and source scores can disagree. It is a verified subset, not a claim that all odds rows can be linked.

`model_features_with_odds.csv.gz` joins those verified links to the pre-match feature rows and maps both opening and last pre-match Pinnacle prices into the feature table's `p1`/`p2` order. It excludes odds rows whose score state is incomplete, invalid, or unresolved; the raw odds and crosswalk keep them for audit. Prices are blank when a pair is unavailable; pair-availability flags are included. The file also fills missing/nonpositive ranks and blank ranking points from a weekly snapshot strictly before the tournament start date, no more than 90 days old. Per-player source and snapshot-date fields identify these fills. The existing `p1_won` column remains the target. Use opening prices for forecasts made earlier; use last pre-match prices only for a forecast made immediately before play. The build script and row/hash/price-coverage report are `scripts/build_model_features_with_odds.py` and `model_features_with_odds_report.json`.

This is a mixed-source derivative: the features and weekly ranking supplement retain Sackmann's CC BY-NC-SA 4.0 obligations and the odds require Valuebetennis CC BY 4.0 attribution. See the repository [data license notes](../../DATA_LICENSE.md). It is not a single-source odds file.

The daily GitHub Action checks a rolling 30-day window and appends newly published, settled rows whose `match_id` is not already present. It does not modify existing records, and it commits nothing when there are no new matches. Schedule delivery can be delayed by GitHub; it is not a live feed.

Before committing, the Action checks the full odds CSV against its manifest (required columns, unique IDs, ATP/WTA and yearly counts, byte size, and SHA-256). A mismatch fails the workflow before a commit is pushed.
It also checks that recent ranking/profile supplements match recent feature records, that ranking snapshots precede the match by no more than 90 days, that the 28-day model-history embargo holds, and that ages agree with birth dates and match dates.

The Action also runs `scripts/build_recent_odds_features.py`, which appends a separate post-archive feature file for settled matches whose players map uniquely through the existing strict crosswalk and whose names match observed crosswalk names. It skips future-dated rows, starts only after a 14-day buffer past the archive's latest tournament start date per tour, replays archive history, applies the standard 28-day embargo, and appends new odds and feature rows without rewriting existing rows. Unverified IDs and names are omitted. `recent_model_features_report.json` records its counts and checksum. These rows do not replace or alter the pinned archive exports.

`recent_ranking_fallbacks.csv.gz` is a separate append-only keyed supplement for those recent features. It uses the latest ATP/WTA weekly ranking snapshot strictly before the odds match date and no more than 90 days old, and fills only missing rank/ranking-point fields when joined by `record_id`. Each player side records its snapshot date and age. The daily Action appends values for newly eligible rows without rewriting the recent feature file; counts and hashes are in `recent_ranking_fallbacks_report.json`.

`recent_player_profiles.csv.gz` is a separate append-only supplement keyed by `record_id` for recent features. It derives age from birth date on the exact match date, and carries roster height and handedness when available. Each field has a source label. Birth dates and heights use the Sackmann roster first, then the matching CC0 Wikidata profile supplement. Height is a player profile value and is not guaranteed to be the player's measured height on that match date. Existing recent feature rows remain unchanged; see `recent_player_profiles_report.json` for coverage and checksums.

Rebuild or refresh the combined export with:

```powershell
python scripts/fetch_valuebetennis_odds.py
```

## 2025 consensus odds from multiple bookmakers

`sources/atp_wta_2025_closing_odds.csv` preserves all 5,791 source rows from **minmaxxxer, ATP and WTA 2025 closing odds and results**, published with **CC BY 4.0** metadata on [Hugging Face](https://huggingface.co/datasets/minmaxxxer/atp-wta-closing-odds-2025). The pinned revision is `9d8b6a741f8b26c2386e5556b4b1cc9cf6afd188`. The original dataset card is preserved in `sources/consensus_2025_UPSTREAM_README.md`; the report records source URLs, retrieval date and SHA-256. Season 2025 spans source match dates 2024-12-27 through 2025-12-21. This sample supplements the existing market data; it does not establish complete tournament coverage or extend odds before 2021.

The source reports opening/closing consensus probabilities and fair decimal odds, best closing prices, bookmaker counts, margin and line movement. The publisher describes removing each bookmaker's margin proportionally and taking the median across bookmaker brands. Fair odds are synthetic consensus prices, not executable quotes. Individual quote timestamps are unavailable; opening/closing timing is publisher-reported and not independently verified here.

Two additional files make the sample usable with this archive:

| File | Rows | Contents and ordering |
|---|---:|---|
| `multi_bookmaker_consensus_2025.csv.gz` | 4,957 | Audit crosswalk keyed by `record_id`. All market p1/p2 fields retain source player1/player2 order. `source_player1_archive_id` / `source_player2_archive_id` give the explicit Sackmann mapping. Includes outcome fields for auditing, so do not use it directly as a predictor matrix. |
| `model_features_with_consensus_odds_2025.csv.gz` | 4,802 | Existing 2024/2025 historical features with the added `odds_2025_*` prices and probabilities converted to model `p1_id` / `p2_id` order. Counts: 2,479 ATP and 2,323 WTA. `p1_won` is the target. |

Links require the same tour, matching abbreviated surname/first-initial pairs, a unique nearest event date within 14 days, and agreement on winner and every set's games (tiebreak detail is ignored). Exact normalized event titles are preferred (3,682 links); title fallbacks retain all other checks (1,275 links). Ambiguous matches, collisions without a unique nearest source row, and source-player IDs mapping to multiple archive IDs are excluded. Abbreviated names are weaker evidence than a shared authoritative player ID; the crosswalk records its matching method. Unmatched source records remain available in the original file.

The model export requires both a historical feature row and agreement that the match completed. Two otherwise eligible archive rows were excluded because the source marks retirement. Its player orientation uses mapped player IDs. Original historical features are preserved unchanged; source final score, result and `favorite_won` are not copied into it.

Quality audit: 131 of the 5,791 raw source price pairs are flagged: 129 contain a best-close price above twice the corresponding consensus fair odds, and two contain an invalid price. The ratio limit is a suspicious-price heuristic, not proof of a source error. Raw data and audit links preserve these values. For the 82 affected model rows, both best-close fields are blank and `odds_2025_best_close_pair_available` is 0; `odds_2025_best_close_quality_flags` explains the omission. Missing best prices are handled the same way. No individual quote timestamps establish that even an unflagged best price was available before play or executable.

Use source-reported opening columns only for an opening-time forecast. Closing columns, line movement and snapshot summaries such as bookmaker counts/margins belong only to a forecast at the relevant later time. See [modeling notes](../../docs/modeling.md) for the availability assumptions.

Rebuild and validate every new record from the tracked raw source and locally rebuilt SQLite archive:

```powershell
python scripts/build_2025_consensus_odds.py
python scripts/verify_2025_consensus_odds.py
```

`multi_bookmaker_consensus_2025_report.json` records counts, input/output hashes and policies; `consensus_2025_validation_report.json` records full-row verification. This is a pinned historical sample, not a daily-updated feed.

Attribution: **minmaxxxer, ATP and WTA 2025 closing odds and results, CC BY 4.0**, https://huggingface.co/datasets/minmaxxxer/atp-wta-closing-odds-2025; license https://creativecommons.org/licenses/by/4.0/. Changes: matched archive records, converted market player ordering, and filtered flagged best-price pairs in the model export. Both derived files additionally contain Sackmann data and retain its CC BY-NC-SA 4.0 obligations.
