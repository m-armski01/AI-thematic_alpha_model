"""Static PNG figures for the README/report (SPEC §1F), matplotlib with the Agg backend.

Conventions: one y-axis per panel (never a dual axis — the gate/VIX figure is two stacked
panels), fixed categorical colour order (strategy, S&P 500, equal-weight, naive momentum),
2px lines, hairline gridlines, a legend whenever there are two or more series, text in ink
tokens rather than series colours.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

# Validated categorical palette (light surface): blue, orange, aqua, yellow, magenta, green,
# violet, red. Slot order is the colour-vision-safety mechanism; never cycle past it.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
OTHER = "#898781"
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
LINE_W = 1.6  # ~2px at 100 dpi
DPI = 130


def _style(ax, ylabel: str | None = None) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
        ax.spines[side].set_linewidth(0.8)
    ax.grid(True, axis="y", color=GRID, linewidth=0.8)
    ax.grid(False, axis="x")
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    for lbl in ax.get_xticklabels() + ax.get_yticklabels():
        lbl.set_color(INK_2)
    if ylabel:
        ax.set_ylabel(ylabel, color=INK_2, fontsize=9)


def _fig(nrows: int = 1, height: float = 4.2):
    fig, axes = plt.subplots(nrows, 1, figsize=(9, height * nrows), sharex=nrows > 1)
    fig.patch.set_facecolor(SURFACE)
    return fig, axes


def _legend(ax) -> None:
    leg = ax.legend(frameon=False, fontsize=8, loc="upper left")
    for text in leg.get_texts():
        text.set_color(INK_2)


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=DPI, facecolor=SURFACE)
    plt.close(fig)
    return path


def _title(ax, text: str) -> None:
    ax.set_title(text, color=INK, fontsize=11, loc="left", pad=10)


def equity_curves(curves: dict[str, pd.Series], labels: dict[str, str], path: Path) -> Path:
    fig, ax = _fig()
    ends: list[tuple[float, str]] = []
    for i, (name, s) in enumerate(curves.items()):
        ax.plot(s.index, s / s.iloc[0], color=SERIES[i], linewidth=LINE_W, label=labels[name])
        ends.append((float(s.iloc[-1] / s.iloc[0]), f"x{s.iloc[-1] / s.iloc[0]:.1f}"))
    # End labels: keep a minimum gap in log space so converging series don't overprint;
    # a nudged label gets a short leader line back to its curve end.
    last_x = next(iter(curves.values())).index[-1]
    placed: list[float] = []
    for value, text in sorted(ends):
        y = value
        if placed and y / placed[-1] < 1.18:
            y = placed[-1] * 1.18
        placed.append(y)
        style = {"fontsize": 8, "color": INK_2, "va": "center", "annotation_clip": False}
        if y == value:
            ax.annotate(text, (last_x, value), xytext=(6, 0), textcoords="offset points", **style)
        else:
            ax.annotate(
                text,
                (last_x, value),
                xytext=(last_x, y),
                textcoords="data",
                ha="left",
                arrowprops={"arrowstyle": "-", "color": AXIS, "linewidth": 0.8},
                **style,
            )
    ax.set_yscale("log")
    _style(ax, "Growth of 1 (log scale)")
    _title(ax, "Equity curves, net of costs")
    _legend(ax)
    return _save(fig, path)


def underwater(uw: pd.Series, path: Path) -> Path:
    fig, ax = _fig(height=3.2)
    ax.fill_between(uw.index, uw, 0, color=SERIES[0], alpha=0.10, linewidth=0)
    ax.plot(uw.index, uw, color=SERIES[0], linewidth=LINE_W)
    ax.axhline(0, color=AXIS, linewidth=0.8)
    trough = uw.idxmin()
    ax.annotate(
        f"{100 * uw.min():.0f}%",
        (trough, uw.min()),
        xytext=(6, -2),
        textcoords="offset points",
        fontsize=8,
        color=INK_2,
    )
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    _style(ax, "Drawdown from running peak")
    _title(ax, "Strategy underwater plot")
    return _save(fig, path)


def rolling_line(
    series: pd.Series, title: str, ylabel: str, path: Path, reference: float | None = None
) -> Path:
    fig, ax = _fig(height=3.2)
    ax.plot(series.index, series, color=SERIES[0], linewidth=LINE_W)
    if reference is not None:
        ax.axhline(reference, color=AXIS, linewidth=0.8)
    _style(ax, ylabel)
    _title(ax, title)
    return _save(fig, path)


def weights_area(
    weights: pd.DataFrame, path: Path, max_named: int = 8, sample: str | None = "ME"
) -> Path:
    """Stacked allocation over time, sampled at ``sample`` period ends (month-ends by default)
    so a weekly rotation stays readable. Names beyond ``max_named`` (by average weight) fold
    into 'Other' in gray so no series is ever given a generated hue."""
    snap = weights.resample(sample).last().dropna(how="all") if sample else weights
    order = snap.mean().sort_values(ascending=False).index.tolist()
    named, rest = order[:max_named], order[max_named:]
    frame = snap[named].copy()
    if rest:
        frame["Other"] = snap[rest].sum(axis=1)
    colors = SERIES[: len(named)] + ([OTHER] if rest else [])
    fig, ax = _fig()
    ax.stackplot(
        frame.index,
        frame.T.to_numpy(),
        labels=frame.columns,
        colors=colors,
        linewidth=0.6,
        edgecolor=SURFACE,
        alpha=0.9,
        step="post",
    )
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    _style(ax, "Share of equity (remainder is cash)")
    _title(ax, "Strategy allocation, month-end snapshots" if sample else "Strategy allocation")
    leg = ax.legend(
        frameon=False,
        fontsize=8,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.08),
        ncol=min(len(frame.columns), 5),
    )
    for text in leg.get_texts():
        text.set_color(INK_2)
    return _save(fig, path)


def gate_and_vix(
    exposure: pd.Series,
    vix: pd.Series,
    vix_threshold: float,
    path: Path,
    label: str = "Applied gate exposure",
) -> Path:
    """Two stacked panels sharing the x-axis (never a dual y-axis). ``exposure`` is the applied
    gate state: the multiplier in scale mode, 0/1 risk-off in block mode."""
    fig, (ax1, ax2) = _fig(nrows=2, height=2.6)
    ax1.step(exposure.index, exposure, where="post", color=SERIES[0], linewidth=LINE_W)
    ax1.fill_between(exposure.index, exposure, 0, step="post", color=SERIES[0], alpha=0.10)
    ax1.set_ylim(0, 1.05)
    _style(ax1, label)
    _title(ax1, "Applied macro-gate state (top) and VIX (bottom)")
    ax2.plot(vix.index, vix, color=SERIES[1], linewidth=LINE_W)
    ax2.axhline(vix_threshold, color=AXIS, linewidth=0.8)
    ax2.annotate(
        f"threshold {vix_threshold:g}",
        (vix.index[0], vix_threshold),
        xytext=(2, 3),
        textcoords="offset points",
        fontsize=8,
        color=INK_2,
    )
    _style(ax2, "VIX (1-day publication lag)")
    return _save(fig, path)


def turnover_by_cause(
    by_cause: dict[str, pd.Series], labels: dict[str, str], causes: list[str], path: Path
) -> Path:
    """One stacked bar per run: annualized turnover split by cause, total annotated on top."""
    fig, ax = _fig(height=4.0)
    names = list(by_cause)
    x = range(len(names))
    bottom = [0.0] * len(names)
    for k, cause in enumerate(causes):
        vals = [float(by_cause[n].get(cause, 0.0)) for n in names]
        ax.bar(x, vals, bottom=bottom, color=SERIES[k], width=0.6, label=cause, linewidth=0)
        bottom = [b + v for b, v in zip(bottom, vals, strict=True)]
    for i in range(len(names)):
        ax.annotate(
            f"{bottom[i]:.1f}x",
            (i, bottom[i]),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color=INK_2,
        )
    ax.set_xticks(list(x))
    ax.set_xticklabels([labels.get(n, n) for n in names], fontsize=8)
    ax.set_ylim(0, max(bottom) * 1.15 if max(bottom) > 0 else 1.0)
    _style(ax, "Annualized turnover (x equity per year)")
    _title(ax, "Turnover by cause, annualized")
    leg = ax.legend(frameon=False, fontsize=8, loc="upper right")
    for text in leg.get_texts():
        text.set_color(INK_2)
    return _save(fig, path)


def universe_composition(eligible: pd.DataFrame, path: Path) -> Path:
    """Eligibility strip per ticker (top) and the count of eligible names (bottom)."""
    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(9, 0.28 * len(eligible.columns) + 3.6),
        sharex=True,
        gridspec_kw={"height_ratios": [max(len(eligible.columns), 4), 4]},
    )
    fig.patch.set_facecolor(SURFACE)
    tickers = list(eligible.columns)
    idx = eligible.index
    for i, t in enumerate(tickers):
        col = eligible[t].to_numpy(dtype=bool)
        start = None
        for k, on in enumerate([*col, False]):
            if on and start is None:
                start = k
            elif not on and start is not None:
                x0 = idx[start]
                x1 = idx[min(k, len(idx) - 1)]
                ax1.barh(i, x1 - x0, left=x0, height=0.6, color=SERIES[0], linewidth=0)
                start = None
    ax1.set_yticks(range(len(tickers)))
    ax1.set_yticklabels(tickers, fontsize=8)
    ax1.invert_yaxis()
    ax1.set_ylim(len(tickers) - 0.5, -0.5)
    _style(ax1, "Eligible (in the cross-section)")
    ax1.grid(False, axis="y")
    _title(ax1, "Universe composition over time")
    count = eligible.sum(axis=1)
    ax2.step(idx, count, where="post", color=SERIES[0], linewidth=LINE_W)
    ax2.fill_between(idx, count, 0, step="post", color=SERIES[0], alpha=0.10)
    ax2.set_ylim(0, len(tickers) + 0.5)
    _style(ax2, "Eligible names")
    return _save(fig, path)
