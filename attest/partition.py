"""L4b -- global selection as SET PACKING, solved with CP-SAT.

Nothing in this file is wired into the engine. It is a measured alternative to
the greedy cascade in `attest/pipeline.py`, written so the comparison can be
made rather than asserted. See `hive/reports/attest-cpsat.md` for the numbers.

**The problem.** After L3 each settlement carries several candidate *subsets* of
orders. Two candidates conflict when they share an order, because an order
belongs to exactly one settlement. Choosing at most one candidate per settlement
such that the chosen subsets are pairwise disjoint is **set packing**: NP-hard,
an integer program, and -- as PRD.md section 4 sets out -- not expressible as
bipartite assignment. Hungarian matches elements of two sets one-to-one; it has
no vocabulary for "candidate A for S1 is incompatible with candidate B for S2
because both claim order #17". So this file does not reach for it.

**What the engine does today instead.** `PoolIndex.consume` removes a proven
settlement's orders from every remaining pool, easiest-first. That is set
packing solved *greedily and early*: disjointness is enforced, but by
irrevocable commitment in an arbitrary order rather than by search. The
interesting question -- the only one worth 40x the runtime -- is whether solving
it globally buys anything the greedy cascade does not already get.

**Soundness.** A packing solver will happily *choose* between two candidates
that are equally consistent with the data, and a chosen guess that moves money
is exactly the failure FAILURES.md D4 documents. So the optimum alone is not a
proof. A settlement is reported PROVEN here only when its candidate is
**forced**: no alternative solution of equal optimal value assigns it anything
else. That is checked by re-solving with the candidate forbidden and the
objective pinned, which is a decidable property of the program rather than a
score. Settlements whose candidate list was not exhaustively enumerated
(`MAX_ENUM` truncation) can never be forced, because "no alternative" would
then be a claim about a sample.

**Unsat cores.** Packing is trivially feasible -- select nothing. Infeasibility
only appears once coverage is *demanded*, so each component is re-posed with one
assumption literal per settlement meaning "this settlement must be explained".
`SufficientAssumptionsForInfeasibility` then names the settlements that cannot
all be right at once, and the shared orders they are fighting over become the
`Finding.unsat_core` strings. That is the difference between CONTRADICTED as a
shrug and CONTRADICTED as a diagnosis.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from attest.blocking import LAG_LADDER, PoolIndex
from attest.eval.harness import Prediction
from attest.layers import match_single_order
from attest.model import Order, Settlement, tolerance_paise
from attest.subsetsum import OutOfEnvelope, solve
from attest.verdict import Finding, Proof, Verdict, check

#: Per-CP-SAT-call ceiling. A call that times out is treated as *undecided*,
#: which for the forcing test means "not forced" -- the conservative direction,
#: costing recall rather than precision.
TIME_LIMIT_S = 10.0

#: Cap on how many distinct unsat cores are extracted per component before the
#: search stops. Cores are found by forbidding a member of each core already
#: seen, so this bounds a loop that is otherwise exponential.
MAX_CORES = 8


# --------------------------------------------------------------------------
# Candidates
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """One subset of orders that explains one settlement, within tolerance."""

    settlement_id: str
    order_ids: tuple[str, ...]
    net_paise: int
    layer: str


@dataclass
class CandidateSet:
    settlement_id: str
    candidates: list[Candidate]
    exhaustive: bool
    """True when L3 enumerated *every* explanation rather than the first
    `MAX_ENUM`. Forcing is unsound without it."""
    pool_size: int
    note: str = ""
    pool: list[Order] = field(default_factory=list)
    """The pool at the rung actually used, kept so the harness can compute the
    same blocking ceiling for this path as for the engine's."""


def collect(settlements: list[Settlement], orders: list[Order]) -> dict[str, CandidateSet]:
    """Candidate subsets per settlement, with NO global consumption.

    Deliberately different from `pipeline.run`: no order is ever struck from a
    later pool because an earlier settlement claimed it. That greedy cascade is
    the thing being compared against, so it must not contaminate the input.

    Pools are sorted by `order_id` before the solver sees them. `blocking.py`
    iterates a `set[date]`, whose order is hash-randomised per process, and the
    enumerator's sort is stable -- so without this pin, equal-net ties would
    break differently run to run and no result here would reproduce.
    """
    index = PoolIndex(orders)
    out: dict[str, CandidateSet] = {}

    for s in settlements:
        cs = CandidateSet(s.settlement_id, [], False, 0, "no-candidates")
        for rung in range(len(LAG_LADDER)):
            pool = sorted(index.pool(s, rung), key=lambda o: o.order_id)
            cs.pool_size = len(pool)
            cs.pool = pool

            seen: set[tuple[str, ...]] = set()
            found: list[Candidate] = []

            single = match_single_order(s, pool)
            if single is not None:
                key = tuple(sorted(single))
                seen.add(key)
                by_id = {o.order_id: o for o in pool}
                found.append(Candidate(s.settlement_id, key,
                                       by_id[single[0]].net, f"L2-single/r{rung}"))

            try:
                verdict, sols, exhaustive = solve(pool, s.net_paise)
            except OutOfEnvelope as exc:
                cs.note = f"out-of-envelope: {exc}"
                cs.exhaustive = False
                break

            if verdict is Verdict.CONTRADICTED and not found:
                cs.note = f"contradicted/r{rung}"
                continue  # pruned, not absent -- widen and retry

            for sol in sols:
                key = tuple(sorted(sol.order_ids))
                if key in seen:
                    continue
                seen.add(key)
                found.append(Candidate(s.settlement_id, key, sol.net_paise,
                                       f"L3-dp/r{rung}"))
            if found:
                cs.candidates = found
                cs.exhaustive = bool(exhaustive)
                cs.note = f"r{rung}"
                break
        out[s.settlement_id] = cs
    return out


# --------------------------------------------------------------------------
# Decomposition
# --------------------------------------------------------------------------


def components(cands: dict[str, CandidateSet]) -> list[list[str]]:
    """Settlements partitioned into connected components over shared orders.

    Two settlements are linked when any candidate of one shares an order with
    any candidate of the other. Selections in different components cannot
    interact, so each is an independent integer program -- which is what keeps
    an NP-hard formulation affordable. Union-find, then sorted output so the
    component list is stable across runs.
    """
    parent: dict[str, str] = {sid: sid for sid in cands}

    def find(a: str) -> str:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    owners: dict[str, str] = {}
    for sid in sorted(cands):
        for c in cands[sid].candidates:
            for oid in c.order_ids:
                if oid in owners:
                    union(owners[oid], sid)
                else:
                    owners[oid] = sid

    groups: dict[str, list[str]] = defaultdict(list)
    for sid in sorted(cands):
        groups[find(sid)].append(sid)
    return sorted(groups.values(), key=lambda g: (-len(g), g[0]))


# --------------------------------------------------------------------------
# The program
# --------------------------------------------------------------------------


@dataclass
class ComponentResult:
    settlement_ids: list[str]
    chosen: dict[str, Candidate]
    """Settlement -> candidate in the optimal packing. Optimistic: includes
    settlements whose choice was arbitrary among equal optima."""
    forced: set[str]
    """Settlements whose choice is the same in *every* optimal packing. Only
    these are sound enough to post."""
    cores: list[tuple[str, ...]]
    """Unsat cores over the 'explain everything' formulation."""
    n_candidates: int
    n_orders: int
    seconds: float = 0.0
    status: str = ""


def _build(model: cp_model.CpModel, group: list[str],
           cands: dict[str, CandidateSet],
           settle: dict[str, Settlement]) -> tuple[dict[tuple[str, int], object], dict[str, list[object]]]:
    """Booleans plus the two structural constraint families.

    `x[sid, i]` is "settlement sid is explained by its i-th candidate".
    At most one per settlement -- an alternative explanation is an alternative,
    not an addition. At most one selected candidate per order -- this is the
    disjointness that the greedy cascade enforces by consumption and that
    Hungarian cannot state at all.
    """
    x: dict[tuple[str, int], object] = {}
    per_settlement: dict[str, list[object]] = {}
    per_order: dict[str, list[object]] = defaultdict(list)

    for sid in group:
        lits = []
        for i, c in enumerate(cands[sid].candidates):
            v = model.new_bool_var(f"x[{sid},{i}]")
            x[sid, i] = v
            lits.append(v)
            for oid in c.order_ids:
                per_order[oid].append(v)
        per_settlement[sid] = lits
        if lits:
            model.add_at_most_one(lits)

    for oid in sorted(per_order):
        if len(per_order[oid]) > 1:
            model.add_at_most_one(per_order[oid])

    return x, per_settlement


def _rupees(sid: str, settle: dict[str, Settlement]) -> int:
    return settle[sid].net_paise


def solve_component(group: list[str], cands: dict[str, CandidateSet],
                    settle: dict[str, Settlement],
                    forcing: bool = True) -> ComponentResult:
    """Optimal packing for one component, then the forcing test on each pick.

    Two phases rather than one weighted objective: rupee values run to 2e7 paise
    and a lexicographic weight would need a multiplier large enough to make the
    LP relaxation numerically silly. Phase one maximises the count of explained
    settlements; phase two pins that count and maximises rupees. Both optima are
    then pinned for the forcing test, so 'forced' means forced among solutions
    the engine would actually accept as equally good.
    """
    t0 = time.perf_counter()
    n_cand = sum(len(cands[s].candidates) for s in group)
    orders = {oid for s in group for c in cands[s].candidates for oid in c.order_ids}
    res = ComponentResult(list(group), {}, set(), [], n_cand, len(orders))

    if n_cand == 0:
        res.status = "EMPTY"
        res.seconds = time.perf_counter() - t0
        return res

    model = cp_model.CpModel()
    x, per_settlement = _build(model, group, cands, settle)
    explained = [v for sid in group for v in per_settlement[sid]]
    model.maximize(sum(explained))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT_S
    solver.parameters.num_workers = 8
    solver.parameters.random_seed = 20260821
    st = solver.solve(model)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        res.status = solver.status_name(st)
        res.seconds = time.perf_counter() - t0
        return res
    best_count = int(round(solver.objective_value))

    # Phase two: same count, most rupees. Ties on count are common -- two
    # settlements can be mutually exclusive and equally numerous -- and
    # preferring the larger payout is the only tie-break with a business reason.
    model.add(sum(explained) == best_count)
    model.maximize(sum(_rupees(sid, settle) * v
                       for sid in group for v in per_settlement[sid]))
    st = solver.solve(model)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        res.status = solver.status_name(st)
        res.seconds = time.perf_counter() - t0
        return res
    best_rupees = int(round(solver.objective_value))
    res.status = solver.status_name(st)

    for sid in group:
        for i, c in enumerate(cands[sid].candidates):
            if solver.boolean_value(x[sid, i]):
                res.chosen[sid] = c

    if forcing:
        model.add(sum(_rupees(sid, settle) * v
                      for sid in group for v in per_settlement[sid]) == best_rupees)
        res.forced = _forced(model, solver, x, res.chosen, cands)

    res.seconds = time.perf_counter() - t0
    return res


def _forced(model: cp_model.CpModel, solver: cp_model.CpSolver,
            x: dict[tuple[str, int], object], chosen: dict[str, Candidate],
            cands: dict[str, CandidateSet]) -> set[str]:
    """Which picks survive being forbidden, with the optimum pinned.

    For each selected (settlement, candidate), assert that candidate false and
    ask whether any equally-optimal packing remains. Feasible means the engine
    had a genuine choice, and a choice is a guess -- so the settlement is not
    forced and will not post. Infeasible means every optimal packing agrees, and
    *that* is the property worth calling a proof.

    Done with assumptions rather than N separate models: the constraint set is
    unchanged between calls, so the solver keeps its work.
    """
    out: set[str] = set()
    for sid in sorted(chosen):
        if not cands[sid].exhaustive:
            continue  # 'no alternative' would be a claim about a sample -- D4
        idx = next(i for i, c in enumerate(cands[sid].candidates)
                   if c.order_ids == chosen[sid].order_ids)
        model.clear_assumptions()
        model.add_assumption(x[sid, idx].negated())
        st = solver.solve(model)
        if st == cp_model.INFEASIBLE:
            out.add(sid)
        # FEASIBLE -> a real alternative exists. UNKNOWN (timeout) -> we cannot
        # prove there is none, so we decline. Both cost recall, never precision.
    model.clear_assumptions()
    return out


# --------------------------------------------------------------------------
# Unsat cores
# --------------------------------------------------------------------------


def cores_for(group: list[str], cands: dict[str, CandidateSet],
              settle: dict[str, Settlement],
              max_cores: int = MAX_CORES) -> list[tuple[str, ...]]:
    """Which settlements cannot all be explained at once, and over what.

    Set packing is trivially feasible -- select nothing -- so infeasibility has
    to be *asked for*. Each settlement gets an assumption literal meaning "this
    one must be explained"; a settlement with no candidates gets a literal that
    is simply false. Handing all of them to the solver at once and reading
    `sufficient_assumptions_for_infeasibility` returns a subset that cannot hold
    together, extracted by the solver's own conflict analysis rather than
    reconstructed afterwards by a heuristic.

    The loop then forbids one member of each core already found and asks again,
    which surfaces disjoint conflicts instead of returning the same one forever.
    `max_cores` bounds what is otherwise an exponential enumeration.
    """
    model = cp_model.CpModel()
    x, per_settlement = _build(model, group, cands, settle)

    want: dict[str, object] = {}
    by_index: dict[int, str] = {}
    for sid in group:
        w = model.new_bool_var(f"want[{sid}]")
        want[sid] = w
        by_index[w.index] = sid
        lits = per_settlement[sid]
        if lits:
            model.add(sum(lits) == 1).only_enforce_if(w)
        else:
            model.add(w == 0)  # nothing to select: demanding it is immediately false

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT_S
    solver.parameters.num_workers = 8
    solver.parameters.random_seed = 20260821

    out: list[tuple[str, ...]] = []
    blocked: list[list[object]] = []
    for _ in range(max_cores):
        model.clear_assumptions()
        for sid in group:
            model.add_assumption(want[sid])
        st = solver.solve(model)
        if st != cp_model.INFEASIBLE:
            break
        idxs = solver.sufficient_assumptions_for_infeasibility()
        core = tuple(sorted({by_index[i] for i in idxs if i in by_index}))
        if not core or core in out:
            break
        out.append(core)
        # Relax: at least one member of this core must go unexplained, so the
        # next round is forced to find a *different* conflict.
        model.add(sum(want[sid] for sid in core) <= len(core) - 1)
        blocked.append([want[sid] for sid in core])
    model.clear_assumptions()
    return out


def explain_core(core: tuple[str, ...], cands: dict[str, CandidateSet]) -> tuple[str, ...]:
    """Turn a core into `Finding.unsat_core` strings: who conflicts, over what.

    A bare list of settlement ids is a conflict without a subject. The orders
    claimed by more than one member of the core are the actual contested
    resource, so they are named -- that is what makes CONTRADICTED auditable
    instead of a shrug.
    """
    claims: dict[str, set[str]] = defaultdict(set)
    for sid in core:
        for c in cands[sid].candidates:
            for oid in c.order_ids:
                claims[oid].add(sid)
    contested = sorted(oid for oid, who in claims.items() if len(who) > 1)

    lines = [f"mutually unsatisfiable: {', '.join(core)} cannot all be explained"]
    for sid in core:
        cs = cands[sid]
        if not cs.candidates:
            lines.append(f"  {sid}: no candidate subset survives blocking ({cs.note})")
        else:
            lines.append(f"  {sid}: {len(cs.candidates)} candidate subset(s), "
                         f"{'exhaustive' if cs.exhaustive else 'truncated at MAX_ENUM'}")
    if contested:
        shown = ", ".join(contested[:6])
        more = "" if len(contested) <= 6 else f" (+{len(contested) - 6} more)"
        lines.append(f"  contested orders: {shown}{more}")
    return tuple(lines)


# --------------------------------------------------------------------------
# Top level
# --------------------------------------------------------------------------


@dataclass
class PackingResult:
    findings: list[Finding]
    preds_strict: list[Prediction]
    """Posts only settlements whose candidate is forced across every optimal
    packing. This is the sound reading."""
    preds_optimistic: list[Prediction]
    """Posts whatever the optimum happened to select, including arbitrary picks
    among equal optima. Kept because measuring the unsound variant is how you
    find out what the soundness gate costs."""
    pools: dict[str, list[Order]]
    component_sizes: list[int]
    solve_times: list[float]
    core_count: int
    candidate_seconds: float = 0.0
    solve_seconds: float = 0.0

    def size_histogram(self) -> dict[str, int]:
        buckets = {"1": 0, "2": 0, "3-5": 0, "6-10": 0, "11-50": 0, "51-200": 0, "200+": 0}
        for n in self.component_sizes:
            key = ("1" if n == 1 else "2" if n == 2 else "3-5" if n <= 5
                   else "6-10" if n <= 10 else "11-50" if n <= 50
                   else "51-200" if n <= 200 else "200+")
            buckets[key] += 1
        return buckets


def _proof(s: Settlement, members: list[Order]) -> Proof:
    """Identical in effect to `pipeline._proof`. Duplicated rather than imported
    so this module can be deleted without touching the engine."""
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
        constraints={"amount": True, "window": True, "disjointness": True},
    )


def pack(settlements: list[Settlement], orders: list[Order],
         forcing: bool = True, extract_cores: bool = True) -> PackingResult:
    """L4b end to end: candidates, decompose, pack, prove forcing, name cores."""
    by_id = {o.order_id: o for o in orders}
    settle = {s.settlement_id: s for s in settlements}

    t0 = time.perf_counter()
    cands = collect(settlements, orders)
    cand_secs = time.perf_counter() - t0

    t1 = time.perf_counter()
    groups = components(cands)
    chosen: dict[str, Candidate] = {}
    forced: set[str] = set()
    core_by_sid: dict[str, tuple[str, ...]] = {}
    times: list[float] = []
    n_cores = 0

    for g in groups:
        r = solve_component(g, cands, settle, forcing=forcing)
        times.append(r.seconds)
        chosen.update(r.chosen)
        forced |= r.forced
        if extract_cores:
            for core in cores_for(g, cands, settle):
                n_cores += 1
                text = explain_core(core, cands)
                for sid in core:
                    core_by_sid.setdefault(sid, text)
    solve_secs = time.perf_counter() - t1

    findings: list[Finding] = []
    strict: list[Prediction] = []
    optimistic: list[Prediction] = []

    for s in settlements:
        sid = s.settlement_id
        cs = cands[sid]
        pick = chosen.get(sid)
        is_forced = sid in forced

        proofs = tuple(
            p for p in (_proof(s, [by_id[o] for o in c.order_ids]) for c in cs.candidates)
            if check(p, s, by_id)
        )
        if is_forced and pick is not None:
            keep = tuple(p for p in proofs if p.order_ids == pick.order_ids)
            verdict, proofs = Verdict.PROVEN, (keep or proofs[:1])
            layer = "L4b-cpsat/forced"
        elif proofs:
            verdict, layer = Verdict.AMBIGUOUS, "L4b-cpsat/unforced"
        else:
            verdict, layer = Verdict.CONTRADICTED, "L4b-cpsat/no-candidate"

        core = core_by_sid.get(sid, ())
        if verdict is Verdict.CONTRADICTED and not core:
            core = (f"no subset of any window satisfies the amount constraint ({cs.note})",)
        findings.append(Finding(sid, verdict, proofs, unsat_core=core,
                                exhaustive=cs.exhaustive, layer=layer))

        strict.append(Prediction(
            sid, list(proofs[0].order_ids) if verdict is Verdict.PROVEN else None,
            layer, reason="" if verdict is Verdict.PROVEN else verdict.value))
        optimistic.append(Prediction(
            sid, list(pick.order_ids) if pick is not None else None,
            "L4b-cpsat/optimum", reason="" if pick is not None else "DECLINED"))

    return PackingResult(
        findings=findings, preds_strict=strict, preds_optimistic=optimistic,
        pools={sid: cs.pool for sid, cs in cands.items()},
        component_sizes=[len(g) for g in groups], solve_times=times,
        core_count=n_cores, candidate_seconds=cand_secs, solve_seconds=solve_secs,
    )
