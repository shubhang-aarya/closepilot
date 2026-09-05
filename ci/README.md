# CI

`gates.yml` is a GitHub Actions workflow. It lives here rather than in
`.github/workflows/` because pushing to that path needs a token with `workflow`
scope, and this repository is pushed with one that deliberately does not have it.

To enable it:

```bash
gh auth refresh -h github.com -s workflow
mkdir -p .github/workflows && git mv ci/gates.yml .github/workflows/gates.yml
git commit -m "enable CI" && git push
```

Everything it runs is in `ci/verify.sh`, which you can run yourself:

```bash
./ci/verify.sh
```

A workflow that drifts from the local command is a workflow nobody trusts a red
build from, so there is one script and CI calls it.

## What the ten stages defend

| Stage | Defends | Fails when |
|---|---|---|
| 1 · property and invariant tests | the engine's stated properties | any invariant stops holding |
| 2 · proof integrity | that a proof is checked by code sharing nothing with the prover | a proof passes the prover and fails the kernel, or a search space loses its provenance |
| 3 · money model | integer paise end to end, rounding toward review | a deciding path computes money in floating point, or expected loss rounds toward posting |
| 4 · adapter invariants | the reader | a row is double-counted, an amount is truncated, a malformed row is swallowed, or a webhook is accepted unverified |
| 5 · AI action boundary | "AI proposes, ATTEST proves, policy decides" | a model output can reach a posting, or an agent can hold a write capability |
| 6 · claim register | that every number in README traces to an artifact | regenerating the README blocks changes them, i.e. the prose has drifted |
| 7 · benchmark artifacts | the measurements themselves | an artifact is missing or unparseable, or a claim cites one it cannot read |
| 8 · adversarial pass | the whole chain, SOURCE to LEDGER | any of 34 attacks succeeds, **or a control breaks**, **or the harness errors** |
| 9 · safety gates | the six regression gates | false proofs rise, or money wrongly auto-posted rises at all |
| 10 · browser contracts | the Case Desk | any of the 90 contracts breaks — **or fewer than 90 run** |

Stage 10's second condition is the one worth explaining. The contracts skip
themselves when `attest.web` is not listening, and pytest reports a skip as
success — so a CI job that forgot to start the server would print `90 skipped`
and go green while testing nothing. The stage starts the server and then asserts
the exact count, so a suite that quietly ran nothing fails the build.

Stage 6 has the same shape: running the claim register is not the check.
Regenerating README from the artifacts and finding it unchanged is the check,
which is why the working tree is compared afterwards rather than the tool's exit
code alone.

The workflow installs **no Rust toolchain**, on purpose. The engine has to run on
the numpy path with a narrower envelope, or the fallback is decorative.

## The protected core

`attest/verdict.py`, `model.py`, `subsetsum.py`, `blocking.py`, `layers.py`,
`pipeline.py` and `attest/generate/` decide whether money moves. A local
pre-commit hook blocks edits to them; the workflow enforces the same rule on
pull requests, where the hook cannot be bypassed.

A change there is not forbidden — it is required to be **deliberate**.

The hook's own override is `ATTEST_CORE=1 git commit`, an environment variable
at commit time, which leaves nothing behind for CI to inspect. So the workflow
checks the signal the real process actually leaves: a pull request touching the
core must also add a report in `reports/` and a test. Both core changes this
project has made — CORE-001 and CORE-002 — carry both, which is how the rule was
chosen rather than invented.

The reason for the second requirement is CORE-001 itself. `postable()` failed
open for as long as it existed, every gate held at +0.0000, and nothing anywhere
was red. A green build is not evidence that a change to the core is safe; it is
the state the core was already in while broken.

## `submission-check.py`

`verify.sh` defends the engine. `submission-check.py` defends the submission —
the two demo settlements named by id, the held-out figures quoted on screen,
both closed kernel defects, and the absence of any calibration-seed figure on a
reading surface. Run it before submitting:

```bash
./.venv/bin/python ci/submission-check.py
```

It is separate because the failures it catches are the ones the claim register
structurally cannot: a settlement id is not a percentage.
