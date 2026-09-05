# Documentation

The README is the argument. These are the documents it rests on, in the order a
reviewer would want them.

## Start here

| | |
|---|---|
| **[EVALUATION.md](EVALUATION.md)** | Ground truth, the metric vocabulary, the held-out seed panel, and how coverage moves with portfolio density. The document behind every number on the front page. |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | The layers, the trusted kernel, and search-space integrity — why a correct verifier can still verify the wrong question. |
| **[ARCHITECTURE-DIAGRAM.md](ARCHITECTURE-DIAGRAM.md)** | Source to ledger in one diagram, with the advisory layer drawn outside the decision path. |
| **[../FAILURES.md](../FAILURES.md)** | Twenty-four dated failures, what each cost, and what changed because of it. |
| **[DECISIONS.md](DECISIONS.md)** | Fifteen ADRs, including the five that rejected work already built. |

## Evidence

| | |
|---|---|
| **[CLAIMS.md](CLAIMS.md)** | Every externally visible number, the artifact it is read from, the command that regenerates it, and the limitation it carries. |
| **[EVALUATION-PANEL.md](EVALUATION-PANEL.md)** | ATTEST against three reference matchers on identical data, including the one that beats it on precision. |
| **[ADVERSARIAL.md](ADVERSARIAL.md)** | Thirty-five attacks from source to ledger, the two rules that make the result mean something, and the defect they found. |
| **[FAILURE-STORY.md](FAILURE-STORY.md)** | Five failures that changed the system, with reproductions. |
| **[FAILURE-REGRESSION-MAP.md](FAILURE-REGRESSION-MAP.md)** | Every failure mapped to the test that would catch it returning — machine-checked. |
| **[GOLDEN-DATASET.md](GOLDEN-DATASET.md)** | The canonical dataset and the states it produces, case by case. |
| **[../reports/](../reports/)** | Numbered defect reports for the money-deciding core. CORE-001 and CORE-002 were found by attacking our own guarantee; CORE-003 and CORE-004 by an external red-team pass. |

## How it works

| | |
|---|---|
| **[ALGORITHMS.md](ALGORITHMS.md)** | The tolerance derivation, the counting DP, and why greedy and Hungarian both fail here. |
| **[MONEY-MODEL.md](MONEY-MODEL.md)** | Integer paise, the rounding direction, and why the tolerance is derived rather than tuned. |
| **[QUESTIONS.md](QUESTIONS.md)** | Questions a reviewer would ask, answered from artifacts rather than from memory. |

## Boundaries

| | |
|---|---|
| **[RAZORPAY-INTEGRATION.md](RAZORPAY-INTEGRATION.md)** | The capability matrix with an evidence column, and the boundaries that are frozen. |
| **[RAZORPAY-DEMO.md](RAZORPAY-DEMO.md)** | IMPLEMENTED / SIMULATED / NOT VERIFIED, capability by capability. |
| **[REPRODUCE.md](REPRODUCE.md)** | Clone to running, including the three things that did not work the first time. |

## Process

**[contracts/](contracts/)** — the division of work while this was built: which
task owned which module, and what each was forbidden to touch. Kept because the
protected-core rule in [../AGENTS.md](../AGENTS.md) is enforced by a commit
hook, and this is what it was enforcing.
