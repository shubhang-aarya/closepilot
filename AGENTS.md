# Working in this repository

ATTEST is a submission for the Razorpay AI Buildathon (Track 04). It is judged on
code a human will read. Two rules follow from that and neither is negotiable.

## 1. The solver core is human-authored. Do not edit it.

```
attest/model.py        attest/verdict.py      attest/subsetsum.py
attest/blocking.py     attest/layers.py       attest/pipeline.py
attest/generate/**     (frozen — see below)
```

Found a bug in one of these? **Report it to the inbox with a reproduction.** Do
not patch it. A correctness bug caught and reported is worth more here than a
silent fix, because the fix has to be understood by the person defending it.

This is enforced, not requested. `.githooks/pre-commit` rejects any commit
touching these paths. Enable it once per clone:

```bash
git config core.hooksPath .githooks
```

## 2. `attest/generate/**` is frozen.

The hazard taxonomy and generator were written before the matcher, deliberately,
so the benchmark cannot be tuned to flatter the engine. Editing them invalidates
every number in `PRD.md`. If a hazard looks wrong, say so — do not change it.

---

## What you may own

| Contract | Owns | Read it |
|---|---|---|
| `baselines` | `eval/baselines.py` | [contracts/baselines.md](docs/contracts/baselines.md) |
| `blocking-study` | `eval/blocking_study.py` | [contracts/blocking-study.md](docs/contracts/blocking-study.md) |
| `rust` | `native/**` | [contracts/rust.md](docs/contracts/rust.md) |
| `adversary` | appends to `FAILURES.md` only | [contracts/adversary.md](docs/contracts/adversary.md) |
| `report` | `attest/eval/report.py` | [contracts/report.md](docs/contracts/report.md) |

One worker per contract. If your contract is taken, do not start a second copy.

## House style

Match `attest/model.py`. Specifically: full type annotations, `from __future__
import annotations`, integer paise never floats, and comments that say **why**
rather than restating the line. If a docstring could be generated from the
signature, delete it.

## Verifying your work

```bash
./.venv/bin/python -m attest 250        # engine must still run
./.venv/bin/python -m attest 250 --holdout   # DO NOT RUN. Reserved for D7.
```

The held-out seed is executed exactly once, at the end of the build. Running it
early destroys the only unbiased measurement in the project.

## Reporting

Every contract ends by writing its findings as markdown to the inbox. Numbers,
not adjectives. If your result is that the idea did not work, that is a result —
report it. `FAILURES.md` is a first-class output of this project.
