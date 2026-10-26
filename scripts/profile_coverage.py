"""Measure post-2000 match-stat and player-profile completeness from SQLite."""
import hashlib
import csv
import gzip
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data/processed/tennis.sqlite'
OUT = ROOT / 'data/processed/post_2000_coverage_report.json'
DOC = ROOT / 'docs/post-2000-coverage.md'
ODDS = ROOT / 'data/odds/atp_wta_match_odds.csv'
ODDS_MANIFEST = ROOT / 'data/odds/valuebetennis_manifest.json'
LINK_REPORT = ROOT / 'data/odds/odds_link_report.json'
ODDS_FEATURE_REPORT = ROOT / 'data/odds/model_features_with_odds_report.json'
RECENT_FEATURE_REPORT = ROOT / 'data/odds/recent_model_features_report.json'
RECENT_RANK_REPORT = ROOT / 'data/odds/recent_ranking_fallbacks_report.json'
RECENT_PROFILE_REPORT = ROOT / 'data/odds/recent_player_profiles_report.json'
RANK_FALLBACK_REPORT = ROOT / 'data/processed/supplements/ranking_fallbacks_report.json'
PROFILE_ENRICHMENT = ROOT / 'data/processed/supplements/player_profile_enrichment.csv.gz'
PROFILE_ENRICHMENT_REPORT = ROOT / 'data/processed/supplements/player_profile_enrichment_report.json'
VALIDATION_REPORT = ROOT / 'data/processed/validation_report.json'
START_DATE = '2000-01-01'


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def percentage(count, total):
    return round(100 * count / total, 2) if total else None


def main():
    if not DB.is_file():
        raise SystemExit('Build data/processed/tennis.sqlite first with scripts/build_dataset.py')
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        matches = []
        for row in db.execute('''SELECT tour,category,count(*) AS matches,
                sum(CASE WHEN CAST(w_svpt AS REAL)>0 AND CAST(l_svpt AS REAL)>0 THEN 1 ELSE 0 END) AS both_serve_stats,
                sum(CASE WHEN CAST(winner_rank AS REAL)>0 AND CAST(loser_rank AS REAL)>0 THEN 1 ELSE 0 END) AS both_ranked,
                sum(CASE WHEN CAST(minutes AS REAL)>0 THEN 1 ELSE 0 END) AS minutes_recorded,
                sum(CASE WHEN surface IS NOT NULL AND surface!='' THEN 1 ELSE 0 END) AS surface_recorded,
                min(event_date) AS first_event_date,max(event_date) AS last_event_date
            FROM matches WHERE event_date>=? GROUP BY tour,category ORDER BY tour,category''', (START_DATE,)):
            total = row['matches']
            matches.append({
                'tour': row['tour'], 'category': row['category'], 'matches': total,
                'both_serve_stats': row['both_serve_stats'],
                'both_serve_stats_pct': percentage(row['both_serve_stats'], total),
                'both_ranked': row['both_ranked'],
                'both_ranked_pct': percentage(row['both_ranked'], total),
                'minutes_recorded': row['minutes_recorded'],
                'minutes_recorded_pct': percentage(row['minutes_recorded'], total),
                'surface_recorded': row['surface_recorded'],
                'surface_recorded_pct': percentage(row['surface_recorded'], total),
                'first_event_date': row['first_event_date'], 'last_event_date': row['last_event_date'],
            })

        profiles = []
        appearances = '''
            SELECT tour,winner_id AS player_id FROM matches WHERE event_date>=?
            UNION SELECT tour,loser_id FROM matches WHERE event_date>=?
        '''
        for row in db.execute(f'''SELECT p.tour,count(*) AS players,
                sum(CASE WHEN p.dob IS NOT NULL AND p.dob!='' THEN 1 ELSE 0 END) AS date_of_birth,
                sum(CASE WHEN p.height IS NOT NULL AND p.height!='' THEN 1 ELSE 0 END) AS height,
                sum(CASE WHEN p.hand IS NOT NULL AND p.hand!='' THEN 1 ELSE 0 END) AS hand,
                sum(CASE WHEN p.ioc IS NOT NULL AND p.ioc!='' THEN 1 ELSE 0 END) AS country,
                sum(CASE WHEN p.wikidata_id IS NOT NULL AND p.wikidata_id!='' THEN 1 ELSE 0 END) AS wikidata_id
            FROM players p JOIN ({appearances}) a USING(tour,player_id)
            GROUP BY p.tour ORDER BY p.tour''', (START_DATE, START_DATE)):
            total = row['players']
            fields = ('date_of_birth', 'height', 'hand', 'country', 'wikidata_id')
            profiles.append({
                'tour': row['tour'], 'players': total,
                **{field: row[field] for field in fields},
                **{field + '_pct': percentage(row[field], total) for field in fields},
            })
        appearance_ids = {(row[0], row[1]) for row in db.execute('''
            SELECT tour,winner_id AS player_id FROM matches WHERE event_date>=?
            UNION SELECT tour,loser_id FROM matches WHERE event_date>=?
        ''', (START_DATE, START_DATE))}

    enriched_players = {}
    with gzip.open(PROFILE_ENRICHMENT, 'rt', encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            key = (row['tour'], row['player_id'])
            if key not in appearance_ids:
                continue
            fields = enriched_players.setdefault(row['tour'], {'date_of_birth': 0, 'height': 0})
            fields['date_of_birth'] += bool(row['date_of_birth_fallback'])
            fields['height'] += bool(row['height_cm_fallback'])
    profile_enrichment_report = json.loads(PROFILE_ENRICHMENT_REPORT.read_text(encoding='utf-8'))
    for profile in profiles:
        additions = enriched_players.get(profile['tour'], {})
        for field in ('date_of_birth', 'height'):
            added = additions.get(field, 0)
            profile[f'{field}_wikidata_added'] = added
            profile[f'{field}_after_wikidata'] = profile[field] + added
            profile[f'{field}_after_wikidata_pct'] = percentage(profile[f'{field}_after_wikidata'], profile['players'])

    odds_dates = []
    with ODDS.open(encoding='utf-8-sig', newline='') as stream:
        for odds_row in csv.DictReader(stream):
            if odds_row.get('date'):
                odds_dates.append(odds_row['date'][:10])
    odds_manifest = json.loads(ODDS_MANIFEST.read_text(encoding='utf-8'))
    link_report = json.loads(LINK_REPORT.read_text(encoding='utf-8'))
    odds_feature_report = json.loads(ODDS_FEATURE_REPORT.read_text(encoding='utf-8'))
    recent_feature_report = json.loads(RECENT_FEATURE_REPORT.read_text(encoding='utf-8'))
    recent_rank_report = json.loads(RECENT_RANK_REPORT.read_text(encoding='utf-8'))
    recent_profile_report = json.loads(RECENT_PROFILE_REPORT.read_text(encoding='utf-8'))
    rank_fallback_report = json.loads(RANK_FALLBACK_REPORT.read_text(encoding='utf-8'))
    validation_report = json.loads(VALIDATION_REPORT.read_text(encoding='utf-8')) if VALIDATION_REPORT.exists() else {}
    odds_coverage = {
        'rows': odds_manifest['rows'],
        'rows_by_tour': odds_manifest['rows_by_tour'],
        'rows_by_year': odds_manifest.get('rows_by_year', {}),
        'first_match_date': min(odds_dates) if odds_dates else None,
        'last_match_date': max(odds_dates) if odds_dates else None,
        'strict_archive_links': link_report['counts']['linked_score_and_winner_verified'],
        'exact_event_links': link_report['counts']['linked_score_and_winner_verified'] - link_report['counts'].get('linked_event_name_fallback', 0),
        'event_title_fallback_links': link_report['counts'].get('linked_event_name_fallback', 0),
        'odds_enriched_feature_rows': odds_feature_report['rows'],
        'odds_enriched_opening_price_pairs': odds_feature_report['opening_odds_pair_rows'],
        'odds_enriched_last_pre_match_price_pairs': odds_feature_report['last_pre_match_odds_pair_rows'],
        'recent_model_feature_rows': recent_feature_report['total_rows'],
        'recent_model_feature_date_range': recent_feature_report['date_range'],
        'recent_model_rows_with_rank_fallbacks': recent_rank_report['total_rows_with_fallbacks'],
        'recent_model_rank_fills': recent_rank_report['rank_fills'],
        'recent_model_rank_points_fills': recent_rank_report['rank_points_fills'],
        'recent_model_rank_fallback_rows_by_tour': recent_rank_report['rows_by_tour'],
        'recent_model_profile_rows': recent_profile_report['rows_with_profile_data'],
        'recent_model_age_values': recent_profile_report['field_values']['age'],
        'recent_model_height_profile_values': recent_profile_report['field_values']['height'],
        'recent_model_hand_values': recent_profile_report['field_values']['hand'],
        'recent_model_profile_values_by_tour': recent_profile_report['field_values_by_tour'],
        'score_state_counts': validation_report.get('odds_score_state_counts', {}),
        'future_dated_rows': validation_report.get('odds_future_dated_rows_as_of_utc_date', []),
    }
    report = {
        'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'event_date_inclusive': START_DATE,
        'source_database': {'path': 'data/processed/tennis.sqlite', 'sha256': sha256(DB)},
        'match_coverage_by_tour_and_tier': matches,
        'player_profile_completeness_for_players_with_post_2000_matches': profiles,
        'wikidata_profile_enrichment': {
            'license': profile_enrichment_report['license'],
            'requested_unique_entities': profile_enrichment_report['requested_unique_entities'],
            'output': profile_enrichment_report['output'],
            'post_2000_player_fields_added': enriched_players,
            'policy': profile_enrichment_report['policy'],
        },
        'separate_odds_dataset': odds_coverage,
        'weekly_ranking_fallbacks': {
            'rows_with_at_least_one_fallback': rank_fallback_report['rows_with_at_least_one_fallback'],
            'output': rank_fallback_report['output'],
            'post_2000_coverage_by_tour_and_category': rank_fallback_report['post_2000_coverage_by_tour_and_category'],
            'policy': rank_fallback_report['policy'],
        },
        'definitions': {
            'both_serve_stats': 'Both players have positive recorded service points (w_svpt and l_svpt).',
            'both_ranked': 'Both match-file ranking fields are positive before any weekly-ranking fallback.',
            'minutes_recorded': 'Positive match duration recorded.',
            'profile_population': 'Unique player IDs appearing as winner or loser in an archive match dated on/after the start date.',
            'event_dates': 'Generally tournament start dates; they are not exact match dates.',
        },
        'limitations': [
            'Coverage counts describe records present in the pinned archive and do not establish tournament completeness.',
            'The source archive has uneven Challenger and ITF/Futures coverage, and many lower-tier matches lack serve statistics.',
        ],
    }
    OUT.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    lines = [
        '# Post-2000 data completeness', '',
        f"Measured from the pinned archive for event dates on/after {START_DATE}. The archive currently contains **{sum(row['matches'] for row in matches):,}** match rows across the tiers listed below. These are source-record counts, not proof that every real-world event is present.", '',
        '## Match and statistics coverage', '',
        '| Tour | Category | Matches | Both serve stats | Both ranked | Duration | Surface | Event date range |',
        '|---|---|---:|---:|---:|---:|---:|---|',
    ]
    for row in matches:
        lines.append(
            f"| {row['tour']} | {row['category']} | {row['matches']:,} | {row['both_serve_stats']:,} ({row['both_serve_stats_pct']:.1f}%) | "
            f"{row['both_ranked']:,} ({row['both_ranked_pct']:.1f}%) | {row['minutes_recorded']:,} ({row['minutes_recorded_pct']:.1f}%) | "
            f"{row['surface_recorded']:,} ({row['surface_recorded_pct']:.1f}%) | {row['first_event_date']} to {row['last_event_date']} |"
        )
    lines += [
        '', '“Both serve stats” means both players have positive recorded service points. “Both ranked” means both match-time rank fields are positive before the fallback. “Duration” means minutes are present. Event dates are usually tournament start dates, not exact match dates.', '',
        '## Pre-event ranking fallback for model features', '',
        f"The keyed supplement contains {rank_fallback_report['rows_with_at_least_one_fallback']:,} feature rows with at least one rank or ranking-points value recovered from a weekly snapshot. A snapshot must strictly precede the tournament start date and be no more than 90 days old. These counts apply to the completed-match feature export, after its exclusions.", '',
        '| Tour | Category | Feature matches | Both ranked before | Both ranked with fallback | Rank values filled | Ranking-point values filled |',
        '|---|---|---:|---:|---:|---:|---:|',
    ]
    for tour, categories in rank_fallback_report['post_2000_coverage_by_tour_and_category'].items():
        for category, values in categories.items():
            lines.append(
                f"| {tour} | {category} | {values['eligible_matches']:,} | {values['both_ranked_before']:,} ({values['both_ranked_before_pct']:.2f}%) | "
                f"{values['both_ranked_after']:,} ({values['both_ranked_after_pct']:.2f}%) | {values.get('rank_fills', 0):,} | {values.get('rank_points_fills', 0):,} |"
            )
    lines += [
        '', 'The main yearly feature files remain unchanged; join the supplement on `record_id` and use it only to fill blank or nonpositive rank values. The odds-enriched feature file already applies these fallbacks and carries per-player provenance columns.', '',
        '## Player profile coverage', '',
        '| Tour | Players appearing since 2000 | Date of birth | Height | Hand | Country | Wikidata ID |',
        '|---|---:|---:|---:|---:|---:|---:|',
    ]
    for row in profiles:
        lines.append(
            f"| {row['tour']} | {row['players']:,} | {row['date_of_birth']:,} ({row['date_of_birth_pct']:.1f}%) | "
            f"{row['height']:,} ({row['height_pct']:.1f}%) | {row['hand']:,} ({row['hand_pct']:.1f}%) | "
            f"{row['country']:,} ({row['country_pct']:.1f}%) | {row['wikidata_id']:,} ({row['wikidata_id_pct']:.1f}%) |"
        )
    lines += [
        '', 'Player completeness is measured among unique player IDs appearing in post-2000 archive matches. It is not the percentage of all professional players identified.', '',
        '## CC0 player-profile supplement', '',
        'The roster tables above show values present in the pinned archive. A separate supplement uses only existing Wikidata IDs and fills only missing/invalid birth dates or heights. It does not alter the source player files. Birth dates require day precision; heights are converted to centimeters and restricted to 130–230 cm. Conflicting Wikidata values are omitted.', '',
        '| Tour | Birth dates added | DOB coverage after supplement | Heights added | Height coverage after supplement |',
        '|---|---:|---:|---:|---:|',
    ]
    for row in profiles:
        lines.append(
            f"| {row['tour']} | {row['date_of_birth_wikidata_added']:,} | {row['date_of_birth_after_wikidata']:,} ({row['date_of_birth_after_wikidata_pct']:.1f}%) | "
            f"{row['height_wikidata_added']:,} | {row['height_after_wikidata']:,} ({row['height_after_wikidata_pct']:.1f}%) |"
        )
    lines += [
        '', 'The supplement is keyed by `(tour, player_id)` and is licensed CC0 for Wikidata structured facts; its player IDs are derived from the Sackmann rosters and retain those source obligations. Height is a player profile value, not a historical height-at-match value. See `data/processed/supplements/player_profile_enrichment_report.json` for hashes, revision IDs and field counts.', '',
        '## Odds coverage', '',
        f"The separately attributed odds CSV contains **{odds_coverage['rows']:,}** singles rows with dates from {odds_coverage['first_match_date']} to {odds_coverage['last_match_date']}, with {odds_coverage['strict_archive_links']:,} verified links to archive matches ({odds_coverage['exact_event_links']:,} exact event-title links and {odds_coverage['event_title_fallback_links']:,} event-title fallback links). The fallback requires the same tour and normalized player pair, no exact-title candidate, a unique nearest archive date within 14 days, and exact winner plus player-oriented set-score agreement. It intentionally omits ambiguous or unverified candidates.",
        f"The validation report classifies score states as `{json.dumps(odds_coverage['score_state_counts'], sort_keys=True)}` and currently flags {len(odds_coverage['future_dated_rows'])} future-dated row(s) as of the last validator run. Filter these rows and nonterminal/unknown score states for modeling.", '',
        f"An odds-enriched pre-match feature file is also available for {odds_coverage['odds_enriched_feature_rows']:,} rows. It has {odds_coverage['odds_enriched_opening_price_pairs']:,} complete opening-price pairs and {odds_coverage['odds_enriched_last_pre_match_price_pairs']:,} complete last-pre-match-price pairs, oriented to feature p1/p2.", '',
        f"A separate append-only recent model feature file contains {odds_coverage['recent_model_feature_rows']:,} rows from {odds_coverage['recent_model_feature_date_range'][0]} to {odds_coverage['recent_model_feature_date_range'][1]}, beyond the pinned archive cutoff. It uses verified player-ID aliases, a 14-day archive-end buffer, and the 28-day feature-history embargo. A keyed weekly-ranking supplement provides {odds_coverage['recent_model_rank_fills']:,} rank and {odds_coverage['recent_model_rank_points_fills']:,} ranking-point values across {odds_coverage['recent_model_rows_with_rank_fallbacks']:,} matches, from snapshots strictly before match date and no more than 90 days old. The keyed profile supplement adds {odds_coverage['recent_model_age_values']:,} ages at match date, {odds_coverage['recent_model_height_profile_values']:,} static profile heights, and {odds_coverage['recent_model_hand_values']:,} handedness values across {odds_coverage['recent_model_profile_rows']:,} matches. Height is not a historical measurement.", '',
        '## Limits', '',
        '- ITF/Futures and Challenger coverage is uneven; the counts above do not establish complete event coverage.',
        '- Lower-tier serve statistics are sparse, and many height and WTA birth-date values are missing.',
        '- The results/rankings archive is frozen at its pinned source revision. The odds feed is maintained separately by the daily append-only action.',
        '- Regenerate this report after rebuilding the SQLite database and refreshing odds/crosswalk inputs with `python scripts/profile_coverage.py`.', '',
        f"Report source database SHA-256: `{sha256(DB)}`.",
    ]
    DOC.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({
        'report': OUT.relative_to(ROOT).as_posix(),
        'documentation': DOC.relative_to(ROOT).as_posix(),
        'match_rows': sum(row['matches'] for row in matches),
        'match_groups': len(matches),
        'players_by_tour': {row['tour']: row['players'] for row in profiles},
    }, indent=2))


if __name__ == '__main__':
    main()
