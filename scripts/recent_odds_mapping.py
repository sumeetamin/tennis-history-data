"""Map provider prices explicitly into model player order."""
import math


def aligned_prices(raw, source_p1_is_model_p1):
    output = {}
    for model_side in (1, 2):
        source_side = model_side if source_p1_is_model_p1 else 3 - model_side
        for period, source_period in (('open', 'ouverture'), ('close', 'cloture')):
            try:
                value = float(raw.get(f'cote{source_side}_{source_period}') or '')
                if not math.isfinite(value) or value <= 1:
                    value = None
            except (TypeError, ValueError):
                value = None
            output[f'odds_{period}_p{model_side}_decimal'] = value
    return output
