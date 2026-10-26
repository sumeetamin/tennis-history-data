# Source strategy and coverage

This inventory is a starting point, not a guarantee of completeness. Confirm current availability and reuse terms before importing or publishing each source.

| Data area | Candidate source | Useful coverage | Notes |
| --- | --- | --- | --- |
| ATP/WTA results, rankings, player tables, some match stats | [Sackmann archive mirror](https://github.com/Aneeshers/tennis-sackmann-archive) | ATP/WTA historic CSVs; archive README reports snapshots through 2026 | Includes ATP tour, qualifying, Challenger and Futures files; WTA tour, qualifying, ITF and some ITF-qualifying files. It does not establish complete ITF coverage. Mirror says source data is CC BY-NC-SA 4.0. Preserve attribution and share-alike terms. |
| ATP/WTA settled singles results and pre-match odds | [Valuebetennis open CSVs](https://www.valuebetennis.com/donnees.htm) | 2021 onward; the repository's daily workflow checks a 30-day window | CC BY 4.0 with attribution. The workflow appends only missing `match_id` values; it does not revise existing rows. Its player IDs are separate from Sackmann IDs. |
| ATP/WTA/Challenger results and current updates | [TennisMyLife database](https://stats.tennismylife.org/tennis-match-database) | The site lists season files and Challenger files from 2018 onward | Its page warns that redistribution of raw data may require permission. Treat as a comparison or update source until written reuse terms are confirmed. |
| ATP/WTA/Challenger season CSVs, some odds/stat fields | [TennisData.App downloads](https://tennisdata.app/downloads/) | Public season CSV exports from 2021 onward | The download page invites personal use, but the [Terms of Service](https://tennisdata.app/terms/) prohibit copying, redistribution, and derivative works from its content without prior written permission and prohibit automated extraction. Do not ingest into this repo unless written permission clarifies reuse. |
| Historical ATP/WTA/Challenger/Futures result lookup | [Live Tennis API historical archive](https://docs.livetennisapi.com/historical-results-archive.html) | API docs describe results from 1968–2022 with player bios, rankings-at-match-time, and recorded serve stats | Useful for cross-checking coverage and player identities. It is a licensed API corpus; confirm storage and redistribution terms before putting results into a public repo. |
| Current and historical ITF tournament verification | [Official ITF results archive](https://www.itftennis.com/en/tournament-calendar/results/) | Searchable tournament results page | Useful for validating event names, dates, surfaces, winners, and final scores. Public access alone does not grant bulk redistribution rights. |
| Point-by-point and shot-level charting | [Match Charting Project](https://github.com/JeffSackmann/tennis_MatchChartingProject) | Crowdsourced charted matches, a subset of pro matches | Its README states CC BY-NC-SA 4.0 and non-commercial use; attribute contributors/project and keep the license. It is not complete match coverage. |
| Grand Slam point-by-point | [Grand Slam point-by-point archive](https://github.com/5ky9uy/pt-by-pt-at-grandslams) | Many main-draw singles matches from 2011 onward | Field coverage varies by tournament/year. Verify source provenance and reuse terms before redistribution. |
| Official profiles and event records | ATP, WTA, ITF, and tournament websites | Useful for checking identity and event facts | Do not bulk scrape or republish these sites without permission. ATP prohibits systematic retrieval of scores, stats, and rankings without prior written permission; WTA prohibits automated or mass collection without separate written permission; ITF restricts copying and redistribution of site content. See [collection policy](collection-policy.md). |

## Coverage policy

"Since the beginning" means the earliest verifiable record per tour, tier, event, and field, not a single universal start date. The Open Era begins in 1968, but some professional events, tours, rankings, and statistics have different histories. The initial archive has partial ITF coverage, so it cannot by itself satisfy a complete ITF-history goal. Challenger and ITF depth is especially uneven across eras. Publish a coverage report with the oldest and newest records and completeness rates for each data family.

## Before ingesting a source

1. Record the exact URL, retrieval date, provider, license or terms, and attribution requirement.
2. Confirm redistribution is allowed for the raw files and for normalized derivatives.
3. Keep source-specific terms attached to the data; do not assume all project data shares one license.
4. Capture a checksum and source revision where possible.
5. Compare sample rows with an independent source and document known gaps.

If rights are unclear, keep only source links and metadata in the public repo until permission or a clearly reusable source is found.
