"""paa-cal — standalone PAA / Risk Grid calculator over editable CSV inputs.

Mirrors the Deephaven scripts in ../deephaven-paa/ with plain-Python,
stdlib-only code so every number can be reproduced and debugged by hand.
"""

from .load import load_inputs
from .engine import compute_risk, compute_trades, compute_paa
from .rollup import aggregate, summary
from .grids import risk_grid, paa_grid

__all__ = ["load_inputs", "compute_risk", "compute_trades", "compute_paa",
           "aggregate", "summary", "risk_grid", "paa_grid"]
