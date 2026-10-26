"""Shared score-state checks for the Valuebetennis singles feed."""
import re

_SET_RE = re.compile(r'(\d+)\s*[-–]\s*(\d+)(?:\(\d+\))?')


def settlement_status(row):
    """Classify a row; result and score must indicate a settled match to append it.

    Retirement, walkover, and default rows are explicit terminal outcomes.
    Ordinary scores must contain completed set scores through the deciding set.
    """
    score = (row.get('score') or '').strip().upper()
    if not score:
        return 'missing_score'
    if re.search(r'\b(W/O|WO|WALKOVER)\b', score):
        return 'walkover'
    if re.search(r'\b(RET|RETIRED)\b', score):
        return 'retirement'
    if re.search(r'\b(DEF|DEFAULT)\b', score):
        return 'default'

    sets = [(int(a), int(b)) for a, b in _SET_RE.findall(score)]
    if not sets:
        return 'invalid'
    if not all(_is_completed_set(a, b) for a, b in sets):
        return 'incomplete'

    p1_sets = sum(a > b for a, b in sets)
    p2_sets = sum(b > a for a, b in sets)
    category = (row.get('categorie') or '').strip().casefold()
    tour = (row.get('genre') or '').strip().casefold()
    best_of = 5 if tour == 'atp' and category in {'grand chelem', 'grand slam'} else 3
    sets_to_win = best_of // 2 + 1
    if max(p1_sets, p2_sets) < sets_to_win:
        return 'incomplete'
    winner_id = str(row.get('vainqueur_id') or '')
    p1_id, p2_id = str(row.get('joueur1_id') or ''), str(row.get('joueur2_id') or '')
    if not winner_id or winner_id not in {p1_id, p2_id}:
        return 'winner_id_unresolved'
    score_winner_id = p1_id if p1_sets > p2_sets else p2_id
    if winner_id != score_winner_id:
        return 'winner_disagreement'
    return 'completed'


def _is_completed_set(a, b):
    high, low = max(a, b), min(a, b)
    return (high >= 6 and high - low >= 2) or (high == 7 and low == 6)


def is_settled(row):
    return settlement_status(row) in {'completed', 'retirement', 'walkover', 'default'}
