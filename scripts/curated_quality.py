"""Conservative result checks for the curated release, separate from legacy exports."""
import math
import re


def decimal_price(value):
    try:
        return str(value) if math.isfinite(float(value)) and float(value) > 1 else ''
    except (ValueError, TypeError):
        return ''


def profile_height(value):
    """Keep plausible recorded centimetres; never guess a unit conversion."""
    try:
        return str(value) if math.isfinite(float(value)) and 100 <= float(value) <= 250 else ''
    except (ValueError, TypeError):
        return ''


def completed_result(row):
    """Require a complete ordinary singles score and an agreeing provider winner.

    Unknown scoring formats stay in the issue ledger. In particular, a two-set
    ATP Slam score cannot establish whether it is qualifying or an unfinished
    main-draw match when the source does not distinguish the two.
    """
    p1, p2, winner = (str(row.get(k) or '') for k in ('joueur1_id', 'joueur2_id', 'vainqueur_id'))
    if not p1 or not p2 or p1 == p2 or winner not in (p1, p2):
        return 'invalid_player_or_winner_id'
    score = (row.get('score') or '').strip()
    if not score:
        return 'missing_score'
    if not re.fullmatch(r'\d+[-–]\d+(?:\(\d+\))?(?:\s+\d+[-–]\d+(?:\(\d+\))?)*', score):
        return 'terminal_or_unsupported_score'
    sets = [(int(a), int(b)) for a, b in re.findall(r'(\d+)[-–](\d+)(?:\(\d+\))?', score)]
    best_of = 5 if row['genre'].lower() == 'atp' and row['categorie'].casefold() in ('grand chelem', 'grand slam') else 3
    required = best_of // 2 + 1
    wins = [0, 0]
    for a, b in sets:
        if max(wins) == required:
            return 'sets_after_match_decided'
        hi, lo = max(a, b), min(a, b)
        ordinary = (hi == 6 and 0 <= lo <= 4) or (hi == 7 and lo in (5, 6))
        advantage_decider = hi >= 8 and hi - lo == 2 and wins == [required - 1, required - 1]
        if not (ordinary or advantage_decider):
            return 'incomplete_or_unsupported_set'
        wins[0 if a > b else 1] += 1
    if max(wins) != required:
        return 'incomplete_or_unknown_match_format'
    if winner != (p1 if wins[0] > wins[1] else p2):
        return 'winner_score_disagreement'
    return 'completed'


def orient_score(score, winner_is_p1):
    if winner_is_p1:
        return score
    return re.sub(r'(\d+)([-–])(\d+)', lambda m: m[3] + m[2] + m[1], score)
