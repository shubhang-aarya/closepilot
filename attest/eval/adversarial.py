"""Adversarial pass over the whole chain. Outcomes observed, not predicted.

    SOURCE -> NORMALIZATION -> SEARCH SPACE -> MEMBERSHIP -> SOLVER
           -> PROOF -> POLICY -> ACTION -> LEDGER

Each attack tries to make the chain wrong, ambiguous, duplicated, stale,
forged, incomplete, out-of-order or malformed.

**A harness error is not a defence.** The first version of this file counted any
raised exception as the system refusing, and four attacks came back DEFENDED on
the strength of `AttributeError: 'Pipeline' object has no attribute 'run'` —
which is this file being wrong about the API, not the pipeline stopping an
attack. An adversarial pass that scores its own bugs as wins is worse than no
pass at all, because it produces a page of green.

So each attack declares the exception types that would constitute a REFUSAL.
Anything else is HARNESS ERROR, reported separately and counted as neither.

**Every stage carries a control.** A kernel that rejects everything defends every
attack trivially. Controls assert the legitimate case still succeeds, so a
defence means "this was refused and the honest version was not".
"""
from __future__ import annotations

import datetime as dt

from attest.adapters.money import AmountError, Unit, parse_amount
from attest.adapters.razorpay import RazorpayAdapter
from attest.agents import Capability, Pipeline
from attest.ledger import Unbalanced, JournalEntry, Line, post
from attest.model import Order, Settlement, Method
from attest.searchspace import Integrity, Reduction, SearchSpace
from attest.verdict import Finding, Proof, Verdict, check

#: DEFENDED, BREACH, CONTROL-OK, CONTROL-BROKEN or HARNESS-ERROR
#: A real agent from the roster. The first version used "reader",
#: which does not exist — so every ACTION attack was refused as
#: "unknown agent" rather than by the gate under test, and read as
#: DEFENDED. Refused for the wrong reason is not defended.
_AGENT = "reconciliation"

RESULTS: list[tuple[str, str, str, str, str]] = []


def attack(stage: str, kind: str, name: str, refuses: type | tuple = (),
           control: bool = False):
    """`refuses` names the exceptions that count as the system refusing.

    Anything raised outside that set is this file's bug, not a defence.
    """
    def deco(fn):
        try:
            ok, detail = fn()
            verdict = ("CONTROL-OK" if control and ok else
                       "CONTROL-BROKEN" if control else
                       "DEFENDED" if ok else "BREACH")
        except Exception as e:
            if refuses and isinstance(e, refuses):
                verdict, detail = ("CONTROL-BROKEN" if control else "DEFENDED"), \
                    f"refused with {type(e).__name__}: {e}"
            else:
                verdict, detail = "HARNESS-ERROR", f"{type(e).__name__}: {e}"
        RESULTS.append((stage, kind, name, verdict, str(detail)[:130]))
        return fn
    return deco


def _order(oid, paise):
    return Order(order_id=oid, captured_on=dt.date(2026, 5, 6), gross_paise=paise,
                 method=Method.UPI, customer_name="", payment_id=oid)


def _space(universe=5, members=("o1", "o2", "o3", "o4", "o5")):
    return SearchSpace(universe=universe,
                       reductions=(Reduction("amount ceiling", 2, True, "x"),),
                       members=frozenset(members))


def _sound_proof():
    """Two 1000-paise UPI orders against a 2000-paise credit.

    Tolerance is k paise for k orders, so two orders is 2 — not 1. The first
    version of this file wrote 1 and the kernel rejected it, which read as the
    kernel failing its own control. It was the control that was wrong.
    """
    return Proof("s1", ("o1", "o2"), 2000, 0, 0, 0, 2000, 0, 2)


def _judgement():
    from attest.policy import Decision, Judgement
    return Judgement(decision=Decision.AUTO_POST, expected_loss_paise=0,
                     p_error=0.0, reasons=())


def _proven(order_ids=("o1", "o2"), space=None, layer="exact"):
    return Finding(settlement_id="s1", verdict=Verdict.PROVEN,
                   proofs=[Proof("s1", tuple(order_ids), 1000, 0, 0, 0, 1000, 0, 1)],
                   space=space if space is not None else _space(), layer=layer)


# ---------------------------------------------------------------- SOURCE ---
@attack("SOURCE", "duplicated", "same recon row delivered twice")
def _():
    a = RazorpayAdapter()
    r = {"entity_id": "p1", "payment_id": "p1", "type": "payment",
         "settlement_id": "s1", "amount": 1000, "credit": 1000, "debit": 0,
         "fee": 0, "tax": 0, "method": "upi"}
    s = a.normalise([dict(r), dict(r)], [])
    return s.settlements[0].net_paise == 1000, f"net={s.settlements[0].net_paise}, dup={s.duplicates}"


@attack("SOURCE", "out-of-order", "pages delivered in reverse order")
def _():
    a = RazorpayAdapter()
    def row(i):
        return {"entity_id": f"p{i}", "payment_id": f"p{i}", "type": "payment",
                "settlement_id": "s1", "amount": i * 100, "credit": i * 100,
                "debit": 0, "fee": 0, "tax": 0, "method": "upi"}
    fwd = a.normalise([row(1), row(2), row(3)], [])
    rev = a.normalise([row(3), row(2), row(1)], [])
    return (fwd.settlements[0].net_paise == rev.settlements[0].net_paise
            and sorted(o.order_id for o in fwd.orders) == sorted(o.order_id for o in rev.orders)), \
        "aggregation is commutative"


@attack("SOURCE", "malformed", "row is a string, not an object")
def _():
    s = RazorpayAdapter().normalise(["garbage"], [])
    return bool(s.rejected) and not s.orders, f"rejected={s.rejected[0].reason[:50]}"


@attack("SOURCE", "forged", "row claims two different identities")
def _():
    s = RazorpayAdapter().normalise([{"entity_id": "a", "refund_id": "b",
        "type": "refund", "settlement_id": "s1", "credit": 0, "debit": 1,
        "fee": 0, "tax": 0}], [])
    return bool(s.rejected), f"rejected={s.rejected[0].reason[:60] if s.rejected else 'NO'}"


# --------------------------------------------------------- NORMALIZATION ---
@attack("NORMALIZATION", "wrong", "fractional paise silently truncated")
def _():
    try:
        v = parse_amount(10.5, Unit.PAISE)
        return False, f"BREACH: accepted as {v}"
    except AmountError as e:
        return True, str(e)[:70]


@attack("NORMALIZATION", "wrong", "rupee value read under a paise contract")
def _():
    try:
        v = parse_amount("10.50", Unit.PAISE)
        return False, f"BREACH: accepted as {v}"
    except AmountError:
        return True, "refused; unit must be declared"


@attack("NORMALIZATION", "malformed", "NaN / Infinity / negative amounts")
def _():
    bad = [float("nan"), float("inf"), -1, "abc", None, True]
    got = []
    for b in bad:
        try:
            parse_amount(b, Unit.PAISE); got.append(repr(b))
        except AmountError:
            pass
    return not got, f"accepted: {got}" if got else "all six refused"


@attack("NORMALIZATION", "incomplete", "unreadable amount shrinks the target")
def _():
    s = RazorpayAdapter().normalise([{"entity_id": "p1", "payment_id": "p1",
        "type": "payment", "settlement_id": "s1", "amount": 10.5,
        "credit": 1000, "debit": 0, "fee": 0, "tax": 0, "method": "upi"}], [])
    return s.settlements[0].net_paise == 1000 and not s.orders, \
        f"target held at {s.settlements[0].net_paise}, order dropped"


# ---------------------------------------------------------- SEARCH SPACE ---
@attack("SEARCH SPACE", "forged", "proof carries no search space at all")
def _():
    f = Finding("s1", Verdict.PROVEN,
                [Proof("s1", ("o1",), 1000, 0, 0, 0, 1000, 0, 1)],
                space=None, layer="exact")
    return not f.postable, f"postable={f.postable}"


@attack("SEARCH SPACE", "forged", "search space is a look-alike object")
def _():
    class Fake:
        """Every attribute postable() reads, none of the type it requires."""
        universe, reductions = 5, ("amount ceiling",)
        members = frozenset({"o1", "o2"})
        integrity = Integrity.VALIDATED
    f = _proven(space=Fake())
    return not f.postable, f"duck-typed space postable={f.postable}"


@attack("SEARCH SPACE", "incomplete", "space records no universe")
def _():
    return not _proven(space=_space(universe=0)).postable, "universe=0 refused"


@attack("SEARCH SPACE", "wrong", "compromised space still tries to post")
def _():
    sp = SearchSpace(universe=5, reductions=(
        Reduction("unaccounted", 3, False, ""),), members=frozenset({"o1", "o2"}),
        known_loss=1)
    f = _proven(space=sp)
    return not f.postable, f"integrity={sp.integrity.value}, postable={f.postable}"


# ------------------------------------------------------------ MEMBERSHIP ---
@attack("MEMBERSHIP", "forged", "proof cites orders that exist nowhere")
def _():
    return not _proven(order_ids=("X", "Y")).postable, "foreign ids refused"


@attack("MEMBERSHIP", "forged", "one foreign order among four real ones")
def _():
    return not _proven(order_ids=("o1", "o2", "o3", "GHOST")).postable, \
        "a single foreign id is enough"


@attack("MEMBERSHIP", "incomplete", "space records no members")
def _():
    return not _proven(space=_space(members=())).postable, "no members recorded"


@attack("MEMBERSHIP", "wrong", "cardinality satisfied, membership not")
def _():
    # the CORE-002 attack: 2 cited <= 5 universe, but neither belongs
    f = _proven(order_ids=("X", "Y"), space=_space(universe=5))
    return not f.postable, "counting is not belonging"


# ---------------------------------------------------------------- SOLVER ---
def _kernel_case():
    st = Settlement(settlement_id="s1", settled_on=dt.date(2026, 5, 8),
                    net_paise=2000, utr="U1")
    orders = {"o1": _order("o1", 1000), "o2": _order("o2", 1000),
              "o3": _order("o3", 700)}
    return st, orders


@attack("SOLVER", "forged", "proof whose orders do not sum to the credit")
def _():
    st, orders = _kernel_case()
    p = Proof("s1", ("o1", "o3"), 1700, 0, 0, 0, 1700, 0, 1)
    return not check(p, st, orders), "kernel rejects the sum"


@attack("SOLVER", "duplicated", "same order cited twice to reach the total")
def _():
    st, orders = _kernel_case()
    p = Proof("s1", ("o1", "o1"), 2000, 0, 0, 0, 2000, 0, 1)
    return not check(p, st, orders), "kernel rejects the duplicate"


@attack("SOLVER", "forged", "proof cites an order the run never saw")
def _():
    st, orders = _kernel_case()
    p = Proof("s1", ("o1", "ghost"), 2000, 0, 0, 0, 2000, 0, 1)
    return not check(p, st, orders), "kernel rejects the unknown id"


@attack("SOLVER", "control", "a genuinely correct proof still passes", control=True)
def _():
    st, orders = _kernel_case()
    return check(_sound_proof(), st, orders), \
        "the kernel is not simply refusing everything"


# ----------------------------------------------------------------- PROOF ---
@attack("PROOF", "ambiguous", "AMBIGUOUS finding carrying a single explanation")
def _():
    f = Finding("s1", Verdict.AMBIGUOUS,
                [Proof("s1", ("o1",), 1000, 0, 0, 0, 1000, 0, 1)],
                space=_space(), layer="exact")
    return not f.postable, f"postable={f.postable}"


@attack("PROOF", "wrong", "CONTRADICTED finding that still carries a proof")
def _():
    f = Finding("s1", Verdict.CONTRADICTED,
                [Proof("s1", ("o1",), 1000, 0, 0, 0, 1000, 0, 1)],
                space=_space(), layer="exact")
    return not f.postable, f"postable={f.postable}"


@attack("PROOF", "incomplete", "proof with no solver provenance")
def _():
    return not _proven(layer="").postable, "layer='' refused"


# --------------------------------------------------------------- ACTION ----
@attack("ACTION", "forged", "agent configured with a write capability",
        refuses=PermissionError)
def _():
    from attest.agents import Agent
    try:
        a = Agent(id="x", name="x", purpose="x",
                  capabilities=frozenset({Capability.POST_ENTRY}))
        return False, f"BREACH: constructed {a.capabilities}"
    except Exception as e:
        return True, f"refused at construction: {type(e).__name__}"


@attack("ACTION", "forged", "unproven finding pushed through the pipeline")
def _():
    f = Finding("s1", Verdict.AMBIGUOUS, [], space=_space(), layer="exact")
    at = Pipeline().request(_AGENT, "post", "s1", Capability.POST_ENTRY,
                            evidence=object(), finding=f, judgement=_judgement())
    return not at.permitted, f"permitted={at.permitted}; stopped at "\
                             f"{at.stopped_at}: {at.steps[-1].detail[:60]}"


@attack("ACTION", "forged", "compromised space, but verdict says PROVEN")
def _():
    sp = SearchSpace(universe=5, reductions=(Reduction("u", 3, False, ""),),
                     members=frozenset({"o1", "o2"}), known_loss=1)
    at = Pipeline().request(_AGENT, "post", "s1", Capability.POST_ENTRY,
                            evidence=object(), finding=_proven(space=sp),
                            judgement=_judgement())
    return not at.permitted, f"permitted={at.permitted}; stopped at {at.stopped_at}"


@attack("ACTION", "forged", "unproven finding, using a capability the agent HOLDS")
def _():
    # The two attacks above stop at CAPABILITY, which is the strongest possible
    # refusal but means the later gates are never reached. RUN_SOLVER is held by
    # `reconciliation`, so this one gets past CAPABILITY and is judged by the
    # verification gate itself.
    f = Finding("s1", Verdict.AMBIGUOUS, [], space=_space(), layer="exact")
    at = Pipeline().request(_AGENT, "solve", "s1", Capability.RUN_SOLVER,
                            evidence=object(), finding=f, judgement=_judgement())
    return not at.permitted, f"stopped at {at.stopped_at}: {at.steps[-1].detail[:60]}"


@attack("ACTION", "incomplete", "no evidence attached, capability held")
def _():
    at = Pipeline().request(_AGENT, "solve", "s1", Capability.RUN_SOLVER,
                            evidence=None, finding=_proven(),
                            judgement=_judgement())
    return not at.permitted, f"stopped at {at.stopped_at}: {at.steps[-1].detail[:60]}"


@attack("ACTION", "forged", "foreign order in the proof, capability held")
def _():
    at = Pipeline().request(_AGENT, "solve", "s1", Capability.RUN_SOLVER,
                            evidence=object(),
                            finding=_proven(order_ids=("o1", "GHOST")),
                            judgement=_judgement())
    return not at.permitted, f"stopped at {at.stopped_at}: {at.steps[-1].detail[:60]}"


@attack("ACTION", "control", "a held capability on a sound finding is permitted",
        control=True)
def _():
    at = Pipeline().request(_AGENT, "solve", "s1", Capability.RUN_SOLVER,
                            evidence=object(), finding=_proven(),
                            judgement=_judgement())
    return at.permitted, f"permitted={at.permitted} — the pipeline is not "\
                         f"refusing everything"


# ---------------------------------------------------------------- LEDGER ---
@attack("LEDGER", "wrong", "journal entry whose lines do not balance",
        refuses=Unbalanced)
def _():
    try:
        e = JournalEntry("s1", dt.date(2026, 5, 8), "U1",
                         [Line("bank", 1000, 0, ""), Line("recv", 0, 900, "")],
                         ("o1",), {}, 0, 1)
        return False, f"BREACH: constructed {e.settlement_id}"
    except Unbalanced as e:
        return True, f"refused: {e}"


@attack("LEDGER", "malformed", "one line is both a debit and a credit",
        refuses=(Unbalanced, ValueError))
def _():
    try:
        Line("bank", 1000, 1000, "")
        return False, "BREACH: constructed"
    except Exception as e:
        return True, f"refused: {type(e).__name__}"


@attack("LEDGER", "forged", "posting a finding whose proof cites a foreign order")
def _():
    st, orders = _kernel_case()
    f = Finding("s1", Verdict.PROVEN,
                [Proof("s1", ("X",), 2000, 0, 0, 0, 2000, 0, 2)],
                space=_space(), layer="exact")
    out = post(f, st, _judgement(), orders)
    return not isinstance(out, JournalEntry), \
        f"got {type(out).__name__}: {getattr(out, 'reason', '')[:70]}"


@attack("LEDGER", "forged",
        "a proof the kernel rejects, pushed straight at the ledger")
def _():
    """CORE-004, and the reason this attack exists at all.

    Every other LEDGER attack here forges something `postable` can see: a
    foreign order, an unbalanced entry, a verdict that is not PROVEN. This one
    forges the ARITHMETIC and leaves the search provenance immaculate — real
    orders, a recorded space, a named layer — so `postable` answers yes to all
    four of its questions and never notices the sum is wrong.

    Before the fix the ledger posted it, because the ledger did not ask the
    kernel. Found by a red-team review, not by this suite, which is the honest
    provenance and worth stating.
    """
    st, orders = _kernel_case()
    # o1 + o2 net to 2000; claim o1 + o3, which nets to 1700, against a 2000
    # credit -- then assert the arithmetic anyway. The kernel recomputes.
    p = Proof("s1", ("o1", "o3"), 1700, 0, 0, 0, 2000, 0, 2)
    sp = SearchSpace(universe=3, reductions=(Reduction("amount ceiling", 0, True, "x"),),
                     members=frozenset({"o1", "o2", "o3"}))
    f = Finding("s1", Verdict.PROVEN, [p], space=sp, layer="exact")
    if check(p, st, orders):
        return False, "BREACH: the kernel accepted a proof that does not balance"
    out = post(f, st, _judgement(), orders)
    return not isinstance(out, JournalEntry), \
        f"postable={f.postable}, ledger returned {type(out).__name__}"


@attack("LEDGER", "control", "a sound finding does post", control=True)
def _():
    st, orders = _kernel_case()
    sp = SearchSpace(universe=3, reductions=(Reduction("amount ceiling", 1, True, "x"),),
                     members=frozenset({"o1", "o2", "o3"}))
    f = Finding("s1", Verdict.PROVEN, [_sound_proof()], space=sp, layer="exact")
    out = post(f, st, _judgement(), orders)
    return isinstance(out, JournalEntry), \
        f"got {type(out).__name__}: {getattr(out, 'reason', '')[:70]}"


if __name__ == "__main__":
    w = 78
    C = {"DEFENDED": "\033[32m", "CONTROL-OK": "\033[32m",
         "BREACH": "\033[31m", "CONTROL-BROKEN": "\033[31m",
         "HARNESS-ERROR": "\033[33m"}
    print("\nADVERSARIAL PASS — SOURCE to LEDGER")
    print("=" * w)
    last = None
    for stage, kind, name, v, detail in RESULTS:
        if stage != last:
            print(f"\n  {stage}")
            last = stage
        print(f"    {C[v]}{v:<14}\033[0m {kind:<12} {name}")
        print(f"                   {detail}")

    bad = [r for r in RESULTS if r[3] in ("BREACH", "CONTROL-BROKEN")]
    harness = [r for r in RESULTS if r[3] == "HARNESS-ERROR"]
    ok = [r for r in RESULTS if r[3] in ("DEFENDED", "CONTROL-OK")]
    print("\n" + "=" * w)
    print(f"  {len(RESULTS)} attacks · {len(ok)} defended/control-ok · "
          f"{len(bad)} breached · {len(harness)} harness errors")
    for r in bad:
        print(f"    {r[3]}  {r[0]} / {r[1]} / {r[2]}\n            {r[4]}")
    for r in harness:
        print(f"    HARNESS-ERROR  {r[0]} / {r[2]}\n            {r[4]}")
    if harness:
        print("\n  A harness error is NOT a defence. These attacks did not run.")
    print("=" * w + "\n")

    # The result is written where the product can read it. Trust states this
    # count on screen, and a count typed into the UI by hand is a claim about a
    # pass that may not have run since. Same rule as benchmark/anchoring.json:
    # the surface reads the artifact, and if the artifact is missing the
    # surface says the pass has not been run rather than inventing a number.
    import json
    from pathlib import Path as _P
    art = _P(__file__).resolve().parents[2] / "benchmark" / "adversarial.json"
    art.write_text(json.dumps({
        "attacks": len(RESULTS),
        "defended": len(ok),
        "breached": len(bad),
        "harness_errors": len(harness),
        "stages": sorted({r[0] for r in RESULTS}),
        "breaches": [{"stage": r[0], "kind": r[1], "name": r[2], "detail": r[4]}
                     for r in bad],
    }, indent=2) + "\n")
    print(f"  wrote {art.relative_to(_P.cwd()) if art.is_relative_to(_P.cwd()) else art}\n")

    raise SystemExit(1 if bad or harness else 0)
