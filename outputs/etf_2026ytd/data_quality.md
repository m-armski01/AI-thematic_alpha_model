# Data quality report

Coverage is measured against each ticker's **own** exchange calendar (`exchange_calendars`: XNYS for NASDAQ/NYSE, XKRX for KRX). Gaps are own-exchange sessions with no bar. Suspicious returns are flagged for manual review against corporate actions; nothing is auto-corrected.

## Price series

| ticker | exchange | first | last | rows | sessions | coverage | gaps | longest gap | flags (>25%) | adj close <= 0 |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| XLK | NYSE Arca | 1998-12-22 | 2026-09-11 | 6972 | 6972 | 100.0% | 0 | 0 | 0 | 0 |
| XLF | NYSE Arca | 1998-12-22 | 2026-09-11 | 6972 | 6972 | 100.0% | 0 | 0 | 0 | 0 |
| XLE | NYSE Arca | 1998-12-22 | 2026-09-11 | 6972 | 6972 | 100.0% | 0 | 0 | 0 | 0 |
| XLV | NYSE Arca | 1998-12-22 | 2026-09-11 | 6972 | 6972 | 100.0% | 0 | 0 | 0 | 0 |
| XLY | NYSE Arca | 1998-12-22 | 2026-09-11 | 6972 | 6972 | 100.0% | 0 | 0 | 0 | 0 |
| XLP | NYSE Arca | 1998-12-22 | 2026-09-11 | 6972 | 6972 | 100.0% | 0 | 0 | 0 | 0 |
| XLI | NYSE Arca | 1998-12-22 | 2026-09-11 | 6972 | 6972 | 100.0% | 0 | 0 | 0 | 0 |
| XLU | NYSE Arca | 1998-12-22 | 2026-09-11 | 6972 | 6972 | 100.0% | 0 | 0 | 0 | 0 |
| XLB | NYSE Arca | 1998-12-22 | 2026-09-11 | 6972 | 6972 | 100.0% | 0 | 0 | 0 | 0 |
| XLRE | NYSE Arca | 2015-10-08 | 2026-09-11 | 2747 | 2747 | 100.0% | 0 | 0 | 0 | 0 |
| XLC | NYSE Arca | 2018-06-19 | 2026-09-11 | 2069 | 2069 | 100.0% | 0 | 0 | 0 | 0 |
| SMH | NASDAQ | 2000-06-05 | 2026-09-11 | 6607 | 6607 | 100.0% | 0 | 0 | 0 | 0 |
| IGV | Cboe BZX | 2001-07-17 | 2026-09-11 | 6326 | 6326 | 100.0% | 0 | 0 | 0 | 0 |
| IBB | NASDAQ | 2001-02-12 | 2026-09-11 | 6433 | 6433 | 100.0% | 0 | 0 | 0 | 0 |
| ITA | Cboe BZX | 2006-05-05 | 2026-09-11 | 5120 | 5120 | 100.0% | 0 | 0 | 0 | 0 |
| TLT | NASDAQ | 2002-07-30 | 2026-09-11 | 6069 | 6069 | 100.0% | 0 | 0 | 0 | 0 |
| GLD | NYSE Arca | 2004-11-18 | 2026-09-11 | 5487 | 5487 | 100.0% | 0 | 0 | 0 | 0 |
| SPY | NYSE | 1998-01-02 | 2026-09-11 | 7217 | 7217 | 100.0% | 0 | 0 | 0 | 0 |

## Suspicious 1-day returns (|r| > 25%)

None.

## Macro series (FRED, raw observation dates)

| series | first | last | obs | NaN within span |
|---|---|---|---:|---:|
| DGS10 | 1962-01-02 | 2026-09-10 | 16158 | 7470 |
| DGS2 | 1976-06-01 | 2026-09-10 | 12566 | 5798 |
| T10Y2Y | 1976-06-01 | 2026-09-11 | 12567 | 5798 |
| VIXCLS | 1990-01-02 | 2026-09-10 | 9271 | 4130 |
| DCOILWTICO | 1986-01-02 | 2026-09-09 | 10241 | 4620 |
| T10YIE | 2003-01-02 | 2026-09-11 | 5928 | 2726 |
| DFF | 1954-07-01 | 2026-09-10 | 26370 | 0 |
| DTB3 | 1954-01-04 | 2026-09-10 | 18164 | 8334 |
| DTWEXBGS | 2006-01-02 | 2026-09-04 | 5184 | 2367 |
| DEXUSEU | 1999-01-04 | 2026-09-04 | 6941 | 3165 |
| DEXKOUS | 1981-04-13 | 2026-09-04 | 11348 | 5233 |
