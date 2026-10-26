# Historical match odds

`atp_wta_match_odds.csv` combines the yearly ATP/WTA singles odds files published by Valuebetennis, preserving their fields and rows while converting the semicolon-separated source files to one comma-separated CSV. `genre` identifies `atp` or `wta`.

- Coverage: 2021 onward, for the provider's captured and settled singles matches.
- Odds: Pinnacle opening and last pre-match decimal odds for both listed players.
- Other fields: event/tournament, category, surface, round, players, result, score, and match duration where supplied.
- This is a separate source dataset. Its player/match IDs are Valuebetennis IDs and should not be treated as Sackmann IDs.
- Attribution: **Valuebetennis, Résultats et cotes de tennis depuis 2021**, https://www.valuebetennis.com/donnees.htm, CC BY 4.0.

The source does not include doubles or matches before 2021. The exact yearly file hashes and row counts used for this combined export are in `valuebetennis_manifest.json`.

The daily GitHub Action checks a rolling 30-day window and appends newly published, settled rows whose `match_id` is not already present. It does not modify existing records, and it commits nothing when there are no new matches. Schedule delivery can be delayed by GitHub; it is not a live feed.

Rebuild or refresh the combined export with:

```powershell
python scripts/fetch_valuebetennis_odds.py
```
