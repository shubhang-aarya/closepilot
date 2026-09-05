"""Tests for the L4b CP-SAT set packing in `attest/partition.py`.

Written against the three properties the module has to get right, because they
are the three that decide whether it may move money:

1. **Disjointness.** Two settlements whose only explanation is the same order
   cannot both be explained. The packing must pick one.
2. **Cores.** When coverage is demanded and cannot be delivered, the solver must
   name the settlements in conflict and the order they are fighting over --
   CONTRADICTED as a diagnosis rather than a shrug.
3. **Forcing.** A settlement whose candidate is merely *selected* must not post.
   Only a candidate that is the same in every optimal packing may. That is the
   FAILURES.md D4 line, and it is the only thing standing between this module
   and a false auto-post.

Fixtures are hand-built rather than generated: the generator's portfolios are
the right instrument for measuring accuracy and the wrong one for pinning down
a two-settlement conflict, where the whole point is that every order in the
instance is accounted for by hand.

Run with:  ./.venv/bin/python -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest
from datetime import date

import pytest

# ortools is not a dependency of the package: the engine does not require it,
# and the L4b packing it backs is a REJECTED implementation kept as evidence
# (FAILURES.md D12). Imported at module scope it turned a missing optional
# dependency into a COLLECTION ERROR, which aborts the whole run — a clean
# checkout following docs/REPRODUCE.md got "1 error" where the document
# promises "157 passed, 1 skipped". An optional dependency should skip.
pytest.importorskip("ortools", reason="ortools is optional; pip install ortools")

from attest.blocking import PoolIndex
from attest.model import Method, Order, Settlement
from attest.partition import (
    collect,
    components,
    cores_for,
    explain_core,
    pack,
    solve_component,
)
from attest.subsetsum import MAX_ENUM
from attest.verdict import Verdict

#: 2026-05-04 is a Monday and 2026-05-06 the Wednesday two business days later,
#: so every fixture order sits in the *tightest* rung of the ladder. Escalation
#: is a property of `blocking.py` and is tested there; letting it fire here
#: would mean these tests were quietly measuring a different pool than intended.
CAPTURED = date(2026, 5, 4)
SETTLED = date(2026, 5, 6)


def order(oid: str, net: int) -> Order:
    """UPI is zero-MDR, so gross == net and the fixtures read as their arithmetic."""
    return Order(oid, CAPTURED, net, Method.UPI, "Test Customer", None)


def settlement(sid: str, net: int) -> Settlement:
    return Settlement(sid, SETTLED, net, None)


def solve_one(settlements: list[Settlement], orders: list[Order]):
    """The whole module up to (not including) `pack`, for a single component."""
    cands = collect(settlements, orders)
    groups = components(cands)
    settle = {s.settlement_id: s for s in settlements}
    return cands, groups, [solve_component(g, cands, settle) for g in groups]


class TestFixtures(unittest.TestCase):
    """Guard the guards: an empty pool would make every assertion below vacuous."""

    def test_orders_are_visible_at_the_tightest_rung(self) -> None:
        pool = PoolIndex([order("ord_a", 1000)]).pool(settlement("setl_1", 1000), 0)
        self.assertEqual([o.order_id for o in pool], ["ord_a"])

    def test_upi_orders_have_net_equal_to_gross(self) -> None:
        self.assertEqual(order("ord_a", 1000).net, 1000)


class TestContestedOrder(unittest.TestCase):
    """Two settlements, one order they both need. The packing must pick one.

    `ord_a` (1000) alone explains `setl_1` (1000); `ord_a` + `ord_b` (1700)
    explains `setl_2`. Both explanations claim `ord_a`, so at most one can be
    selected -- and the greedy cascade cannot even see the choice, because it
    would have consumed `ord_a` for whichever settlement it attempted first.
    """

    def setUp(self) -> None:
        self.orders = [order("ord_a", 1000), order("ord_b", 700)]
        self.settlements = [settlement("setl_1", 1000), settlement("setl_2", 1700)]
        self.cands, self.groups, self.results = solve_one(self.settlements, self.orders)

    def test_both_settlements_land_in_one_component(self) -> None:
        self.assertEqual(self.groups, [["setl_1", "setl_2"]])

    def test_candidates_are_what_the_arithmetic_says(self) -> None:
        self.assertEqual([c.order_ids for c in self.cands["setl_1"].candidates],
                         [("ord_a",)])
        self.assertEqual([c.order_ids for c in self.cands["setl_2"].candidates],
                         [("ord_a", "ord_b")])

    def test_packing_explains_exactly_one_of_them(self) -> None:
        chosen = self.results[0].chosen
        self.assertEqual(len(chosen), 1,
                         "both explanations claim ord_a; selecting both would "
                         "spend one order twice")

    def test_the_tie_break_prefers_the_larger_payout(self) -> None:
        # Phase one leaves count=1 either way, so phase two decides: Rs 17 beats
        # Rs 10. The business reason is the only reason available.
        self.assertEqual(set(self.results[0].chosen), {"setl_2"})
        self.assertEqual(self.results[0].chosen["setl_2"].order_ids, ("ord_a", "ord_b"))

    def test_the_survivor_is_forced_and_the_loser_is_not(self) -> None:
        # Forbidding setl_2's candidate leaves only setl_1, worth less, so no
        # equally-optimal packing disagrees -- that is what makes it postable.
        self.assertEqual(self.results[0].forced, {"setl_2"})

    def test_only_the_forced_settlement_posts(self) -> None:
        res = pack(self.settlements, self.orders)
        posted = {p.settlement_id: p.order_ids for p in res.preds_strict if p.order_ids}
        self.assertEqual(posted, {"setl_2": ["ord_a", "ord_b"]})


class TestInfeasibleComponent(unittest.TestCase):
    """A component where coverage cannot be delivered, and the core that says so.

    Same shape as above: demanding that *every* settlement be explained is
    unsatisfiable because both need `ord_a`. Packing on its own is trivially
    feasible -- select nothing -- so the infeasibility has to be asked for, which
    is exactly what `cores_for` does with its assumption literals.
    """

    def setUp(self) -> None:
        self.orders = [order("ord_a", 1000), order("ord_b", 700)]
        self.settlements = [settlement("setl_1", 1000), settlement("setl_2", 1700)]
        self.cands = collect(self.settlements, self.orders)
        self.settle = {s.settlement_id: s for s in self.settlements}

    def test_a_core_comes_back_naming_both_settlements(self) -> None:
        cores = cores_for(["setl_1", "setl_2"], self.cands, self.settle)
        self.assertTrue(cores, "demanding both be explained is unsatisfiable")
        self.assertIn(("setl_1", "setl_2"), cores)

    def test_the_core_names_the_order_they_fight_over(self) -> None:
        text = explain_core(("setl_1", "setl_2"), self.cands)
        joined = "\n".join(text)
        self.assertIn("mutually unsatisfiable", joined)
        self.assertIn("setl_1", joined)
        self.assertIn("setl_2", joined)
        self.assertIn("contested orders: ord_a", joined)
        # ord_b is claimed by setl_2 alone, so it is not contested and must not
        # be named -- a core that lists uninvolved orders is not a diagnosis.
        self.assertNotIn("ord_b", joined.split("contested orders:")[1])

    def test_a_satisfiable_component_yields_no_core(self) -> None:
        orders = [order("ord_a", 1000), order("ord_b", 700)]
        settlements = [settlement("setl_1", 1000), settlement("setl_2", 700)]
        cands = collect(settlements, orders)
        settle = {s.settlement_id: s for s in settlements}
        self.assertEqual(cores_for(["setl_1", "setl_2"], cands, settle), [])

    def test_the_core_surfaces_through_pack(self) -> None:
        res = pack(self.settlements, self.orders)
        by_id = {f.settlement_id: f for f in res.findings}
        self.assertGreater(res.core_count, 0)
        self.assertTrue(any("contested orders" in line
                            for line in by_id["setl_1"].unsat_core))


class TestUnforcedDoesNotPost(unittest.TestCase):
    """The soundness gate: selected is not the same as proven.

    Two interchangeable orders of 1000 and two settlements of 1000. The optimum
    explains both -- count 2, and every assignment is worth the same rupees --
    but *which* order goes to which settlement is a coin toss. A coin toss that
    moves money is FAILURES.md D4, so neither may post.
    """

    def setUp(self) -> None:
        self.orders = [order("ord_a", 1000), order("ord_b", 1000)]
        self.settlements = [settlement("setl_1", 1000), settlement("setl_2", 1000)]
        self.cands, self.groups, self.results = solve_one(self.settlements, self.orders)

    def test_both_settlements_have_both_orders_as_candidates(self) -> None:
        for sid in ("setl_1", "setl_2"):
            self.assertEqual({c.order_ids for c in self.cands[sid].candidates},
                             {("ord_a",), ("ord_b",)})
            self.assertTrue(self.cands[sid].exhaustive)

    def test_the_optimum_selects_a_candidate_for_each(self) -> None:
        self.assertEqual(len(self.results[0].chosen), 2)

    def test_nothing_is_forced(self) -> None:
        # Swapping ord_a and ord_b is an equally optimal packing, so no pick
        # survives being forbidden.
        self.assertEqual(self.results[0].forced, set())

    def test_pack_declines_both(self) -> None:
        res = pack(self.settlements, self.orders)
        self.assertEqual([p.order_ids for p in res.preds_strict], [None, None])
        for f in res.findings:
            self.assertIs(f.verdict, Verdict.AMBIGUOUS)
            self.assertEqual(f.layer, "L4b-cpsat/unforced")

    def test_the_optimistic_reading_would_have_posted(self) -> None:
        # Not a shippable option -- this is the measurement of what the gate is
        # worth. If this ever stops differing from preds_strict, the gate has
        # been disabled and the report's numbers are meaningless.
        res = pack(self.settlements, self.orders)
        self.assertEqual(sum(1 for p in res.preds_optimistic if p.order_ids), 2)


class TestTruncatedEnumerationIsNeverForced(unittest.TestCase):
    """`MAX_ENUM` truncation must defeat forcing, whatever the packing says.

    Eight interchangeable orders of 1000 against a settlement of 4000 has
    C(8,4) = 70 explanations. L3 stops at `MAX_ENUM`, so "no alternative exists"
    would be a claim about a sample rather than about the instance -- and a
    sample is not a proof.
    """

    def setUp(self) -> None:
        self.orders = [order(f"ord_{i}", 1000) for i in range(8)]
        self.settlements = [settlement("setl_1", 4000)]
        self.cands, self.groups, self.results = solve_one(self.settlements, self.orders)

    def test_the_enumeration_is_flagged_non_exhaustive(self) -> None:
        cs = self.cands["setl_1"]
        self.assertFalse(cs.exhaustive)
        self.assertLessEqual(len(cs.candidates), MAX_ENUM)

    def test_the_optimum_still_picks_one(self) -> None:
        self.assertEqual(len(self.results[0].chosen), 1)

    def test_but_it_is_not_forced(self) -> None:
        self.assertEqual(self.results[0].forced, set())

    def test_pack_declines_it(self) -> None:
        res = pack(self.settlements, self.orders)
        self.assertIsNone(res.preds_strict[0].order_ids)
        self.assertIs(res.findings[0].verdict, Verdict.AMBIGUOUS)


class TestDecomposition(unittest.TestCase):
    """Components exist to keep an NP-hard formulation affordable; if they leak,
    the affordability argument in the report goes with them."""

    def test_settlements_sharing_no_order_are_separate_components(self) -> None:
        orders = [order("ord_a", 1000), order("ord_b", 2000)]
        settlements = [settlement("setl_1", 1000), settlement("setl_2", 2000)]
        cands = collect(settlements, orders)
        # setl_1 cannot reach ord_b -- the pool filter drops orders whose net
        # exceeds the credit -- so the two share nothing.
        self.assertEqual(components(cands), [["setl_1"], ["setl_2"]])

    def test_a_settlement_with_no_candidate_is_its_own_component(self) -> None:
        orders = [order("ord_a", 1000)]
        settlements = [settlement("setl_1", 1000), settlement("setl_2", 3333)]
        cands = collect(settlements, orders)
        self.assertEqual(cands["setl_2"].candidates, [])
        self.assertIn(["setl_2"], components(cands))

    def test_component_output_is_ordered_largest_first(self) -> None:
        orders = [order("ord_a", 1000), order("ord_b", 700), order("ord_c", 5000)]
        settlements = [settlement("setl_1", 1000), settlement("setl_2", 1700),
                       settlement("setl_3", 5000)]
        cands = collect(settlements, orders)
        sizes = [len(g) for g in components(cands)]
        self.assertEqual(sizes, sorted(sizes, reverse=True))


class TestDeterminism(unittest.TestCase):
    """`collect` sorts its pools because `blocking.py` iterates a `set[date]`.
    Without the pin no number in the report reproduces."""

    def test_pools_come_back_sorted_by_order_id(self) -> None:
        orders = [order("ord_c", 300), order("ord_a", 100), order("ord_b", 200)]
        cands = collect([settlement("setl_1", 600)], orders)
        self.assertEqual([o.order_id for o in cands["setl_1"].pool],
                         ["ord_a", "ord_b", "ord_c"])

    def test_the_forced_set_is_stable_across_repeat_solves(self) -> None:
        # CP-SAT runs eight workers, so which optimum comes back is not
        # reproducible. Which settlements are *forced* must be.
        orders = [order("ord_a", 1000), order("ord_b", 700)]
        settlements = [settlement("setl_1", 1000), settlement("setl_2", 1700)]
        seen = set()
        for _ in range(3):
            res = pack(settlements, orders, extract_cores=False)
            seen.add(tuple(sorted(p.settlement_id for p in res.preds_strict
                                  if p.order_ids)))
        self.assertEqual(len(seen), 1, f"forced set drifted across runs: {seen}")


if __name__ == "__main__":
    unittest.main()
