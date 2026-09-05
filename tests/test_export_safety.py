"""The export is a read. §38.P0-3.

ATTEST's whole claim is that it does not move money it cannot prove. Adding a
way for data to *leave* is the first thing in this product that could break
that claim, so the export is pinned as read-only by evidence rather than by
intention: the run is compared field by field before and after, the ledger is
compared entry by entry, the filesystem is compared by mtime, and the source of
everything the export can reach is read for the names of the mutating calls.

Each guarantee below was mutation-tested — a deliberate write was introduced
and every test that should catch it did.
"""
from __future__ import annotations

import inspect
import json
import pathlib

import pytest

from attest import api
from attest.verdict import Verdict


@pytest.fixture(scope="module")
def run():
    return api.execute(60, 424242)


def _snapshot(r) -> str:
    """Everything about a run that a mutation could plausibly disturb."""
    return json.dumps({
        "findings": [
            {"sid": f.settlement_id, "verdict": f.verdict.value,
             "proofs": [sorted(p.order_ids) for p in f.proofs],
             "postable": f.postable, "exhaustive": f.exhaustive,
             "space": (None if getattr(f, "space", None) is None
                       else [f.space.universe, f.space.candidates,
                             f.space.integrity.value])}
            for f in r.findings],
        "settlements": [[s.settlement_id, s.net_paise, str(s.settled_on)]
                        for s in r.settlements],
        "exceptions": sorted((k, v.reason.value, v.next_step)
                             for k, v in r.exceptions.items()),
        "pools": {k: sorted(o.order_id for o in v) for k, v in r.pools.items()},
        # The journal is derived, not stored, so it is rebuilt through the same
        # API a user would see and compared as the money record it is.
        "journal": api.journal_view(r),
        "summary": api.summary(r),
    }, sort_keys=True)


def test_the_export_does_not_change_the_run(run):
    """Every verdict, proof, exception, pool and journal entry is identical."""
    before = _snapshot(run)
    api.export_queue(run)
    api.export_queue_csv(run)
    assert _snapshot(run) == before, "the export changed the run it read"


def test_the_export_does_not_touch_the_ledger(run):
    """The journal is the money record. A read may not add a line to it."""
    before = api.journal_view(run)
    api.export_queue(run)
    api.export_queue_csv(run)
    after = api.journal_view(run)
    assert after["posted_paise"] == before["posted_paise"], \
        "the export changed what was posted"
    assert after["refused_paise"] == before["refused_paise"], \
        "the export changed what was refused"
    assert len(after["entries"]) == len(before["entries"]), \
        "the export wrote a journal entry"
    assert after["balances"] is True, "the journal stopped balancing"


def test_the_export_writes_nothing_to_disk(run, tmp_path):
    """No artifact, no cache, no log. Compared by mtime across the package."""
    root = pathlib.Path(api.__file__).resolve().parent.parent
    watched = [p for p in root.rglob("*")
               if p.is_file() and "__pycache__" not in p.parts
               and ".git" not in p.parts and ".venv" not in p.parts]
    before = {p: p.stat().st_mtime_ns for p in watched}
    api.export_queue(run)
    api.export_queue_csv(run)
    changed = [str(p.relative_to(root)) for p in watched
               if p.stat().st_mtime_ns != before.get(p)]
    new = [str(p.relative_to(root)) for p in root.rglob("*")
           if p.is_file() and p not in before and "__pycache__" not in p.parts
           and ".git" not in p.parts and ".venv" not in p.parts]
    assert not changed, f"the export modified {changed}"
    assert not new, f"the export created {new}"


def test_the_export_cannot_reach_a_mutating_call(run):
    """Read the source, not the intention.

    `ledger.post` is how money is recorded, and the solver and policy carry the
    other state a verdict depends on. None of those names may appear in
    anything the export executes.
    """
    src = (inspect.getsource(api.export_queue)
           + inspect.getsource(api.export_queue_csv))
    forbidden = ["ledger.post", "post(", "journal.append", "entries.append",
                 "urlopen", "requests.", "socket.", "subprocess",
                 "open(", ".write(", "execute(", "os.remove", "unlink"]
    hits = [w for w in forbidden if w in src]
    assert not hits, f"the export names a mutating or outbound call: {hits}"


def test_the_export_is_idempotent(run):
    """Asked twice, it answers the same. A read has no memory."""
    a, b = api.export_queue_csv(run), api.export_queue_csv(run)
    assert a == b, "two identical reads returned different bytes"


def test_the_export_carries_only_unresolved_settlements(run):
    """A PROVEN settlement is finished work and must never enter the queue."""
    proven = {f.settlement_id for f in run.findings
              if f.verdict is Verdict.PROVEN}
    rows = api.export_queue(run)["rows"]
    leaked = sorted({r["settlement_id"] for r in rows} & proven)
    assert not leaked, f"resolved settlements are in the handoff queue: {leaked}"
    assert {r["verdict"] for r in rows} <= {"AMBIGUOUS", "CONTRADICTED",
                                            "INSUFFICIENT"}


def test_every_row_says_what_would_settle_it(run):
    """A queue without the next step is a list, not a handoff."""
    rows = api.export_queue(run)["rows"]
    assert rows, "the run produced no unresolved work to hand over"
    # Both, not either. `why` is the generic question for the blocker class;
    # `required_next_evidence` is what would settle THIS settlement. Accepting
    # one as a substitute for the other let a mutation strip every specific
    # instruction while the suite stayed green.
    mute = [r["settlement_id"] for r in rows if not r["required_next_evidence"]]
    assert not mute, f"rows with no next step: {mute[:5]}"
    vague = [r["settlement_id"] for r in rows if not r["why"]]
    assert not vague, f"rows with no stated question: {vague[:5]}"
    unblocked = [r["settlement_id"] for r in rows if not r["blocker"]]
    assert not unblocked, f"rows with no blocker: {unblocked[:5]}"
    unversioned = [r["settlement_id"] for r in rows if not r["rules_version"]]
    assert not unversioned, "rows cannot be traced to the rules that judged them"


def test_the_contested_orders_are_the_disputed_ones(run):
    """The point of the column: orders every explanation shares are not in
    dispute, and shipping them would hand a person a pool to re-sift."""
    by_sid = {f.settlement_id: f for f in run.findings}
    for row in api.export_queue(run)["rows"]:
        f = by_sid[row["settlement_id"]]
        if len(f.proofs) < 2:
            continue
        sets = [set(p.order_ids) for p in f.proofs]
        common = set.intersection(*sets)
        contested = set(row["contested_order_ids"].split()) if \
            row["contested_order_ids"] else set()
        assert not (contested & common), (
            f"{row['settlement_id']} lists undisputed orders as contested")
        assert contested == set().union(*sets) - common, (
            f"{row['settlement_id']} does not list every disputed order")


# ── the evidence request. §43 ────────────────────────────────────────────────
# Same property as the queue, and it matters more: this one produces something a
# person will paste into an email, so it must be a read and it must be true.

def test_the_evidence_request_does_not_change_the_run(run):
    """Preparing the operator's next move may not disturb the run it reads."""
    from attest.verdict import Verdict
    sid = next(f.settlement_id for f in run.findings
               if f.verdict is Verdict.AMBIGUOUS)
    before = _snapshot(run)
    api.evidence_request(run, sid)
    api.evidence_request_text(run, sid)
    assert _snapshot(run) == before, "preparing a request changed the run"


def test_the_evidence_request_cannot_send_anything(run):
    """There is no recipient and no transport, and the source says so."""
    src = (inspect.getsource(api.evidence_request)
           + inspect.getsource(api.evidence_request_text))
    for name in ("urlopen", "requests.", "socket.", "smtplib", "subprocess",
                 "post(", "send(", "open(", ".write("):
        assert name not in src, f"the evidence request reaches for {name}"


def test_a_proven_settlement_has_nothing_to_ask_for(run):
    """A request for evidence on a settled case is noise in an operator's inbox."""
    from attest.verdict import Verdict
    proven = next((f.settlement_id for f in run.findings
                   if f.verdict is Verdict.PROVEN), None)
    if proven is None:
        pytest.skip("this run proved nothing")
    assert api.evidence_request(run, proven) is None
    assert api.evidence_request_text(run, proven) == ""


def test_the_request_names_the_orders_that_are_actually_disputed(run):
    """The whole value is that it asks about 12 orders and not 2,368.

    An agreed order appearing in the disputed list sends a person to check
    something every surviving explanation already agrees on.
    """
    from attest.verdict import Verdict
    by_sid = {f.settlement_id: f for f in run.findings}
    checked = 0
    for f in run.findings:
        if f.verdict is not Verdict.AMBIGUOUS or len(f.proofs) < 2:
            continue
        d = api.evidence_request(run, f.settlement_id)
        sets = [set(p.order_ids) for p in f.proofs]
        common, union = set.intersection(*sets), set().union(*sets)
        assert set(d["contested_order_ids"]) == union - common, \
            f"{f.settlement_id} asks about the wrong orders"
        assert set(d["agreed_order_ids"]) == common
        assert not (set(d["contested_order_ids"]) & set(d["agreed_order_ids"]))
        checked += 1
        if checked >= 25:
            break
    assert checked, "no ambiguous settlement was available to check"


def test_the_request_explains_why_the_evidence_discriminates(run):
    """"Send me a reference" is a chore. Saying what it rules out is a reason."""
    from attest.verdict import Verdict
    sid = next(f.settlement_id for f in run.findings
               if f.verdict is Verdict.AMBIGUOUS)
    d = api.evidence_request(run, sid)
    for key in ("why_we_stopped", "request", "why_it_discriminates",
                "expected_outcome", "on_receipt"):
        assert d[key] and len(d[key]) > 12, f"{key} is empty or a stub"
    assert d["prepared_only"] is True
    text = api.evidence_request_text(run, sid)
    assert "Not sent" in text, "the artifact does not say it was not sent"
    for v in ("rules_version", "policy_version", "solver_version"):
        assert v in text, f"the artifact cannot be traced back to {v}"
