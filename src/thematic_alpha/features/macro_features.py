"""Macro features (SPEC §1B), computed from the lagged, master-calendar FRED frame.

Level changes are in the series' own units (DGS10 in percentage points, VIX in points); WTI and
the dollar index use percentage changes. Windows for the yield and oil changes come from the
macro-gate config so the gate and the features always agree.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

VIX_CHANGE_WINDOW = 21
VIX_PERCENTILE_WINDOW = 252
DXY_CHANGE_WINDOW = 21
# WTI printed -$37 on 2020-04-20. A percentage change through a non-positive base is meaningless,
# so the *denominator* is floored here. The numerator is untouched: a crash still reads as a crash.
WTI_PRICE_FLOOR = 1.0


@dataclass(frozen=True)
class MacroFeatureSpec:
    yield_change_window: int
    oil_change_window: int


def compute_macro_features(macro: pd.DataFrame, spec: MacroFeatureSpec) -> pd.DataFrame:
    out = pd.DataFrame(index=macro.index)
    out["dgs10_level"] = macro["DGS10"]
    out[f"dgs10_chg_{spec.yield_change_window}d"] = macro["DGS10"] - macro["DGS10"].shift(
        spec.yield_change_window
    )
    out["t10y2y_level"] = macro["T10Y2Y"]
    out["vix_level"] = macro["VIXCLS"]
    out[f"vix_chg_{VIX_CHANGE_WINDOW}d"] = macro["VIXCLS"] - macro["VIXCLS"].shift(
        VIX_CHANGE_WINDOW
    )
    out[f"vix_percentile_{VIX_PERCENTILE_WINDOW}d"] = (
        macro["VIXCLS"]
        .rolling(VIX_PERCENTILE_WINDOW, min_periods=VIX_PERCENTILE_WINDOW)
        .rank(pct=True)
    )
    wti = macro["DCOILWTICO"]
    out[f"wti_chg_{spec.oil_change_window}d"] = (
        wti / wti.shift(spec.oil_change_window).clip(lower=WTI_PRICE_FLOOR) - 1
    )
    out["t10yie_level"] = macro["T10YIE"]
    out[f"dxy_chg_{DXY_CHANGE_WINDOW}d"] = macro["DTWEXBGS"].pct_change(
        DXY_CHANGE_WINDOW, fill_method=None
    )
    return out
