# Historical match odds

`atp_wta_match_odds.csv` combines the yearly ATP/WTA singles odds files published by Valuebetennis, preserving their fields and rows while converting the semicolon-separated source files to one comma-separated CSV. `genre` identifies `atp` or `wta`.

- Coverage: 2021 onward, for the provider's captured and settled singles matches.
- Odds: Pinnacle opening and last pre-match decimal odds for both listed players.
- Other fields: event/tournament, category, surface, round, players, result, score, and match duration where supplied.
- This is a separate source dataset. Its player/match IDs are Valuebetennis IDs and should not be treated as Sackmann IDs.
- Attribution: **Valuebetennis, Résultats et cotes de tennis depuis 2021**, https://www.valuebetennis.com/donnees.htm, CC BY 4.0.

The source does not include doubles or matches before 2021. The manifest records the source season hashes as well as the current combined CSV row counts, per-tour/per-year counts, byte size, and SHA-256. Daily appends update those combined-file checksums and counts from the actual CSV, without changing previously stored odds rows.

The upstream feed can contain missing scores, nonterminal-looking scores, or future-dated rows despite its settled-match description. The raw export is preserved as published; the daily updater only appends rows with a winner ID tied to one listed player and either (a) a completed score with the winner agreeing with the set score, or (b) an explicit retirement, walkover, or default marker. The score check is a conservative heuristic because the feed does not provide a separate settlement-status field. The dataset validator reports score-state counts and future-dated rows so questionable rows can be excluded deliberately downstream.

`linked_odds_sackmann.csv.gz` is a conservative one-to-one crosswalk to the repository's match archive. It includes only records with an exact normalized tour, tournament, and player-pair match, one nearest archive event date within 14 days, a unique closest odds record for each archive match, and agreement on winner and player-1-oriented set scores. It preserves the original odds fields and adds the Sackmann `record_id` plus the matched archive fields. Unmatched rows are intentionally omitted rather than guessed. Counts, hashes, and excluded-candidate reasons are in `odds_link_report.json`.

Regenerate the crosswalk after rebuilding either input dataset with:

```powershell
python scripts/link_odds_to_sackmann.py
```

The crosswalk's coverage is lower than the full odds CSV because the results archive has uneven ITF/Challenger coverage and source scores can disagree. It is a verified subset, not a claim that all odds rows can be linked.

The daily GitHub Action checks a rolling 30-day window and appends newly published, settled rows whose `match_id` is not already present. It does not modify existing records, and it commits nothing when there are no new matches. Schedule delivery can be delayed by GitHub; it is not a live feed.

Rebuild or refresh the combined export with:

```powershell
python scripts/fetch_valuebetennis_odds.py
```
