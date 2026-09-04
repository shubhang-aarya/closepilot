"""The hazard taxonomy.

Every family below is a distinct reason a real reconciliation fails. They are
enumerated here, in one place, because the engine's accuracy is only meaningful
relative to the hazards it was tested against -- a matcher that scores 99% on
clean one-to-one data has demonstrated nothing.

The generator injects these deliberately and labels every ground-truth row with
the family that produced it, so evaluation reports failure *by cause* instead of
by percentage. "We match 94%" is a number. "We match 94%, and the misses are
concentrated in AMBIGUOUS_SUBSET and ORPHAN_SETTLEMENT, for these reasons" is an
engineering claim.

This file is frozen after D1. Tuning the hazards to suit the matcher would make
every downstream number a measurement of nothing.
"""

from __future__ import annotations

from enum import Enum


class Case(str, Enum):
    """A failure mode of settlement reconciliation."""

    CLEAN = "clean"
    """One settlement, a handful of orders, every reference present. The base
    rate. Should be solved entirely by the deterministic layer."""

    MISSING_REF = "missing_ref"
    """Gateway payment_id absent or malformed on the merchant's side. Drops the
    row out of the hash join and into amount-based matching."""

    BUNDLE_LARGE = "bundle_large"
    """One settlement covering 20-40 orders. The core hard case: the number of
    candidate subsets is exponential in the bundle size, so this is where naive
    matchers stop and where meet-in-the-middle earns its place."""

    SPLIT_ORDER = "split_order"
    """A single order's proceeds arrive across two settlements. Breaks the
    assumption that the mapping is many-to-one, which is what forces the
    N-to-M set-partitioning formulation."""

    REFUND_OFFSET = "refund_offset"
    """A refund is netted off inside the settlement, so the credit is *smaller*
    than the sum of its orders. Any matcher that only searches upward misses
    every one of these."""

    CHARGEBACK_REVERSAL = "chargeback_reversal"
    """A chargeback in this period reverses an order captured two periods ago.
    The offsetting order is outside the date-blocking window, so aggressive
    pruning silently destroys these matches."""

    DUPLICATE_AMOUNT = "duplicate_amount"
    """Two or more orders with identical net, same day, same method. Arithmetic
    cannot distinguish them; only a reference or a name can."""

    TIMING_GAP = "timing_gap"
    """T+2 nominal, but weekends and bank holidays stretch it to T+4. A fixed
    date window is wrong; the window has to follow the settlement calendar."""

    MONTH_BOUNDARY = "month_boundary"
    """A settlement spanning a month end. Included because month-end is exactly
    when finance teams run reconciliation, and because it interacts badly with
    any code that blocks on (year, month)."""

    ORPHAN_ORDER = "orphan_order"
    """A captured order that never settles inside the observation window --
    still pending, or held. Correct behaviour is to leave it unmatched, so this
    family measures whether the engine invents matches under pressure."""

    ORPHAN_SETTLEMENT = "orphan_settlement"
    """A settlement containing an order absent from the merchant's export.
    Unsolvable by construction. Present to verify the engine says so rather
    than forcing a plausible wrong answer."""

    NARRATION_GARBLE = "narration_garble"
    """Bank narration truncated mid-UTR, case-folded, delimiters mangled. The
    only family where an LLM has a real edge over a regex."""

    NAME_VARIANT = "name_variant"
    """Counterparty spelled differently across sources: initials, honorifics,
    transliteration drift. Semantic, not arithmetic."""

    MIXED_METHOD = "mixed_method"
    """One bundle mixing UPI (zero MDR) with cards and wallets. Defeats any
    matcher that assumes a single blended fee rate, because two bundles of
    identical gross settle for different nets."""

    AMBIGUOUS_SUBSET = "ambiguous_subset"
    """Two disjoint subsets of the candidate pool whose nets sum to the same
    value within tolerance. Exactly one is correct, and arithmetic alone cannot
    say which.

    This family is the reason the engine must emit a posterior over
    explanations rather than a boolean. A matcher that returns a single answer
    here is not more accurate than one that returns two ranked answers -- it is
    the same accuracy, dishonestly reported. Any auto-post threshold that fires
    on these is a bug that would move real money.
    """


#: Share of settlements drawn from each family. Not uniform: real portfolios are
#: dominated by easy cases, and a benchmark that over-weights the hard ones
#: flatters the engine as surely as one that ignores them.
DEFAULT_MIX: dict[Case, float] = {
    Case.CLEAN: 0.30,
    Case.MISSING_REF: 0.09,
    Case.BUNDLE_LARGE: 0.14,
    Case.SPLIT_ORDER: 0.05,
    Case.REFUND_OFFSET: 0.08,
    Case.CHARGEBACK_REVERSAL: 0.03,
    Case.DUPLICATE_AMOUNT: 0.05,
    Case.TIMING_GAP: 0.06,
    Case.MONTH_BOUNDARY: 0.03,
    Case.ORPHAN_ORDER: 0.04,
    Case.ORPHAN_SETTLEMENT: 0.02,
    Case.NARRATION_GARBLE: 0.04,
    Case.NAME_VARIANT: 0.03,
    Case.MIXED_METHOD: 0.02,
    Case.AMBIGUOUS_SUBSET: 0.02,
}

assert abs(sum(DEFAULT_MIX.values()) - 1.0) < 1e-9, "hazard mix must sum to 1"
