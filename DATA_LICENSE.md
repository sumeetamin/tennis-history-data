# Data license and attribution

Tennis data compiled by **Jeff Sackmann / Tennis Abstract**.
Original projects: https://github.com/JeffSackmann
Archive used: https://github.com/Aneeshers/tennis-sackmann-archive
Pinned revision: 83733587353df8a41f2fd4f516147d5aa83f5a8d

The imported data and derived dataset are distributed under
**Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International**.
License: https://creativecommons.org/licenses/by-nc-sa/4.0/
Full legal text: https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode

Credit Jeff Sackmann / Tennis Abstract, link to the source and license, and
identify modifications. Non-commercial use only. Adaptations shared with
others must use the same license, consistent with its terms.

Modifications in this repository: source-category labeling, exact duplicate
match payload removal in the database, normalized tables with source
provenance, measured coverage reports, and historical prediction features.
Original source CSV bytes and license notices are preserved under data/raw.

No ownership of the original source data is claimed. The MIT code license
does not replace or expand the data license.

## Other source datasets and mixed-source exports

The Valuebetennis odds files are separately licensed under CC BY 4.0 and require attribution to Valuebetennis. The odds-enriched feature export combines those odds with Sackmann-derived features; preserve both sources' attribution and license terms. See `data/odds/README.md` for the exact scope and file-level notes. Do not assume every file in the repository has only the license stated above.

The player-profile supplement uses Wikidata structured facts, released under CC0. Its `tour`, `player_id`, and `wikidata_id` keys are carried from the Sackmann rosters, so the file remains a mixed-source derivative and the roster-derived identifiers retain the CC BY-NC-SA 4.0 obligations. See `data/processed/supplements/player_profile_enrichment_report.json` for source URL, item revisions and checksums.

