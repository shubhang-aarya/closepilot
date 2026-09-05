# Contract: `report`

**Owns:** `attest/eval/report.py` · On the critical path for the D7 video.

## Why this exists

The submission is a public repo plus a five-minute video. The engine currently
speaks only in terminal tables, and a terminal table cannot show the thing that
actually distinguishes ATTEST: that a settlement is *proven*, and what the proof
consists of.

This is not a product UI. It is the engine's output artifact — a file the engine
emits, the way a compiler emits a listing.

## What to build

`render(report, findings, settlements, orders) -> str` producing a single
self-contained `report.html`. No external assets, no CDN, no framework, no build
step. Inline CSS. It must open from `file://` with the network off.

Three views:

1. **Summary** — settlements, rupees processed, and the verdict split
   PROVEN / AMBIGUOUS / CONTRADICTED. Not a percentage bar. Three counts.
2. **Proof panel** — for one PROVEN settlement, the arithmetic laid out so a
   human can check it by hand: each order's gross, the fee, the net, the sum,
   the adjustment, the residual, and the tolerance bound it had to clear.
   **A reader must be able to verify the claim without trusting the tool.**
3. **Exception panel** — for AMBIGUOUS, the competing explanations side by side
   with what distinguishes them. For CONTRADICTED, the `unsat_core` verbatim.

## Acceptance

- Legible in both light and dark; no horizontal page scroll at 1280px
- Renders from a real run at `seed=20260821`, `n=250` — not fixtures
- **AMBIGUOUS and CONTRADICTED must look like first-class outcomes, not errors.**
  No red, no warning triangles, no apologetic language. An engine declining to
  guess is behaving correctly, and the page must communicate that
- Read-only outside `eval/`

## Report

The path to the generated file, plus the three settlement IDs you would put on
screen in a demo: your clearest PROVEN, your most interesting AMBIGUOUS, and a
CONTRADICTED whose unsat core actually explains itself.
