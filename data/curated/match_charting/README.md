# Match Charting Project supplement

This folder adds a licensed, contributor-charted ATP/WTA statistics layer. The source is the [Tennis Abstract Match Charting Project](https://github.com/JeffSackmann/tennis_MatchChartingProject), licensed CC BY-NC-SA 4.0. Attribution and the original source data dictionary are retained in `manifest.json`, `UPSTREAM_README.md` and `data_dictionary.txt`.

The update imported the ATP/WTA match metadata and every published match-level aggregate statistics table in the source revision. The tables preserve the source column names and are compressed CSVs under `matches/` and `stats/`. They include match-level and per-set serving, returning, key-point, net, rally, shot-direction, shot-type, return-depth and error summaries. This source is a selected charted-match sample, not an exhaustive event or match database.

The pinned revision contains **11,822 unique charted matches** and **3,085,083 aggregate-stat rows**. The conservative matcher yields **10,282 unique archive candidates**, 18 ambiguous matches and 1,522 matches with no candidate under its rules. Those counts are current to the recorded source revision; see `manifest.json` for per-table hashes and updated values.

## Match links

`match_links.csv.gz` maps charting `match_id` values to candidate records in `../post_2000/matches/`. Candidate generation requires the same tour, exact normalized unordered player-name pair, the same year, event/match-date distance of at most 14 days, and surface agreement when both sources provide a surface. The nearest candidate must be unique. A `unique_pair_nearest_date_candidate` is still a conservative candidate link, not an official identifier or independently score-verified match. Keep `ambiguous_candidate_tie` and unmatched rows visible instead of guessing.

When the source corrects an existing match's chart metadata, `match_link_corrections.csv.gz` records the replacement candidate rows keyed by `chart_match_id`. Apply the latest correction row for a matching ID over the base link table. `source_corrections.csv.gz` similarly contains full latest source rows for changed upstream keys, keyed by `source_file` and `source_key`. A small number of malformed source metadata rows can be reconstructed from the source `match_id`; the manifest counts those separately. These overlays preserve the previously published rows; no base row is rewritten.

## Modeling cautions

These are match outcomes and post-match statistics. Do not use a match's own charted totals as predictors of that match's winner. They can support historical summaries of a player's style only when a model feature is calculated from charted matches that finished before the target match. Availability is sparse and biased toward well-known players, tournaments and matches with accessible video. Hand annotations can contain errors or differing interpretations.

The source also publishes raw point-by-point shot sequences. This repository currently imports the metadata and all aggregate match-stat tables; it does not mirror the much larger point-sequence files. The source links and notation documentation are available in `UPSTREAM_README.md` and `data_dictionary.txt`.

## Refresh and preservation

```sh
python scripts/update_match_charting_project.py
```

The script checks the source Git revision and exits without changing files if it is already current. On a new upstream revision it appends unseen source keys, keeps old records, records changed values in the correction overlays, and rebuilds candidate links only for newly added chart metadata. The daily GitHub Action runs this updater. Review `manifest.json` for the exact source commit, file hashes, counts, skipped malformed source rows and changed-key counts.

## License

The source and this transformed supplement are CC BY-NC-SA 4.0. Cite **Crowdsourced shot-by-shot professional tennis data by The Tennis Abstract Match Charting Project**, link to <https://github.com/JeffSackmann/tennis_MatchChartingProject> and <https://creativecommons.org/licenses/by-nc-sa/4.0/>, and indicate changes. Non-commercial use and share-alike terms apply. The main repository also contains Valuebetennis odds under its separate CC BY 4.0 license; see the root [data source catalog](../../../docs/data-sources.md) and [license notes](../../../DATA_LICENSE.md).
