# Coverage dashboard

Generated from **1,267,424** post-2000 published match rows and **148,819** main-tour feature rows. Coverage counts are row availability, not proof that every real-world event is present.

The machine-readable marginal breakdown is [`coverage_dimensions.csv`](../data/curated/post_2000/coverage_dimensions.csv); the complete report and definitions are in [`coverage_report.json`](../data/curated/post_2000/coverage_report.json). Each row reports population size, field-present rows, missing rows, and percent present for the selected dimension.

## Population split

| Tour | Population | Rows |
|---|---|---:|
| atp | atp_wta_tour_main_draw | 79,625 |
| atp | challenger_main_draw | 131,351 |
| atp | itf_or_futures_main_draw | 419,885 |
| atp | qualifier | 61,018 |
| atp | unclassified | 7,161 |
| wta | atp_wta_tour_main_draw | 73,029 |
| wta | itf_or_futures_main_draw | 378,103 |
| wta | qualifier | 113,335 |
| wta | unclassified | 3,917 |

## Timing and known gaps

- Exact match start timestamps and local time zones are not present in the result source.
- Odds rows have opening and provider-reported last pre-match prices for two players where available, but not verified individual quote timestamps or a quote time zone.
- Result-publication timestamps are not present. Tournament dates and assumed delays are not substituted for them.
- A missing ranking, score, duration, or statistic remains missing. The dashboard counts its absence explicitly.
- Qualifiers, Challenger main draws, Futures/ITF main draws, WTA ITF rows, and tour main draws are measured in separate population categories where source fields permit classification.

Report CSV SHA-256: `24c3e9a69fc191b0d30e901b1cfdfbd81140c2d314839434962fc408974f3e64`.
