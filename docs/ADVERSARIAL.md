# Adversarial pass — SOURCE to LEDGER

```
./.venv/bin/python -m attest.eval.adversarial
```

35 attacks against the real chain, run on every build as stage 8 of
`ci/verify.sh`. The script is the evidence: it prints what each attack did and
exits non-zero if anything breached, so an unsuccessful attack is recorded by
being re-run rather than by being written down once and trusted.

```
SOURCE → NORMALIZATION → SEARCH SPACE → MEMBERSHIP → SOLVER
       → PROOF → POLICY → ACTION → LEDGER
```

Each stage is attacked with the failure modes that apply to it: **wrong,
ambiguous, duplicated, stale, forged, incomplete, out-of-order, malformed.**

## Two rules that make the result mean something

**A harness error is not a defence.** The first version of this file counted any
raised exception as the system refusing. Four attacks came back DEFENDED on the
strength of `AttributeError: 'Pipeline' object has no attribute 'run'` — which
is the harness being wrong about the API, not the pipeline stopping anything.
An adversarial pass that scores its own bugs as wins is worse than no pass,
because it produces a page of green. Each attack now declares which exceptions
constitute a refusal; anything else is `HARNESS-ERROR`, reported separately and
counted as neither defended nor breached.

Two more attacks were refused with `unknown agent reader` — the harness had
invented an agent id. Refused for the wrong reason is not defended either.

**Every stage carries a control.** A kernel that rejects everything defends every
attack trivially, so each stage also asserts that the legitimate case still
succeeds. One control caught itself on the first run: a proof of two orders
declaring `tolerance_paise=1`, when tolerance is *k* paise for *k* orders. The
kernel was right and the control was wrong, and without the control the three
kernel attacks above it would have been meaningless green.

## What the pass found

One defect, in the refusal *reason* rather than the refusal itself.

`Finding.postable` is a single boolean guarding six conditions. Both
`ledger.post` and the agent pipeline's verification stage reported every one of
them as **"the search space is compromised"** — including a proof citing an
order that belongs to no candidate universe, where the search space is perfectly
sound. The refusal was correct; the reason sent whoever read it to inspect the
wrong thing.

Fixed by `why_not_postable` in `searchspace.py`, shared by both callers, which
names the condition that actually failed. It explains but never decides —
`postable` still decides. Regression:
`test_every_unpostable_reason_is_named_not_guessed`, which walks all six
conditions, asserts each is named, and fails if `postable` ever gains a
condition the explanation has not been taught to state. Confirmed red against
the hardcoded message before it was committed green.

That this project asserts `test_every_refusal_states_a_reason` and still shipped
a misattributed one is the point. A reason that is present but wrong passes a
test for presence.

## The attacks that changed nothing

The other 33 were defended, and the defences are load-bearing rather than
incidental:

| Stage | Refused because |
|---|---|
| SOURCE | identity is read from the source, never fabricated; a row naming itself twice is rejected; aggregation is order-independent |
| NORMALIZATION | amounts are read exactly or refused — never `int()`, `round()` or truncation; the unit is declared, not inferred |
| SEARCH SPACE | a proof without recorded provenance cannot post, and a duck-typed look-alike is not a `SearchSpace` |
| MEMBERSHIP | cited orders must *belong* to the recorded universe, not merely be fewer than it |
| SOLVER | the 35-line kernel re-derives from source records and shares no code with the prover |
| PROOF | AMBIGUOUS carrying one explanation, CONTRADICTED carrying a proof, and proofs with no solver provenance are all unpostable |
| ACTION | `POST_ENTRY` is held by no agent, so a write is refused at configuration time rather than at call time |
| LEDGER | an unbalanced entry cannot be constructed at all, and a line cannot be both a debit and a credit |
| LEDGER | a proof the independent kernel rejects is refused an entry, however intact its search provenance — CORE-004 |

The ACTION stage needed two passes to test anything real. The first attacks
requested `POST_ENTRY`, which stops at the capability gate — the strongest
possible refusal, and one that means the evidence and verification gates were
never reached. The later attacks request `RUN_SOLVER`, which the
`reconciliation` agent actually holds, so they get past capability and are
judged by the gates under test.
