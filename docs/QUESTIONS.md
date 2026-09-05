# Judge questions

Twenty-four questions, ordered roughly by how likely they are and how much
damage a bad answer does. Every answer names where it is proved. Answers are
written to be said aloud in under twenty seconds.

---

**1. Why not just use exact-only? It has a 0.0% false-proof rate.**
It does, and we print that next to our own number. It decides 22 of 500; we
decide 84. The question is not who is safest — it is who is safest *per case
decided*, and neither of us is useful without the other number beside it.
→ benchmark strip · `benchmark/baselines.json`

**2. Why not let the LLM decide?**
Because we measured it. Across the evaluation panel there were 1,020 ambiguous
cases; the anchoring loop offered an answer on 63 of them and was right on 27.
It is silent on 94% of the work it exists for, and on 53% of candidate pools its
lens is true of every order in the pool — so the anchor is an arbitrary pick
wearing a rationale. A component that absent cannot be allowed to move money.
(At n=63 its 42.9% is not distinguishable from chance either way, which is why
we quote the silence, not the precision.)
→ §05 the model · `benchmark/anchoring.json`

**3. Then why have AI at all?**
It proposes hypotheses a deterministic solver then tests. That is genuinely
useful and costs nothing, because its output is recorded as evidence and
discarded. The alternative — no proposal step — would not be safer, just
emptier.
→ §05, the actor chain

**4. Why is 42.9% acceptable?**
It is not acceptable as a decider, which is why it is not one. It is
acceptable as a proposer, because the solver rejects a bad proposal at zero
cost. The number is on screen precisely so nobody has to take our word for
what it is allowed to do.

**5. Is this actually connected to Razorpay?**
Through a read-only adapter, not a live account. That is stated on the product
itself and never softened. The architectural point is the opposite of an
integration boast: 21 of 21 modules that produce a verdict contain no reference
to the provider.
→ §10 trust, the adapter chain · `docs/RAZORPAY-INTEGRATION.md`

**6. So the Razorpay part is fake?**
The adapter is real and read-only; what is *not* claimed is live account
validation. We could have pointed it at a test account and called it live. We
did not, because a false-proof rate is only knowable against ground truth.

**7. Why synthetic data?**
Because the headline metric is *how often the system is confidently wrong*, and
you cannot compute that without knowing the right answer. Synthetic ground
truth is the requirement, not a shortcut. Track 04 asks for synthetic data.
→ `docs/GOLDEN-DATASET.md`

**8. Why do 250 and 500 both appear?**
250 is today's live run, seed 555001. 500 is the held-out evaluation panel:
two seeds of 250, neither of them calibrated on — and the live run is one of
them. The demo is a sample of the evaluation, not a separate favourable run.
Both are labelled above the comparison table.
→ benchmark strip · a contract verifies the live seed was held out from calibration

**9. What does "match rate" mean here?**
The share of the batch for which a unique explanation was established and
independently re-derived — 52 of 250, 20.8%. Not "found a plausible match":
*proved*, by a checker that does not import the solver.

**10. Can this move money?**
It writes balanced journal entries when policy permits. In this run that was
one settlement, ₹353.73, and zero wrongly auto-posted. Everything else was
refused.
→ §07 the books · `attest/ledger.py`

**11. What happens when the evidence is ambiguous?**
The engine abstains, the verdict is unchanged, no entry is written, and the
product states which evidence would settle it. Ambiguity is a result, not a
failure to produce one.

**12. Why is refusal a feature and not a limitation?**
Because the expensive error in reconciliation is not an unmatched settlement —
it is a *confident wrong* posting, which discharges a receivable against the
wrong customer while the books still balance. Refusing is the cheaper error.

**13. What prevents a forged proof?**
Two things. A 35-line checker that re-derives every proof and does not import
the solver, so a bug in the search cannot approve its own output. And a
recorded search space: a proof citing orders outside the universe it was found
in is refused. CORE-001 was exactly that bug, found by the adversarial pass.
→ §06 the machinery · `docs/ADVERSARIAL.md` · `FAILURES.md`

**14. What if the adapter lies?**
Then the verdict is wrong and we would not know — and we say so. It is on the
"what ATTEST does not claim" list rather than defended against, because
defending against it honestly requires a second source we do not have.
→ §10 trust

**15. What if the model is wrong?**
Nothing happens. The engine never reads its conclusion. On the demo case the
model concluded AMBIGUOUS and the engine concluded AMBIGUOUS — they agree, and
that is a coincidence, not a mechanism.

**16. Isn't this just a rules engine with a dashboard?**
A rules engine produces an answer. This produces an answer *plus a claim about
whether the evidence establishes it*, and refuses to act when it does not.
That second output is the product.

**17. What is actually novel?**
Treating the verdict as a claim about evidence sufficiency rather than as an
answer — and then building the boundary that enforces it: an independent
checker, a recorded search space, a policy that prices error against review
cost, and an AI path with no route to the ledger.

**18. What does ATTEST actually automate?**
Exactly what it can prove and price. One settlement in this run. That is the
honest number and it is on the first screen.

**19. What does it deliberately not automate?**
Everything unproved — 198 exceptions — and everything proved but not worth the
risk: 51 proven settlements cost more to get wrong than to check at ₹150 a
review, so policy sent them to a human.
→ §07 the decision

**20. Where does AI enter the system?**
One place: proposing an anchor on an already-ambiguous case. It cannot enter
anywhere else, and the module list proves the engine has no path to it.

**21. Why should Razorpay care?**
Settlement reports carry no order-level reference. That ambiguity is
structural, not a data-quality bug, and it is exactly where finance automation
becomes dangerous. This is the boundary made explicit.

**22. Why should I trust your solver?**
You should not have to. That is the point of the independent checker — the
solver's answer is not accepted because the solver produced it.

**23. What is the one thing you built that matters?**
The refusal path, and the measurement that justifies it. Everything else is
supporting work.

**24. What would you do next?**
Point the adapter at a real test account and re-measure — knowing the
false-proof rate would become unknowable, which is the trade being made. And
widen the solver envelope, which currently caps at ₹2,00,000 on the native
kernel.
→ `docs/DECISIONS.md`

---

## Questions we should not be asked, because the product answers them first

*"Are these numbers real?"* — every figure is fetched at load; kill the API and
the page says it has nothing to show rather than rendering defaults.

*"What's your accuracy?"* — the product never states an accuracy without the
coverage beside it.

*"Is it production-ready?"* — nothing claims it is, anywhere.


---

# Three judges, simulated

## Judge A — Razorpay engineer, skeptical, technical

**15s** — 250 settlements, ₹53 lakh, and a match rate stated as a percentage
rather than a boast. He notices the word "synthetic" is on screen rather than
buried.
**90s** — the benchmark, and specifically that exact-only's 0.0% is printed
next to ours. That is the moment he starts reading properly instead of skimming.
**Novel** — the independent checker and the recorded search space. He has seen
matchers; he has not often seen one that treats its own output as a claim.
**Attacks** — "your solver could be wrong and your checker could share the
bug." **Answer** — it does not import the solver; the solver imports it, and
the API measures that rather than asserting it. Then CORE-001 in `FAILURES.md`:
the adversarial pass found exactly that class of bug and it is written up.
**Interview?** Yes. The tell is that we published our own worst number.

## Judge B — product / hiring, skims, does not read docs

**15s** — "it refuses to guess with money." The 52px coral line does that work.
**90s** — the 197 coral points beside one white one, and 2,328 → 23 → 4.
**Novel** — that an AI hackathon entry spends its largest type on *not* using
the AI.
**Attacks** — "is this a real product or a beautiful explanation of one?"
**Answer** — `/app` is the working instrument on the same case; the front door
is the reading. One click, same verdict, same canvas.
**Interview?** Probably — but she is the judge most at risk of stopping at
screen five, which is why the video matters more for her than for A.

## Judge C — competitor, assumes we are exaggerating

**15s** — looks for the catch. Finds "GENERATED" and "seed" on the first
screen and expects that to be the weakness.
**90s** — finds instead that it is stated as a *requirement* with a reason, and
that live validation is marked NOT VERIFIED without being asked.
**Novel** — grudgingly, the measurement of the AI path. Most entries will not
have scored their own model at all.
**Attacks** — the sharpest three: *"250 versus 500 is cherry-picking"*;
*"42.9% means your AI doesn't work"*; *"you decide 84 of 500, that is a 17%
system."*
**Answers** — the panel is labelled two seeds × 250, held out, and a contract
verifies its seeds exclude the live seed. 42.9% is exactly why it does not
decide — that is the argument, not an admission. And 84 of 500 is the honest
denominator: greedy's 462 comes with 439 wrong, which is the trade the whole
submission is about.
**Interview?** He would not want to, and would concede it should happen.

## What this changes

Nothing in the product. Judge B is the one the video exists for — she is the
most likely to stop before the AI section, and she is the one the hiring
decision runs through. The shot list front-loads the benchmark to 0:40 for
exactly that reason.
