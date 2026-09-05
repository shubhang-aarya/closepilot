"""Coincidence risk — how cheap was this match? §12, and the answer to D10.

D10 found that false proofs come from two sources, and that the second cannot be
fixed by searching harder:

    search-space error   the truth was pruned before solving
    model gap            the truth is not expressible at all

A `split_order` pays out half an order elsewhere, so the credit does not equal
the sum of its true orders and no exact solver can reach them. What happens
instead is that some *other* subset lands within tolerance, uniquely, and it
arrives wearing every mark of a proof. The arithmetic is perfect. The kernel
accepts it. It is wrong.

Nothing downstream can catch that — but something upstream can measure how
surprising the match was.

**The signal is already computed.** The counting DP produces, for free, which
sums are reachable from the candidate pool. So we can ask how densely populated
the neighbourhood of the target is:

    a credit sitting in a region where almost every value is reachable
    was cheap to hit, and a unique hit there is weak evidence

    a credit in a sparse region was expensive to hit, and a unique hit
    there is strong evidence

This is a property of the pool and the target, computable *before* anyone looks
at whether the answer is right, and it costs one pass over an array the solver
already built.

It is not a probability and it is not calibrated into one. It is a feature the
policy stratifies on, so that "unique" over a dense neighbourhood is priced
differently from "unique" over a sparse one — which is exactly what the D10
failures deserve and what a single precision figure cannot express.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class Cheapness(str, Enum):
    """How easy it was to hit this credit at all."""

    SPARSE = "sparse"
    """Few nearby values reachable. A unique hit here is strong evidence."""

    MODERATE = "moderate"
    DENSE = "dense"
    """Most nearby values reachable. A unique hit here is nearly free, and
    uniqueness says more about the enumerator's cap than about the portfolio."""


#: Half-width of the neighbourhood, in paise. Wide enough that the answer is
#: about the region rather than about the exact target, narrow enough that it is
#: still local: 100 rupees either side.
WINDOW_PAISE = 10_000


@dataclass(frozen=True)
class Coincidence:
    density: float
    """Share of sums within the window that some subset can reach."""

    reachable: int
    window: int
    unique_share: float
    """Share of reachable sums in the window reachable exactly ONE way. A
    neighbourhood where most sums are uniquely reachable makes a unique hit
    unremarkable rather than special."""

    @property
    def cheapness(self) -> Cheapness:
        if self.density < 0.02:
            return Cheapness.SPARSE
        if self.density < 0.25:
            return Cheapness.MODERATE
        return Cheapness.DENSE

    @property
    def note(self) -> str:
        return {
            Cheapness.SPARSE:
                f"only {self.density:.2%} of nearby values are reachable at all, "
                f"so landing on this credit was hard and doing it once is "
                f"meaningful evidence",
            Cheapness.MODERATE:
                f"{self.density:.1%} of nearby values are reachable; a unique hit "
                f"here carries some weight but not much",
            Cheapness.DENSE:
                f"{self.density:.1%} of nearby values are reachable, so hitting "
                f"this credit exactly was close to free and uniqueness is weak "
                f"evidence about the portfolio",
        }[self.cheapness]

    def to_json(self) -> dict[str, object]:
        return {"density": round(self.density, 5),
                "reachable": self.reachable, "window": self.window,
                "unique_share": round(self.unique_share, 4),
                "cheapness": self.cheapness.value, "note": self.note}


def assess(counts: np.ndarray, target: int,
           window: int = WINDOW_PAISE) -> Coincidence:
    """Measure the neighbourhood the answer was found in.

    `counts` is the saturating reachability array the DP already produced — 0,
    1 or 2+ ways to reach each sum. Nothing is re-solved.
    """
    lo = max(0, target - window)
    hi = min(len(counts) - 1, target + window)
    if hi <= lo:
        return Coincidence(0.0, 0, 0, 0.0)

    band = counts[lo : hi + 1]
    total = int(band.size)
    reachable = int(np.count_nonzero(band))
    once = int(np.count_nonzero(band == 1))
    return Coincidence(
        density=reachable / total,
        reachable=reachable,
        window=total,
        unique_share=(once / reachable) if reachable else 0.0,
    )
