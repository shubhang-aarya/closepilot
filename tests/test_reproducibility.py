"""The canonical demo must exist on the install a judge actually performs.

Phase 28 P0. A submission whose central case does not reproduce from the
documented setup is worse than one with a smaller claim, and this repository
had exactly that defect.

`attest/subsetsum.py` sets the solver envelope from whether the optional Rust
extension imported:

    MAX_TARGET_PAISE = 20_000_000 if _native_reachable is not None else 3_000_000

The extension needs a Rust toolchain and `maturin develop --release`, which the
README correctly lists as *optional*. So on `pip install -e .` the envelope is
₹30,000, and every settlement above it comes back INSUFFICIENT — the solver
refusing to attempt what the portable reference cannot decide, which is right,
and fatal for a demo built on a ₹1,00,036.83 settlement.

These tests pin the canonical case to one that is decided identically under
BOTH envelopes, and pin the disposition of the whole portfolio under each, so
that the figures quoted in the video can be checked against the environment
they were recorded in.

They do not weaken the engine. The envelope is a resource guard, not a
correctness boundary: the DP is exact under either cap, and raising the numpy
cap to match Rust reproduces the Rust verdicts exactly — at 46.6s against 18.2s
for 250 settlements, measured, which is why the cap stays.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from attest.generate.generator import build           # noqa: E402
from attest.pipeline import run                       # noqa: E402

SEED, N = 20260821, 250

#: Decided identically whether or not the native kernel is installed, because
#: its credit sits below the portable envelope. This is the demo case.
CANONICAL = "setl_000225"

#: Above the portable envelope. Kept as a test subject precisely because it is
#: the case that used to be canonical and could not be reproduced.
OVER_ENVELOPE = "setl_000089"

NUMPY_CAP = 3_000_000
NATIVE_CAP = 20_000_000


def _findings(cap: int):
    """Run the real pipeline with the envelope forced to `cap`.

    Forcing the cap reproduces the *envelope* behaviour, which is what decides
    INSUFFICIENT. It does not remove the native kernel if one is installed, so
    it does not by itself prove the two implementations agree on the counts —
    `native/tests/differential.py` does that, over 1,777 instances.

    The no-kernel case was also verified directly: a clean `git ls-files | tar`
    extraction with `pip install -e .` and no Rust toolchain returns
    AMBIGUOUS with 4 explanations for the canonical settlement, and the
    portable disposition below.
    """
    import attest.subsetsum as ss

    was = ss.MAX_TARGET_PAISE
    ss.MAX_TARGET_PAISE = cap
    try:
        ds = build(N, seed=SEED)
        _, _, findings = run(ds.settlements, ds.orders)
        return {f.settlement_id: f for f in findings}, ds
    finally:
        ss.MAX_TARGET_PAISE = was


@pytest.fixture(scope="module")
def portable():
    return _findings(NUMPY_CAP)


@pytest.fixture(scope="module")
def native():
    return _findings(NATIVE_CAP)


def test_the_canonical_case_is_identical_on_both_execution_paths(portable, native):
    """The one a judge will watch. Same verdict, same number of explanations,
    same credit — whether or not they have a Rust toolchain."""
    p, n = portable[0][CANONICAL], native[0][CANONICAL]
    assert p.verdict.value == n.verdict.value == "AMBIGUOUS", (
        f"portable={p.verdict.value} native={n.verdict.value}")
    assert len(p.proofs) == len(n.proofs) == 4, (
        f"portable={len(p.proofs)} explanations, native={len(n.proofs)}")


def test_the_canonical_case_sits_inside_the_portable_envelope(portable):
    """Why it reproduces: its credit is below the cap the reference can carry.
    If the generator ever moves it above, this fails before a video is made."""
    _, ds = portable
    credit = next(s.net_paise for s in ds.settlements
                  if s.settlement_id == CANONICAL)
    assert credit < NUMPY_CAP, (
        f"{CANONICAL} is {credit} paise, above the portable envelope "
        f"{NUMPY_CAP} — it would come back INSUFFICIENT on a default install")


def test_the_case_that_could_not_reproduce_still_cannot(portable, native):
    """The defect, pinned. This is not a regression to fix by widening the cap —
    it is the reason the canonical case moved, and it should stay visible."""
    assert portable[0][OVER_ENVELOPE].verdict.value == "INSUFFICIENT"
    assert native[0][OVER_ENVELOPE].verdict.value == "AMBIGUOUS"


def test_every_settlement_is_accounted_for_on_both_paths(portable, native):
    """The track bar asks for an honest exception list. On either path, every
    settlement has a disposition and none is silently dropped."""
    for label, (found, ds) in (("portable", portable), ("native", native)):
        assert len(found) == N, f"{label}: {len(found)} findings for {N} settlements"
        assert all(f.verdict is not None for f in found.values()), label


def test_the_portable_disposition_is_what_the_video_will_claim(portable):
    """The figures a judge will see on their own machine, pinned so the video
    and the repository cannot drift apart."""
    found, _ = portable
    c = Counter(f.verdict.value for f in found.values())
    assert dict(c) == {"PROVEN": 51, "AMBIGUOUS": 161,
                       "CONTRADICTED": 1, "INSUFFICIENT": 37}, dict(c)


def test_the_native_disposition_is_what_the_optional_kernel_adds(native):
    """Installing the kernel moves the 37 out-of-envelope settlements into the
    same ambiguity as the rest — it decides more, it does not decide
    differently."""
    found, _ = native
    c = Counter(f.verdict.value for f in found.values())
    assert dict(c) == {"PROVEN": 52, "AMBIGUOUS": 197, "CONTRADICTED": 1}, dict(c)
