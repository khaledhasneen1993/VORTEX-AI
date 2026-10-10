"""One original R: immutable initial entry-to-stop price distance.

Price thresholds use the original entry anchor; net reporting divides cumulative
realized net by original quantity * initial distance. Costs affect the numerator,
not R. Pyramids and tightened stops never redefine the original unit.
"""

from math import isfinite


def signal_r(signal):
    return abs(signal.entry - signal.stop)


def anchor_entry(position):
    return position.anchor_entry or position.entry


def price_r(position):
    # Compatibility for flat legacy metadata; current entries always store R.
    return position.initial_risk or abs(anchor_entry(position) - (position.initial_stop or position.stop))


def net_r(position, cumulative_net):
    denominator = position.initial_qty * position.initial_risk
    if not isfinite(denominator) or denominator <= 0:
        return None  # Do not invent original exposure for legacy reports.
    return round(cumulative_net / denominator, 6)
