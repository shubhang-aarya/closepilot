# What broke

Five failures, chosen because each one changed how the system works. Every
number here is reproducible; every fix has a test that was watched to fail
first.

The reason this document exists: a system that reports only its successes has
not been tested, it has been demonstrated. What follows is the evidence that
somebody tried to break this.

---

## CORE-001 — the last gate before money moves, failing open

**What we thought.** `Finding.postable` was the final check before an entry
could be written. A PROVEN verdict plus an intact search space, and the money
could move.

**How we tested it.** Not by reading the predicate. By constructing a finding
with its search space stripped out and asking whether it could post.

**What broke.** It returned `True`. With no search space recorded there was
nothing to check, so the check passed — **a proof was postable *because* it
omitted the evidence it would have been judged on.**

**Why it mattered.** Every gate was green. All six safety gates held at
+0.0000, the full suite passed, and nothing anywhere was red. The defect had
been there for as long as the function had.

**What we changed.** `postable` now fails closed on four conditions: no search
space, no candidate universe, no solver provenance, compromised integrity.
`attest/verdict.py` is protected by a pre-commit hook, so the change was made
only after being authorised as human-owned, and it carries a report.

**Regression.** `test_core001_a_proof_without_search_space_provenance_cannot_post`
and five siblings.

**Current result.** Measured impact on legitimate proofs: **none.** 52 postable
before, 52 after, six gates +0.0000. Reproduction in
`reports/CORE-001-postable-fails-open.md`.

---

## CORE-002 — counting is not belonging

**What we thought.** CORE-001 was fixed. `postable` now verified that the proof
belonged to the search space it was proved against.

**How we tested it.** One deliberate membership attack: a forged proof citing
`("X", "Y")` — two order ids that exist nowhere — against a real space of five
candidates.

**What broke.** It passed. Condition 4 compared the **size** of the cited proof
against the **size** of the candidate universe. Two is less than five, so the
forgery satisfied it.

**Why it mattered.** This is the same shape of error as the failure the whole
product is built around — a property that holds in a restricted sense and is
reported as though it held generally. We had just fixed one instance of it and
written another one three lines below.

**What we changed.** `SearchSpace` now records `members`, populated at the single
construction site in `blocking.py`, and the check is `set(proof.order_ids) ⊆
space.members`.

**Regression.** `test_core002_cited_orders_must_belong_to_the_candidate_universe`
and three siblings.

**Current result.** Fixed, six gates +0.0000. Reproduction in
`reports/CORE-002-cardinality-not-membership.md`.

---

## D22 — the AI was arguing with itself, and the number that disabled it was measured under the argument

**What we thought.** The hypothesis loop had been measured at 0.429 precision
and shipped disabled on that basis.

**How we tested it.** Building the Investigate lens meant running the loop live
and printing every step, rather than reporting an aggregate.

**What broke.** The model proposed **the identical anchor three times in a row.**
A uniqueness refutation names no rejected orders, so it fed nothing back — the
model had no way to know its idea had already failed.

**Why it mattered.** The 0.429 was measured under a defective loop. It was a
measurement of the defect, not of the model.

**What we changed.** The refutation is now reported with the reason, and the
engine abstains explicitly rather than looping.

**Regression.** Covered indirectly by
`test_the_model_is_visually_and_semantically_separate_from_evidence`, which
asserts `non-discriminative` reaches the Evidence lens. **This entry is marked
FIXED, COVERED INDIRECTLY in the failure map** — nothing was written against the
old behaviour and watched to fail, so it does not meet the bar the other four do.

**Current result.** The loop is visible in the product, including its failure.

---

## D23 — six defects in the part with no proof obligation

**What we thought.** The adapter was straightforward. Read rows, sum them.

**How we tested it.** Ran an adversarial pass against it rather than reading it:
duplicate rows, malformed rows, fractional amounts, unsigned webhooks.

**What broke.** Six things.

```
1000 read twice                 → settlement net 2000, CONTRADICTED
int(10.5)                       → 10, money altered, nobody told
non-dict row                    → AttributeError, the whole page lost
str(None) == "None"             → every unidentified row shares one identity
if self.secret and not verify() → no secret means nothing is verified
json.loads(bad_body)            → raises past the boundary meant to stop it
```

**Why it mattered.** An independent kernel checks every proof. **Nothing checks
that the numbers the prover was handed are the numbers Razorpay sent.** The
adapter is the only part of the system with no proof obligation, so it is
exactly where a silent error survives.

The fourth one is the one worth keeping. Deduplication fell back through
identity fields using a conditional wrapped in `str()`. `str(None)` is `"None"`
— a perfectly truthy string — so every row lacking a `payment_id` was given the
same identity and collapsed into one record. **The fix for double-counting had
become a cause of under-counting,** which is strictly worse: an inflated
settlement contradicts and gets looked at, a deflated one balances and does not.

**What we changed.** Identity read per record type and never fabricated;
`parse_amount` reading exactly or refusing; explicit `Rejection` records;
webhooks failing closed.

**Regression.** 50 tests in `tests/test_adapter.py`.

**Current result.** All six fixed. Six gates +0.0000 — which is the *result*
here: these are reader bugs, so a moved verdict would have meant a fix reached
somewhere it had no business reaching.

---

## D24 — the reproduction we had written but never performed

**What we thought.** The project was reproducible. `docs/REPRODUCE.md` said so.

**How we tested it.** Cloned into an empty directory and ran the documented
commands instead of reading them.

**What broke.** Three steps.

```
$ pip install -e .
  error: Multiple top-level packages discovered in a flat-layout

$ pytest tests/ -q
  TypeError: dataclass() got an unexpected keyword argument 'slots'
```

The second is **D1, verbatim** — a failure this project had logged as fixed
eleven months earlier. The failure map recorded its defence as "the interpreter
check in docs/REPRODUCE.md", and `docs/REPRODUCE.md` **did not exist.**

The third: `attest.eval.gate` — the thing that exists to *check* — rewrote
`benchmark/results.json` on every run, and that artifact generates README's
figures. Running the gates republished the headline numbers as a side effect.
On a machine with no Rust toolchain that would have moved "value accounted for"
from 66.7% to 23.6% with nobody asking.

**Why it mattered.** None of the three was visible from inside the development
environment, and for the same reason each time: that environment was configured
before the conditions that break them existed.

**What we changed.** Package discovery declared; an executable interpreter check
in `attest/__init__.py` (a README is not executable); gating made read-only.

**Regression.**
`test_running_the_gates_does_not_republish_the_numbers_they_check`, confirmed
red against the old behaviour.

**Current result.** A clean clone installs and runs. A later pass found a fourth:
`pytest tests/` aborted collection on a missing optional dependency where the
document promised a skip.

---

## The pattern

Four of these five were found by **running an attack, not by reading code.**
The fifth was found by performing a document instead of writing one.

CORE-001 is the one to keep in mind. Every gate was green while it was broken.
**A passing build is not evidence that the last gate before money moves is
closed** — it is the state that system was already in.
