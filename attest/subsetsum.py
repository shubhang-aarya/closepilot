"""L3 -- which orders compose this credit.

Meet-in-the-middle was the plan and it does not survive contact with the data.
Measured candidate pools run to a median of 899 orders, so splitting in half and
enumerating gives 2^449 partial sums per side. The technique is only viable
below roughly n=45, which describes none of this portfolio.

What works instead is a counting dynamic program over the amount axis.
Amounts are integers -- paise, never floats -- so reachable sums form a dense
array indexed by value, and each order is one shifted add over it:

    reach[s] += reach[s - net]        for every order, descending in s

Complexity is O(n * target) rather than O(2^(n/2)): linear in the pool instead of
exponential. For n=899 and a 47,382 rupee credit that is roughly 4.3e9 cell
updates -- far beyond Python, comfortably inside a few hundred milliseconds of
Rust over a packed array. The port on D6 is therefore not a flourish; it is the
difference between the algorithm running and not running.

The counter is the interesting part. Counts saturate at two:

    0 -> CONTRADICTED   no subset of the pool explains this credit
    1 -> PROVEN         exactly one does
    2 -> AMBIGUOUS      at least two do; a human sees both, the engine posts neither

Two bits per reachable sum is all that is needed to decide the verdict, because
the question is never "how many explanations" but "is the explanation unique".
That makes the three states a computed property of the constraint system rather
than a threshold on a score.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:
    # Byte-identical to `_reachable`, verified over 1,777 instances and 1.3e11 DP
    # cells across all fifteen hazard families. Two bitplanes instead of a byte
    # array: the DP is three ALU ops per cell and bandwidth-bound, so the only
    # optimisation that matters is making the array smaller.
    from attest_native import reachable as _native_reachable
except ImportError:  # pragma: no cover - the pure-Python path stays correct
    _native_reachable = None

from attest.model import Order, tolerance_paise
from attest.verdict import Verdict

#: Beyond this the numpy reference exhausts memory bandwidth long before it
#: exhausts patience. Rust removes the ceiling; until then instances above it are
#: reported as out-of-envelope rather than silently mis-answered.
#: The Python reference is bandwidth-bound -- it copies an array the width of the
#: credit once per order -- so it could only afford Rs 30,000. That cap silently
#: skipped 14.8% of the portfolio, including *every* large bundle, before a single
#: subset was examined. The packed kernel holds two bits per sum instead of eight,
#: which is what makes the wider envelope affordable. Without the extension the
#: cap falls back to what numpy can actually carry.
MAX_TARGET_PAISE = 20_000_000 if _native_reachable is not None else 3_000_000
MAX_POOL = 900

#: Distinct explanations enumerated before declaring ambiguity. Two is enough to
#: prove non-uniqueness; more are collected only to show a human the field.
MAX_ENUM = 4


@dataclass(frozen=True)
class Solution:
    order_ids: tuple[str, ...]
    net_paise: int


class OutOfEnvelope(Exception):
    """Instance exceeds what the Python reference can decide.

    Raised rather than approximated. An engine that quietly degrades to a guess
    at scale is worse than one that says it cannot answer.
    """


def _reachable(nets: list[int], target: int) -> np.ndarray:
    """Saturating count of subsets reaching each sum in [0, target].

    Descending update order is what makes this 0/1 knapsack rather than
    unbounded -- each order may be spent once. numpy needs the explicit copy
    because the source and destination slices overlap.
    """
    counts = np.zeros(target + 1, dtype=np.uint8)
    counts[0] = 1
    for net in nets:
        if net == 0 or net > target:
            continue
        prev = counts.copy()
        head = counts[net:].astype(np.uint16) + prev[: target + 1 - net]
        counts[net:] = np.minimum(head, 2).astype(np.uint8)
    return counts


def _enumerate(nets: list[tuple[str, int]], target: int, tol: int,
               limit: int, reach: np.ndarray | None = None) -> list[Solution]:
    """Depth-first recovery of up to `limit` explanations.

    Sorted descending so large orders are decided first and the bound bites
    early; the suffix-sum test prunes any branch whose remaining orders cannot
    reach the residual.

    `reach` is the counting DP's output, and it is what makes large bundles
    tractable. Blind depth-first search over 185 candidates looking for a
    27-element subset wanders essentially forever: the suffix-sum bound only
    rejects a branch once the remainder has become arithmetically impossible,
    which is far too late. The DP already knows which sums are reachable *at
    all*, so a branch whose residual is unreachable can be cut immediately
    rather than explored to exhaustion.

    The test is an over-approximation -- `reach` was computed over every order,
    including ones this branch has already spent -- so it can only ever fail to
    prune. It never prunes a live branch, which is the direction that matters:
    the search stays complete, it just stops visiting the impossible.
    """
    items = sorted(nets, key=lambda kv: -kv[1])
    suffix = [0] * (len(items) + 1)
    for i in range(len(items) - 1, -1, -1):
        suffix[i] = suffix[i + 1] + items[i][1]

    out: list[Solution] = []
    chosen: list[str] = []

    def unreachable(r: int) -> bool:
        if reach is None or r < 0:
            return False
        lo, hi = max(0, r - tol), min(len(reach) - 1, r + tol)
        return lo > hi or not reach[lo : hi + 1].any()

    def walk(i: int, remaining: int) -> None:
        if len(out) >= limit:
            return
        if abs(remaining) <= tolerance_paise(max(len(chosen), 1)) and chosen:
            out.append(Solution(tuple(chosen), target - remaining))
            return
        if i >= len(items) or remaining < -tol or suffix[i] < remaining - tol:
            return
        if unreachable(remaining):
            return
        oid, net = items[i]
        chosen.append(oid)
        walk(i + 1, remaining - net)
        chosen.pop()
        walk(i + 1, remaining)

    walk(0, target)
    return out


def solve(pool: list[Order], target: int) -> tuple[Verdict, list[Solution], bool]:
    """Decide how many subsets of `pool` explain `target`, and produce them.

    The third value reports whether the enumeration was **exhaustive** -- that
    every explanation was found rather than the first `MAX_ENUM`. Downstream
    deduction depends on it: a claim about *every* explanation is unsound if the
    enumerator stopped early, and saying so is cheaper than the alternative.
    """
    if target > MAX_TARGET_PAISE or len(pool) > MAX_POOL:
        raise OutOfEnvelope(f"target={target} pool={len(pool)}")

    usable = [(o.order_id, o.net) for o in pool if 0 < o.net <= target]
    if not usable:
        return Verdict.CONTRADICTED, [], True

    nets = [n for _, n in usable]
    counts = (_native_reachable(nets, target) if _native_reachable is not None
              else _reachable(nets, target))

    # Tolerance depends on subset size, which is unknown before a subset exists.
    # The band is opened to the largest plausible bundle, then every candidate is
    # re-checked against its own exact bound by the trusted kernel.
    band = tolerance_paise(min(len(usable), 64))
    lo, hi = max(0, target - band), min(target, target + band)
    total = int(counts[lo : hi + 1].sum())

    if total == 0:
        return Verdict.CONTRADICTED, [], True

    # Ask for one more than needed: coming back short proves the search ran out
    # of explanations rather than out of budget.
    found = _enumerate(usable, target, band, MAX_ENUM + 1, counts)
    exhaustive = len(found) <= MAX_ENUM
    found = found[:MAX_ENUM]

    if not found:
        return Verdict.CONTRADICTED, [], True
    if len(found) == 1:
        return Verdict.PROVEN, found, exhaustive
    return Verdict.AMBIGUOUS, found, exhaustive


def solve_with_context(pool: list[Order], target: int):
    """`solve`, plus a reading of how cheap the match was.

    The reachability array is thrown away by `solve`; here it is used once more
    to measure the neighbourhood the answer came from. See attest/coincidence.py
    for why that matters — it is the only upstream signal that distinguishes a
    hard-won match from one the pool was always going to produce.
    """
    from attest.coincidence import assess

    verdict, sols, exhaustive = solve(pool, target)
    usable = [o.net for o in pool if 0 < o.net <= target]
    counts = ((_native_reachable(usable, target) if _native_reachable is not None
               else _reachable(usable, target)) if usable else np.zeros(1, np.uint8))
    return verdict, sols, exhaustive, assess(counts, target)
