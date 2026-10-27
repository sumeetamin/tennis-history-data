# ATP/WTA source gaps and next evidence needed

Sources checked on 27 October 2026. Source availability is different from the
number of valid, identity-resolved matches accepted into the research release.

| Source | Useful data | Limits and next action |
|---|---|---|
| [Valuebetennis](https://www.valuebetennis.com/donnees.htm) | 2021 onward results and opening/last-pre-match Pinnacle decimal odds; match datetime declared UTC; event category, provider IDs, round codes | CC BY 4.0. No individual quote timestamps. Documented round endpoints are 0 pre-qualification and 12 final; intermediate codes must not be guessed. Reconcile settled scores before admission. |
| [Sackmann archival mirror](https://github.com/Aneeshers/tennis-sackmann-archive) | Historical matches, weekly rankings and player identities used in this repo | Pinned archive and CC BY-NC-SA 4.0. Existing ranking snapshots end 8 June 2026. Later historical rankings require a dated source; current ranking cannot fill old matches. |
| [WTA official ranking PDF](https://wtafiles.wtatennis.com/pdf/rankings/Singles_Numeric.pdf) | Official snapshot explicitly dated 26 October 2026, printed 25 October; ranking and points | Current snapshot is evidence for that date, not earlier months. [WTA terms](https://www.wtatennis.com/terms-and-conditions) restrict automated collection and republication without permission; no ranking table imported here. |
| [Kick-Serve data](https://kick-serve.com/data/) | Published ATP/WTA CSV/JSON exports with official_rank, points, player identifiers, and separately labelled model ratings | Page offers reuse with attribution and asks commercial redistributors to contact the publisher. Candidate only: row identity, exact snapshot date and underlying data provenance need validation before integration. Never backdate a current snapshot. |
| [Grand Slam point-by-point archive](https://github.com/AngieXuAU/tennis-point-by-point-archive) | Point-level history and derived serve/return summaries already included separately | Limited event/year coverage and non-commercial share-alike terms; cannot establish all-tour statistics. |

Full match completeness requires an independently reconciled event/calendar and
draw census for each tour and season. Exact historical odds validity requires a
source providing both players' prices, market, bookmaker, quote time and match
start time. Injury information requires a reliable publication timestamp. These
are missing evidence, not values that can be safely imputed.
