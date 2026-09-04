"""The engine.

Order of work is itself an optimisation. Settlements are attempted
easiest-first -- smallest candidate pool -- because every settlement proven
removes its orders from every remaining pool. Proving the easy ones first is
constraint propagation: the hard cases are attempted against a materially
smaller search space than they would have faced in isolation, and some become
decidable only because of it.

Escalation runs the other way. A settlement is tried against the tightest date
window first; the window widens only when the verdict comes back CONTRADICTED,
which is precisely the signal that the true explanation was pruned rather than
absent. Cost is paid where the difficulty is, and the rung that succeeded is
recorded on the finding so escalation shows up in the audit trail.
"""

from __future__ import annotations

import os

from attest.blocking import LAG_LADDER, PoolIndex
from attest.eval.harness import Prediction
from attest.evidence import to_fixed_point
from attest.layers import match_single_order
from attest.model import Order, Settlement, tolerance_paise
from attest.subsetsum import OutOfEnvelope, solve_with_context
from attest.verdict import Finding, Proof, Verdict, check


def _proof(s: Settlement, members: list[Order]) -> Proof:
    gross = sum(o.gross_paise for o in members)
    net = sum(o.net for o in members)
    return Proof(
        settlement_id=s.settlement_id,
        order_ids=tuple(o.order_id for o in members),
        gross_paise=gross,
        fee_paise=gross - net,
        tax_paise=0,
        adjustment_paise=0,
        net_paise=net,
        residual_paise=s.net_paise - net,
        tolerance_paise=tolerance_paise(len(members)),
        constraints={"amount": True, "window": True, "uniqueness": True},
    )


def _attach_cores(settlements: list[Settlement], orders: list[Order],
                  findings: list[Finding]) -> None:
    """Overlay solver-extracted conflict explanations onto unresolved findings.

    Best-effort by design: ortools is an optional dependency and a missing core
    costs an explanation, never a verdict. Failing a run because the *reason*
    could not be computed would be the wrong trade.
    """
    try:
        from attest.partition import pack
        packed = pack(settlements, orders, forcing=True, extract_cores=True)
    except Exception:
        return

    cores = {f.settlement_id: f.unsat_core for f in packed.findings if f.unsat_core}
    for i, f in enumerate(findings):
        core = cores.get(f.settlement_id)
        if core and not f.unsat_core and f.verdict is not Verdict.PROVEN:
            findings[i] = Finding(
                f.settlement_id, f.verdict, f.proofs, unsat_core=core,
                space=f.space, coincidence=f.coincidence,
                exhaustive=f.exhaustive, layer=f.layer + "+core")


def run(settlements: list[Settlement], orders: list[Order],
        cores: bool = False) -> tuple[
    list[Prediction], dict[str, list[Order]], list[Finding]
]:
    index = PoolIndex(orders)
    by_id = {o.order_id: o for o in orders}

    # Easiest-first. Cheap proxy for difficulty, computed once against the
    # tightest window: a settlement with few candidates is both fast to decide
    # and likely to free orders that shrink everyone else's pool.
    order_of_work = sorted(settlements, key=lambda s: len(index.pool(s, 0)))

    findings: list[Finding] = []
    preds: list[Prediction] = []
    pools_used: dict[str, list[Order]] = {}

    for s in order_of_work:
        finding: Finding | None = None

        for rung in range(len(LAG_LADDER)):
            pool, space = index.audited_pool(s, rung)
            pools_used[s.settlement_id] = pool

            single = match_single_order(s, pool)
            if single is not None:
                members = [by_id[single[0]]]
                p = _proof(s, members)
                if check(p, s, by_id):
                    finding = Finding(s.settlement_id, Verdict.PROVEN, (p,),
                                      exhaustive=True, space=space,
                                      layer=f"L2-single/r{rung}")
                    break

            try:
                verdict, sols, exhaustive, coin = solve_with_context(
                    pool, s.net_paise)
            except OutOfEnvelope as exc:
                finding = Finding(s.settlement_id, Verdict.INSUFFICIENT, (),
                                  unsat_core=(f"out-of-envelope: {exc}",),
                                  space=space, layer=f"L3-skipped/r{rung}")
                break

            if verdict is Verdict.CONTRADICTED:
                continue  # pruned, not absent -- widen and retry

            proofs = tuple(
                p for p in (_proof(s, [by_id[o] for o in sol.order_ids]) for sol in sols)
                if check(p, s, by_id)
            )
            if not proofs:
                continue
            finding = Finding(
                s.settlement_id,
                Verdict.PROVEN if len(proofs) == 1 else Verdict.AMBIGUOUS,
                proofs, exhaustive=exhaustive, space=space,
                coincidence=coin, layer=f"L3-dp/r{rung}",
            )
            break

        if finding is None:
            _, space = index.audited_pool(s, len(LAG_LADDER) - 1)
            finding = Finding(
                s.settlement_id, Verdict.CONTRADICTED, (),
                unsat_core=("no subset of any window satisfies the amount constraint",),
                space=space, layer="L3-dp/exhausted",
            )

        findings.append(finding)
        if finding.postable:
            index.consume(finding.proofs[0].order_ids)

        preds.append(Prediction(
            s.settlement_id,
            list(finding.proofs[0].order_ids) if finding.postable else None,
            finding.layer,
            reason="" if finding.postable else finding.verdict.value,
        ))

    # L4b -- name the conflicts, but do not resolve them.
    #
    # The CP-SAT packing itself was benchmarked against this greedy cascade and
    # REJECTED: +0.64 pp exact-set match for +0.32 pp WRONG, pooled over 1,250
    # settlements, with precision moving 0.9807 -> 0.9714 and a straight
    # regression at n=1200. Same trade as D4 and D8, refused for the same reason.
    # See hive reports/attest-cpsat.md and FAILURES.md D12.
    #
    # The unsat cores are a different matter. Set packing is trivially feasible
    # -- select nothing -- so infeasibility has to be asked for, with one
    # assumption literal per settlement meaning "this one must be explained".
    # What comes back is extracted by the solver's own conflict analysis rather
    # than reconstructed by a heuristic afterwards, and it converts "no valid
    # assignment" into "these two settlements are fighting over these orders".
    # It changes no verdict and moves no money; it only says why.
    if cores:
        _attach_cores(settlements, orders, findings)

    # L4 -- settlements are evidence about each other. Deducing across the whole
    # population resolves cases no single-settlement search can decide.
    # Off by default. Measured at +3.2pp exact-set for +3.2pp WRONG: eight more
    # correct answers bought with eight more false proofs. Under any cost model
    # where a wrong auto-post exceeds the cost of a human review -- which is the
    # only model this engine is built for -- that trade is negative. Enable with
    # ATTEST_PROP=1 to reproduce the ablation. See FAILURES.md, D4.
    rounds = to_fixed_point(findings) if os.environ.get("ATTEST_PROP") else []
    promoted = sum(r.promoted for r in rounds)
    if promoted:
        print(f"  propagation: {len(rounds)} rounds, "
              f"{sum(r.killed for r in rounds)} candidates eliminated, "
              f"{promoted} settlements promoted to PROVEN")

    preds = [
        Prediction(
            f.settlement_id,
            list(f.proofs[0].order_ids) if f.postable else None,
            f.layer,
            reason="" if f.postable else f.verdict.value,
        )
        for f in findings
    ]
    return preds, pools_used, findings
