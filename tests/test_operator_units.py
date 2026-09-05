"""Phase 12 · G-1. Money an operator reads is money in rupees.

exceptions.py's own docstring promises "Six orders explain all but ₹680.74".
policy._rs() argues the case: money that has to be converted before it can be
judged is money that will be misjudged. These pin that promise to the strings
the product actually paints.

A tolerance of ±31 paise is deliberately exempt: sub-rupee is the honest unit
for a tolerance, and ₹0.31 would read worse.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from attest.exceptions import classify
from attest.generate.generator import build as build_dataset
from attest.graph import build as build_graph
from attest.pipeline import run
from attest.searchspace import amount_ceiling

SEED, N = 20260821, 250

# an integer of 4+ digits immediately before the word "paise"
BARE_PAISE = re.compile(r"\b\d{4,}\s+paise\b")
# ...or a bare 4+ digit integer where money is being narrated
BARE_INT_MONEY = re.compile(
    r"\b(?:explain|explains|totalling|worth|reaches only|credit of|of)\s+\d{4,}\b")


def _offending(text: str) -> list[str]:
    return BARE_PAISE.findall(text) + BARE_INT_MONEY.findall(text)


@pytest.fixture(scope="module")
def demo():
    ds = build_dataset(N, seed=SEED)
    _, pools, findings = run(ds.settlements, ds.orders)
    sett = {s.settlement_id: s for s in ds.settlements}
    orders = {o.order_id: o for o in ds.orders}
    excs = {}
    for i, f in enumerate(findings):
        e = classify(f, sett[f.settlement_id], list(pools.get(f.settlement_id, ())), i)
        if e is not None:
            excs[f.settlement_id] = e
    return {"findings": {f.settlement_id: f for f in findings}, "sett": sett,
            "orders": orders, "excs": excs}


def test_exception_evidence_never_narrates_bare_paise(demo):
    """Every string a person reads in an exception is rupee-formatted."""
    bad: list[tuple[str, str]] = []
    for sid, exc in demo["excs"].items():
        for line in (*exc.established, exc.next_step, exc.missing):
            if _offending(line):
                bad.append((sid, line))
    assert not bad, "bare paise reached operator text:\n" + "\n".join(
        f"  {sid}: {line}" for sid, line in bad[:8])


def test_contradicted_case_states_both_amounts_in_rupees(demo):
    """setl_000109 is the case a stranger is asked to read in Phase 12 Part 9.

    It must not say "4 orders explain 586898 paise of 631603".
    """
    exc = demo["excs"].get("setl_000109")
    assert exc is not None, "setl_000109 is expected to be an exception"
    joined = " ".join(exc.established)
    assert not _offending(joined), f"bare paise in contradicted evidence: {joined}"
    assert "₹" in joined, f"no rupee amount in contradicted evidence: {joined}"


def test_search_space_reduction_reasons_are_rupee_formatted():
    r = amount_ceiling(removed=3, credit_paise=11613)
    assert not _offending(r.justification), r.justification
    assert "₹116.13" in r.justification, r.justification


def test_graph_edge_labels_are_rupee_formatted(demo):
    """The evidence graph labels every order edge with its net."""
    bad = []
    for sid in ("setl_000089", "setl_000109", "setl_000020"):
        f = demo["findings"].get(sid)
        if f is None:
            continue
        g = build_graph(f, demo["sett"][sid], demo["orders"])
        for e in g.edges:
            if _offending(e.why or ""):
                bad.append((sid, e.why))
    assert not bad, "bare paise on graph edges:\n" + "\n".join(
        f"  {s}: {l}" for s, l in bad[:8])


def test_tolerance_stays_in_paise(demo):
    """The exemption is deliberate — pin it so nobody "fixes" it later."""
    seen = [line for exc in demo["excs"].values() for line in exc.established
            if "tolerance" in line or "±" in line]
    assert any(re.search(r"±\d+ paise", s) for s in seen), \
        f"tolerance should still be expressed in paise, saw: {seen[:4]}"


def test_there_is_exactly_one_money_formatter():
    """Phase 25 §C. One obvious representation, and one way to render it.

    Phase 12 moved rendering into attest/money.py and routed exceptions, graph,
    searchspace and policy through it. Two copies survived that sweep — one in
    api.py and one in eval/claims.py — and they had drifted apart: the claims
    copy used Western grouping and dropped the paise entirely, so ₹353.73 was
    published to the README as ₹353 and ₹47,96,811.78 as ₹4,796,811.

    In a system whose whole argument is exact integer paise, a report that
    silently truncates them is not a style difference.
    """
    import ast

    # Walked from the filesystem, not `git ls-files`: a clean-room extraction
    # is not a git working tree, so a contract that asks git gets an empty list
    # there and passes for the wrong reason. The clean room caught this one.
    sources = sorted((ROOT / "attest").rglob("*.py"))
    assert sources, "no package sources found"
    defs = []
    for path in sources:
        f = path.relative_to(ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.FunctionDef) and node.name in ("_rs", "rupees"):
                defs.append(f"{f}:{node.lineno} {node.name}")
    # the file, not the line: pinning a line number tests the fixture
    assert sorted({d.split(":")[0] for d in defs}) == ["attest/money.py"], (
        "money is rendered in more than one place:\n  " + "\n  ".join(defs))


def test_every_money_renderer_agrees_on_paise_and_grouping():
    """Whatever renders an amount renders all of it, in Indian grouping."""
    from attest.money import rupees
    assert rupees(35373) == "₹353.73"
    assert rupees(479681178) == "₹47,96,811.78"
    assert rupees(9775984) == "₹97,759.84"
    assert rupees(0) == "₹0.00"
    assert rupees(-450) == "-₹4.50"


# --------------------------------------------------------------------------
# The anchoring measurement. F1.
#
# D8 disabled the hypothesis loop on a hand-taken measurement of 0.521. The
# measurement was later made re-runnable (attest/eval/anchoring.py) and the
# re-measurement came back at 0.4286 — worse, so the conclusion held and nobody
# noticed that five strings across the product still quoted the superseded
# number. A claim that decides whether a feature ships may not live in a Python
# string that nothing checks.
# --------------------------------------------------------------------------

ANCHORING = ROOT / "benchmark" / "anchoring.json"


def _anchoring():
    import json
    return json.loads(ANCHORING.read_text())


def test_the_anchoring_artifact_still_carries_what_the_claim_needs():
    """If the artifact stops reporting these, the claim has nothing to rest on."""
    a = _anchoring()
    for k in ("precision", "resolved", "correct", "wrong"):
        assert k in a, f"anchoring.json no longer reports {k}"
    assert a["resolved"] == a["correct"] + a["wrong"], \
        f"resolved != correct + wrong: {a}"
    assert 0.0 <= a["precision"] <= 1.0


def test_no_product_code_quotes_a_superseded_anchoring_precision():
    """F1. 0.521 was superseded by the re-measurement and may survive only as
    history — never as the current figure.

    The check is chronology, not arithmetic: an occurrence is allowed when the
    surrounding text says it is the earlier measurement, and refused when it
    stands bare. Rounding variants of the artifact's own number (0.429, 42.9%)
    are the current claim and are fine.
    """
    import re
    HISTORICAL_FILES = {
        "FAILURES.md",                    # D8's own record
        "attest/eval/anchoring.py",       # explains why it was re-measured
        "tests/test_operator_units.py",   # this file
    }
    # A directory whose whole job is to hold superseded chronology is exempt
    # from the "state the current figure" rule. `docs/archive/` held that job
    # and was removed as development scratchpad; `reports/` now carries the
    # historical record that remains, and it is exempt for the same reason —
    # a defect report describes what WAS true before the fix.
    HISTORICAL_DIRS = ("reports/",)
    CHRONOLOGY = ("supersed", "hand-taken", "by hand", "d8 measured",
                  "d8 first measured", "d8 recorded", "d8 disabled",
                  "earlier", "historical", "first measured")
    offenders = []
    for path in sorted(ROOT.rglob("*.py")) + sorted(ROOT.rglob("*.md")):
        rel = path.relative_to(ROOT).as_posix()
        if (rel.startswith((".venv", "native/.venv", ".git"))
                or rel.startswith(HISTORICAL_DIRS)
                or rel in HISTORICAL_FILES):
            continue
        text = path.read_text(errors="ignore")
        for m in re.finditer(r"0\.521|52\.1\s?%", text):
            window = text[max(0, m.start() - 220):m.start() + 120].lower()
            if any(c in window for c in CHRONOLOGY):
                continue
            line = text[:m.start()].count("\n") + 1
            offenders.append(f"{rel}:{line}")
    assert not offenders, (
        "the superseded 0.521 is presented as current, with no chronology:\n  "
        + "\n  ".join(sorted(set(offenders))))


def test_the_displayed_anchoring_claim_is_read_from_the_artifact():
    """The number the product shows is the artifact's, computed at call time —
    not a literal that a re-measurement would leave behind."""
    from attest.api import anchoring_measurement
    a = _anchoring()
    claim = anchoring_measurement()
    assert claim["correct"] == a["correct"]
    assert claim["resolved"] == a["resolved"]
    assert abs(claim["precision"] - a["precision"]) < 1e-9
    assert claim["source"] == "benchmark/anchoring.json"
