# Contract: `adversary`

**Owns nothing.** Appends to `FAILURES.md`. Read-only everywhere else.

## Why this exists

Every other worker is trying to make the engine look good. You are not. The
generator is frozen, so the benchmark cannot be tuned — but its *parameters* were
still chosen by a human who wanted a workable number, and that is a bias worth
attacking.

## What to do

Within the frozen taxonomy, vary what the generator was never pinned on:
hazard mix weights, bundle-size distribution, collision density in
`AMBIGUOUS_SUBSET`, portfolio size, capture-date clustering, fee-method mix.

Find configurations where the engine degrades badly. Two findings are worth
more than the rest:

1. **Any configuration that raises `WRONG` above zero.** A false proof is the
   only truly unacceptable outcome, and the D3 run already produced one. Find
   more, and characterise what causes them.
2. **Any configuration where the engine is confidently wrong rather than
   ambiguous.** AMBIGUOUS is a correct answer under uncertainty. PROVEN-and-wrong
   is the failure mode this entire project exists to prevent.

## Rules

- **You may not edit `attest/generate/**` or anything under `attest/`.**
  Construct configurations in your own scratch file and call the generator.
- Do not tune anything to make the engine look better. That is the opposite job.

## Report

Append to `FAILURES.md` in the existing style: what you varied, what broke, the
numbers, and a one-line hypothesis about the cause. No fixes.
