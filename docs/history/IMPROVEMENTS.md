# IMPROVEMENTS.md — Thematic Alpha

**Purpose of this file.** A prioritised, self-contained work order for a coding agent to bring
this repository to a publishable state. Every item names the files to touch, the reason, and an
acceptance test. Do the P0 items first; they change conclusions. Do not start any item before
reading the **Guardrails** section.

---

## 0. North Star — what this project actually is

This is **not** an institutional alpha strategy and must stop presenting itself as one. It is a
single-investor research study answering one question:

> *Does an active, macro-aware trading overlay beat simply buying and holding my own 12-stock
> AI / datacenter basket?*

The twelve names in `data/reference/universe.csv` are the author's **actual holdings**, bought at
the start of 2026. They are a given, not a selection result. Therefore:

- The **only** benchmark that matters is **equal-weight buy-and-hold of the same basket.**
- The 17-ETF universe and the 2015–2026 window are **controls and robustness evidence**, not the
  headline — keep them, reframe them (see §1, §4).
- "Survivorship / hindsight selection" is no longer a defect to fix; it is a property to *state
  plainly* and move past. Do **not** attempt to rebuild a point-in-time equity universe.

The value of this project to a reader is **rigour and honesty**, not the P&L. Protect that.

---

## 1. Guardrails — do not touch, do not delete

**Do not modify (these are the credibility of the project):**
- `tests/test_no_lookahead.py` and the delete-the-future / spike / execution-lag invariants.
- `docs/preregistration_v2.md` — except to **append** dated deviation entries when a change here
  alters a pre-registered value (see §2.1). Never silently edit a committed parameter.
- `backtest/attribution.py` turnover-by-cause logic.
- The execution model in `backtest/engine.py` (t+1 open, `min_periods == window`, macro lag,
  ffill-only). It is correct; only the cash-accrual addition in §2.1 is permitted.

**Do not delete (these are your control and your out-of-sample evidence):**
- The ETF universe (`data/reference/universe_etf.csv`, `configs/etf*.yaml`).
- The full-window 2015–2026 study (`src/thematic_alpha/study.py`).
- The multi-exchange calendar / FX / KRX machinery — it is **load-bearing** (SK Hynix
  `000660.KS` is in the basket) and is a legitimate feature to advertise.

**Regression bar:** after every change, `pytest` must remain green (174 tests today). Any change
that alters numeric output must either (a) default to off and be byte-identical when off, or
(b) come with regenerated golden fixtures **and** a logged deviation entry.

---

## 2. Code changes

### 2.1 — [P0] Credit idle cash with the risk-free rate

**Files:** `src/thematic_alpha/backtest/engine.py`, `src/thematic_alpha/pipeline.py`,
`src/thematic_alpha/config.py`, `docs/preregistration_v2.md`.

**Problem.** Uninvested cash accrues 0% in the engine loop. The overlay deliberately moves to
cash when the gate blocks, so charging it 0% understates the overlay versus the true
alternative (T-bills). This is the single change most likely to affect the trade-vs-hold verdict.

**Change.**
- Add an optional daily cash-rate series parameter to `run_backtest(...)`, e.g.
  `cash_rate: pd.Series | None = None`. When `None`, behaviour is byte-identical to today.
- When supplied, accrue on the cash balance each session: `cash *= (1.0 + cash_rate[i])`
  (align `cash_rate` to `dates`; missing → 0.0). Apply once per day, consistently for the
  strategy **and** every benchmark so the comparison is fair.
- Plumb the existing `annualize_rf(bundle.macro[config.risk.rf_series])` (DTB3) through
  `run_backtests(...)`.
- Gate it behind a config flag, e.g. `backtest.cash_earns_rf: bool = false` (default off).
  Enable it in `configs/base.yaml` and `configs/base_2026ytd.yaml`.

**Acceptance.**
- With the flag off, `tests/test_golden.py` and all others pass unchanged.
- With the flag on, cash-heavy periods show higher terminal equity than before; add a unit test
  asserting a 100%-cash book compounds at the RF rate over a known window.
- Regenerate golden fixtures **only if** a fixture config enables the flag; if so, append a dated
  entry to `docs/preregistration_v2.md` Deviations: what changed, why, date.

### 2.2 — [P1] Add a regime / sub-period breakdown

**Files:** new `src/thematic_alpha/risk/regimes.py`; wire into `pipeline.py` risk stage and
`reporting/report.py`.

**Problem.** With 11 years of data the study reports only aggregate and rolling stats. The core
claim is a *macro-timing* thesis, so it must be tested by regime.

**Change.** Tag each session into regimes from data already loaded:
- VIX regime: calm (`vix_level < 20`), elevated (20–25), stress (`> 25`).
- Gate state: risk-off vs risk-on (from the applied gate).
- Optionally a rate-shock flag from the 21-day 10y change already computed.

For each bucket, report **strategy vs equal-weight B&H**: total/annualised return, vol, hit rate,
worst drawdown, and share of time. The headline the reader should be able to read off: *does the
overlay help specifically in the stress regimes it was designed for?*

**Acceptance.** New `report.md` section "Performance by regime"; unit test on the bucketing
(deterministic tags from a synthetic VIX path).

### 2.3 — [P1] Momentum-signal robustness (make the signal window configurable)

**Files:** `src/thematic_alpha/strategy/ranker.py`, `src/thematic_alpha/config.py`,
`src/thematic_alpha/study.py`.

**Problem.** The ranker hard-codes `SIGNAL = "mom_63"` (3-month, 5-day skip). An interviewer will
ask "why 63 days, why not 12–1?". The features `mom_126` and `mom_252` are already computed but
unused. Answer with evidence, not a default.

**Change.**
- Add `ranker.momentum_signal: str = "mom_63"` to config; have `rank()` / `rank_on_signal_dates()`
  read it instead of the module constant (validate it exists in the feature set).
- Add a sensitivity block to `study.py` `VARIANTS`: the chosen config run with
  `momentum_signal ∈ {mom_63, mom_126, mom_252}`, reported side by side (same pattern as the
  existing softmax τ sensitivity). Do **not** promote a winner — declare it as a sensitivity set.

**Acceptance.** New rows in `outputs/study.md`; default value keeps current results identical;
`pytest` green.

---

## 3. Cleanup — remove genuinely dead scaffolding

Rule applied: keep anything exercised by a test, the ablation, or a live run; cut flags with no
implementation and `NotImplementedError` branches. Removing these is the main "clean and
professional" win (~30–40 lines + two config sections).

### 3.1 — [P1] Remove the unimplemented `house_money` rule
**Files:** `src/thematic_alpha/strategy/sizing.py` (`announce_house_money`),
`src/thematic_alpha/config.py` (`SizingConfig.house_money`), all four YAMLs (`sizing.house_money`),
and the call site in `pipeline.py` (`announce_house_money(config.sizing)`).
**Why.** A config flag that only logs "not implemented" is the classic interview trap. Delete it
outright (do not implement — it is out of scope for a timing study).
**Acceptance.** No reference to `house_money` remains; `pytest` green (update/remove any test that
asserted the warning).

### 3.2 — [P1] Remove the aspirational `ml` block
**Files:** `src/thematic_alpha/config.py` (the `ml` model + `MlConfig`), the `ml:` section in all
YAMLs, and the `method == "ml"` branch in `ranker.py` that raises `NotImplementedError`.
**Why.** `ml.enabled: false` everywhere; it reads as an abandoned half-build. Keep the ambition as
a single line in the README under "Future work" if desired.
**Acceptance.** `ranker.method` Literal no longer offers `ml`; configs validate; `pytest` green.

### 3.3 — [P2] Keep but confirm these are referenced
Do **not** remove `conviction_tier` / `softmax` / `inverse_vol` weightings or the `scale` gate
mode — they are the "before" rows in the ablation and the softmax sensitivity set. Leave them.

---

## 4. Report — structure and content

**File:** `src/thematic_alpha/reporting/report.py` (and `study.py` report text).

1. **[P0] Reframe the top.** Title and lede must state: a personal research study testing an active
   macro overlay against buy-and-hold of the author's own basket. Add a short **Thesis** block
   (2–4 sentences) stating the actual macroeconomic hypothesis: what the gate is meant to protect
   against (VIX / rate / oil stress on a high-beta AI book) and the prediction being tested.
2. **[P0] Make equal-weight B&H of the same basket the sole headline benchmark.** Remove SPY from
   the headline tiles/first table; demote the `+177.6%` figure. SPY may remain in an appendix table
   as context only.
3. **[P0] Add a verdict block** near the top — one honest paragraph, e.g.: over 2015–2026 the
   overlay is roughly break-even to modestly value-additive versus holding on a risk-adjusted
   basis; in 2026 YTD it added return but through higher beta and a deeper drawdown; eight months
   is too short to conclude.
4. **[P1] Suppress sub-year annualised figures.** For any window shorter than ~24 months, do not
   print CAGR / Calmar / annualised alpha (or grey them with an inline "(N-month window — not
   annualisable)" tag). Show total return and drawdown instead. Consider a guard in
   `metrics.compute_metrics` or in the report renderer.
5. **[P1] Fix the alpha framing.** Where alpha-vs-SPY is shown, report it with its beta and, if
   feasible, a t-stat; state plainly that at β≈2.3 the excess return is dominated by market
   exposure, not selection.
6. **[P1] Demote the ETF run to an appendix / "Does this generalise?" control.** Keep every number;
   change the narrative so it reads as an out-of-basket robustness check, not a co-headline.
7. **[P1] Add "Limitations & next steps."** Name the biases yourself: personal single basket,
   optimistic flat slippage on the small-caps, short live window, no true walk-forward. Owning
   these is the point.

---

## 5. Report — voice & tone (authoritative / analytical)

The generated report currently mixes register (marketing-ish tiles beside careful prose). Enforce
one voice across `report.py` and `study.py` text.

**Voice spec:**
- Third person, present tense for findings ("The overlay reduces drawdown in stress regimes by…").
- Quantified, benchmark-relative claims only — every performance statement cites the B&H
  comparator and the window.
- State uncertainty explicitly (sample length, single basket) rather than hedging vaguely.
- No promotional language, no exclamation, no emoji, no "impressive/strong/amazing".
- Lead with the conclusion, then the evidence (BLUF — bottom line up front).
- Define a term once; use consistent labels ("overlay", "buy-and-hold", "basket").

**Before → after examples (apply this transformation throughout):**
- ✗ "The strategy delivered a spectacular +177.6% return."
  ✓ "Over 2026 YTD the overlay returned +177.6% versus +84.8% for equal-weight buy-and-hold of the
  same basket, with a deeper max drawdown (−32.2% vs −28.5%) and higher realised beta (2.27)."
- ✗ "Annualized CAGR of 338.6%."
  ✓ "Total return over the 8-month window was +177.6%; annualised figures are omitted as the window
  is under one year."

---

## 6. Config clarity — make the output self-describing

**Files:** `configs/*.yaml`, `src/thematic_alpha/config.py`, `reporting/report.py`.

1. **[P1] Relabel the universe selection.** Replace `universe.selection: hindsight` with an honest,
   descriptive value for the basket run, e.g. `owned_portfolio`, and drive the report's framing
   paragraph off it (the personal trade-vs-hold statement, not a hindsight-bias disclaimer). Keep
   `point_in_time` framing for the ETF control.
2. **[P1] Add a `report:` config block** so every generated report is explicitly and consistently
   labelled. Suggested fields (documentation-as-config): `report.title`, `report.subtitle`,
   `report.author`, `report.thesis` (short string), `report.disclaimer`. `report.py` reads these
   into the header/lede instead of hard-coded strings. The *tone* stays enforced in code per §5;
   these fields keep identity and framing consistent across runs.
3. **[P2] Comment the intent** at the top of each YAML in one line: which run is the headline
   (basket), which is the control (ETF), and that annualised metrics are suppressed under 24 months.

---

## 7. Suggested order of execution

1. §2.1 cash-at-RF (P0, changes conclusions) → rerun, note any deviation.
2. §4.1–4.3 + §5 report reframing, verdict, voice (P0, the publishable face).
3. §3 cleanup (P1, quick, professionalises the tree).
4. §2.2 regime + §2.3 signal robustness (P1, strengthens the thesis test).
5. §4.4–4.7, §6 polish (P1/P2).

## 8. Definition of done
- `pytest` green; golden fixtures either unchanged or regenerated + deviation logged.
- No `house_money` / `ml` references remain.
- Report leads with thesis + verdict, benchmarks against basket B&H, suppresses sub-year
  annualisation, and reads in one consistent analytical voice.
- ETF run and 2015–2026 study retained and reframed as controls.
- README states, in one paragraph, what the project is and is not.
