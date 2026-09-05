"""The two execution paths, and what must and must not differ between them.

The recorded demo runs on the native kernel. A clean checkout without a Rust
toolchain runs the portable solver, whose envelope is ₹30,000 instead of
₹2,00,000 — so 37 settlements of this run exceed it and come back INSUFFICIENT.

That divergence is intended. What is NOT acceptable is a submission that shows
native figures while a judge's own run produces portable ones with nothing
saying so. These pin the difference: what the canonical case guarantees across
both paths, and what the operator is told before any figure is printed.

Discovered in the Phase 36 clean-checkout rehearsal, where the portfolio split
came back 51/161/1/37 against a script that says 52/197/1.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _envelope() -> tuple[bool, int]:
    from attest import subsetsum
    return subsetsum._native_reachable is not None, subsetsum.MAX_TARGET_PAISE


def test_the_envelope_is_the_only_thing_that_differs():
    """Both paths run the same solver against the same data; the cap is the
    single variable. If a second one ever appears, the divergence stops being
    explainable by one sentence in the README."""
    native, cap = _envelope()
    assert cap in (3_000_000, 20_000_000), f"unexpected envelope {cap}"
    assert (cap == 20_000_000) is native, \
        "the envelope does not follow the native kernel's availability"


def test_the_canonical_case_is_below_the_portable_envelope():
    """Every figure the video shows for `setl_000225` has to survive a judge
    running it without the Rust toolchain. The case was chosen for this; the
    check keeps it true.

    Its credit is ₹27,208.12 — an order of magnitude under even the portable
    ₹30,000 cap — so the solver attempts it on both paths and reaches the same
    2,368 -> 164 -> 4."""
    from attest.api import detail, execute

    r = execute(250, 20260821)
    d = detail(r, "setl_000225")
    assert d, "the canonical case is missing from the run"

    amount = d["amount"]
    assert amount < 3_000_000, (
        f"the canonical case is ₹{amount / 100:,.2f}, above the portable "
        f"envelope of ₹30,000 — a judge without the native kernel would see "
        f"a different case than the recording")
    assert d["verdict"] == "AMBIGUOUS", d["verdict"]
    assert d["space"]["universe"] == 2368
    assert d["space"]["candidates"] == 164
    assert len(d["proofs"]) == 4


def test_run_demo_names_its_path_before_any_portfolio_figure():
    """The operator must know which envelope produced the numbers before they
    read one. In the source that means the path line is emitted ahead of the
    split, and the portable branch says what INSUFFICIENT means."""
    src = (ROOT / "run-demo").read_text()

    path_at = src.index("ATTEST · GENERATED · $PATHNAME")
    split_at = src.index("$SPLIT")
    assert path_at < split_at, \
        "run-demo prints portfolio figures before naming the execution path"

    portable = src[src.index('if [ "$PATHNAME" = "PORTABLE" ]'):split_at]
    assert "INSUFFICIENT" in portable
    assert "maturin develop --release" in portable, \
        "the portable branch does not say how to match the recording"
    assert "identical on both paths" in portable, \
        "the portable branch does not say the canonical case is unaffected"

    # and it must not call the portable result broken. Bare word matching is
    # not enough: the branch says "not a failure to reconcile them", which is
    # the opposite of the thing being guarded against.
    low = portable.lower()
    for slur in ("failed", "failure", "error", "incorrect", "wrong", "broken"):
        for m in re.finditer(re.escape(slur), low):
            before = low[max(0, m.start() - 14):m.start()]
            if re.search(r"\bnot an?\s*$|\bnot\s*$|\brather than\s*$", before):
                continue                      # negated: the branch is denying it
            raise AssertionError(
                f"run-demo describes the portable result as {slur!r}; it is "
                f"the engine declining to search a space it cannot finish")


def test_the_readme_states_both_paths_before_the_reviewer_path():
    """A judge should not discover the kernel requirement at line 351."""
    text = (ROOT / "README.md").read_text()
    repro = text.index("### Reproduce the demo")

    # §59 reordered the README around the product rather than the build, so the
    # reproduce section is no longer literally first. The guarantee it was
    # protecting is unchanged and is asserted directly: a reviewer must learn
    # there ARE two paths before they read a portfolio figure, and the figures
    # for both must be stated side by side wherever the build is described.
    fold = text[:text.index("## The problem")]
    assert "execution path" in fold.lower(), (
        "the README does not tell a reviewer there are two execution paths "
        "before it starts making claims")
    assert "native" in fold.lower(), "the fold does not name the recorded path"

    head = text[repro:repro + 2500]
    assert "maturin develop --release" in head, \
        "the native build is not in the reproduce section"
    # Both paths' figures, side by side. Read out of the table rather than
    # pinned: the counts follow the demo seed, and pinning them made §47.F1's
    # seed change look like the README had stopped stating them at all.
    rows = re.findall(
        r"\|\s*\*\*(Native kernel|Portable)\*\*[^|]*\|[^|]*\|([^|]*)\|", head)
    assert len(rows) == 2, \
        f"the README does not state both paths' figures side by side: {rows}"
    for name, figs in rows:
        assert re.search(r"\d+ proven", figs), f"{name} states no proven count"
        assert re.search(r"\d+ ambiguous", figs), f"{name} states no ambiguous count"
    assert re.search(r"\d+ insufficient", head.lower()), \
        "the README does not state the portable path's insufficient count"
    assert "identical on both" in head, \
        "the README does not say the canonical case is path-independent"


def test_no_submission_document_states_native_figures_unlabelled():
    """Every place the recorded 197 appears as a portfolio count, the native
    path is named nearby. This is the mistake the rehearsal caught, and it is
    the one that would let a judge's own run contradict the video."""
    # The native run's counts, whichever seed the demo is on. These moved with
    # §47.F1 and the guard went quiet because it was still watching for the
    # old ones - a guard that matches nothing passes for the wrong reason.
    NATIVE_ONLY = re.compile(r"210 ambiguous|39 proven|210 settlements")
    CONTEXT = ("native", "recorded", "kernel")
    offenders = []
    # The demo choreography and the submission checklist were development
    # artifacts and are no longer public; the README is the surface a native-
    # only count could still reach a reader from. The list stays a list because
    # the next surface to carry these counts belongs in it, not in a rewrite.
    for rel in ("README.md",):
        f = ROOT / rel
        if not f.exists():
            continue
        text = f.read_text()
        for m in NATIVE_ONLY.finditer(text):
            window = text[max(0, m.start() - 700):m.start() + 400].lower()
            if not any(c in window for c in CONTEXT):
                line = text[:m.start()].count("\n") + 1
                offenders.append(f"{rel}:{line} — {m.group(0)!r}")
    assert not offenders, (
        "native-kernel portfolio figures presented without naming the path:\n  "
        + "\n  ".join(offenders[:8]))
