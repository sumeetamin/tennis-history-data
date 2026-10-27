# Tennis data sources and collection decisions

Research checked on 2026-10-27. This catalog separates sources already used in this repository, reusable sources that add a distinct data layer, and sources that require permission or a paid/private license. A public URL by itself is not permission to scrape, train on, or republish its contents.

## Used in this repository

| Source | What it contributes | Coverage / freshness | Reuse terms | Repository status |
| --- | --- | --- | --- | --- |
| [Jeff Sackmann / Tennis Abstract archive mirror](https://github.com/Aneeshers/tennis-sackmann-archive) | ATP/WTA results, event and player fields, rankings, scores, and available serve statistics across tour, Challenger, Futures, qualifying and ITF files | Historical archive; this repo pins a source revision and does not assert that it is a complete census | CC BY-NC-SA 4.0; attribution, non-commercial use and share-alike apply | Primary historical results source in `data/raw/` and `data/curated/post_2000/` |
| [Valuebetennis open match and odds CSVs](https://www.valuebetennis.com/donnees.htm) | ATP/WTA singles, Pinnacle opening and last pre-match odds, score, winner, surface, round and duration | 2021 onward; source says files are regenerated nightly; unfinished rows can appear in the feed | CC BY 4.0 with source attribution | `data/odds/atp_wta_match_odds.csv`; append-only, with verified/cautious crosswalks and recent feature supplements |
| [Tennis Abstract Match Charting Project](https://github.com/JeffSackmann/tennis_MatchChartingProject) | Contributor-charted match metadata and aggregate serve, return, net, rally, shot, return-depth, and error statistics | Small, selection-biased ATP/WTA subset; source files are updated periodically, not every day | CC BY-NC-SA 4.0; non-commercial, attribution and share-alike | Imported as a separately attributed supplement under `data/curated/match_charting/`; match links are conservative candidates, not official IDs |
| [Wikidata](https://www.wikidata.org/) | Player birth dates and heights for already-identified players | Open structured facts, varying field coverage | CC0 for structured data; retain provenance and any upstream obligations on player identifiers | Existing profile enrichment only fills supported missing fields |

The main match release is not a ready-to-train table. Use the ATP/WTA pre-match feature export for match prediction; keep match outcomes, box scores, charting aggregates and any other post-match fields out of a match's pre-match predictors. The charting supplement can support prior-only player tendencies if features are recomputed using matches that happened strictly before the prediction date.

## Good sources for validation or future licensed work

| Source | Potential value | Why it is not merged now |
| --- | --- | --- |
| [DataHub ATP World Tour dataset](https://datahub.io/core/atp-world-tour-tennis-data) | ATP tournament/match scores, match statistics, ranking files and player overviews; DataHub lists CC BY 4.0 | Its published snapshot is only current through 2017 and substantially overlaps the pinned archive. It is a useful independent validation candidate; compare field-level gains and provenance before importing a second copy. |
| [Baseline Today open tennis data](https://baseline-today.vercel.app/data) | Wikipedia-compiled ATP/WTA singles results since 2015; the publisher states CC BY-SA 4.0 | The advertised data page returned 404 when checked. Its share-alike license differs from the repository's CC BY-NC-SA source layer, so any future ingestion should remain a separate, clearly licensed dataset until compatibility is resolved. |
| [Live Tennis API academic dataset](https://livetennisapi.com/data/academic) | Recent ATP/WTA/Challenger/ITF match index and point sequences | Access is by research/teaching application, non-commercial academic use only, with an embargo. This personal public repository is not enrolled in that program. |
| [Cito API historical tennis archive](https://citoapi.com/historical-tennis-data/) | Advertises broad historical results, weekly rankings, profiles and statistics | API access needs a key; bulk CSV is a paid feature and redistribution terms have not been established for this repository. Use only after obtaining credentials and explicit reuse rights. |

## Not scraped or republished

- **Official ATP site:** its [terms](https://www.atptour.com/en/terms-and-conditions) reserve rights in scores, rankings, statistics and other content, prohibit systematic retrieval to compile a database, and require express permission for other uses. Request a data license instead of scraping it.
- **Official WTA site:** its [terms](https://www.wtatennis.com/terms-and-conditions) prohibit automated or mass collection and copying, derivative works or distribution without authorization.
- **ITF World Tennis Portal:** its [portal terms](https://contentportal.itftennis.com/terms_and_conditions) prohibit automated scripts and state that portal content cannot be stored or republished elsewhere without written consent.
- **Tennis-Data.co.uk:** it lists many years of bookmaker odds, but its [data-use notice](https://www.tennis-data.co.uk/contact.php) says the data is for private individuals and not commercial or data-training products using automated bots/scrapers/AI. It is therefore excluded from this predictive-model repository.
- **TennisData.app:** free downloadable seasons include results and odds, but its [terms](https://tennisdata.app/terms/) prohibit scraping/systematic extraction and republication or derivative works without prior written permission. A download link is not a redistribution license.
- **TennisMyLife / TML database:** it offers useful recent ATP/WTA files and player IDs, but its [public source repository](https://github.com/migumax/tennis_atp) states that redistribution of the raw database requires permission and its page describes mixed-source collection. Do not bulk copy it into this public repo until the publisher confirms licensing in writing.
- **Paid commercial feeds (for example BALLDONTLIE, Sportradar, or bookmaker APIs):** potentially useful for current matches, rankings, stats and odds, but they require credentials/payment and do not imply permission to republish the raw feed. No paid account or redistribution license is configured here.

## What would move completeness further

1. Obtain written ATP/WTA/ITF permission or a redistribution license for official draws, results, rankings, player profiles and match statistics.
2. Obtain an odds-provider license covering historical bookmaker prices before adding sources whose terms prohibit model training or republication.
3. Compare the CC BY 4.0 DataHub ATP archive with this repo and add only verified non-duplicate fields or matches, with per-row provenance.
4. Use Wikipedia-derived results only as a separate CC BY-SA 4.0 collection unless the licensing relationship to the main data is resolved.
5. Keep an independent expected-event calendar and draw list. Without it, observed source rows and tournament counts cannot prove that every tournament or match is present.

## Sources checked

- [ATP terms](https://www.atptour.com/en/terms-and-conditions)
- [WTA terms](https://www.wtatennis.com/terms-and-conditions)
- [ITF World Tennis Portal terms](https://contentportal.itftennis.com/terms_and_conditions)
- [Sackmann archive license and pinned source](https://github.com/Aneeshers/tennis-sackmann-archive)
- [Match Charting Project license and file documentation](https://github.com/JeffSackmann/tennis_MatchChartingProject)
- [Valuebetennis data and CC BY 4.0 terms](https://www.valuebetennis.com/donnees.htm)
- [Tennis-Data use notice](https://www.tennis-data.co.uk/contact.php)
- [TennisData.app terms](https://tennisdata.app/terms/)
- [Wikidata license](https://www.wikidata.org/wiki/Wikidata:Licensing)
