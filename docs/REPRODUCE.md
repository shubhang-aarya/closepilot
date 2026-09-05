# Reproducing ATTEST from nothing

Every command below was run on 2026-08-22 by cloning this repository into an
empty directory and following it. Where a step failed, the failure is recorded
rather than edited out — three of them were real defects in the project, found
by this exercise and fixed. Nothing here is written from memory.

## 0. What you need

| | |
|---|---|
| **Python 3.11+** | 3.13 is what CI pins and what these numbers were measured on |
| **git** | |
| *optional* — Node + Playwright | only for the 133 browser contracts |
| *optional* — a Rust toolchain | only to build the native kernel; **the engine runs without it**, and the numbers differ — see "Two execution paths" |

**Do not use `python3` on macOS.** It is 3.9, and this project needs 3.11+.
Name the version explicitly:

```bash
python3.13 -m venv .venv
```

If you skip that, `import attest` now stops with an explanation. It used to stop
with `TypeError: dataclass() got an unexpected keyword argument 'slots'` from
`attest/model.py`, which points at the wrong thing entirely — that is
`FAILURES.md` D1, and it was still reproducible on a clean clone until this
document was written.

## 1. Clone and install

```bash
git clone https://github.com/kunalKumar-13/attest.git
cd attest
python3.13 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -e .
./.venv/bin/pip install pytest
```

`pip install -e .` failed on a clean checkout until 2026-08-22 —
setuptools found `eval/`, `native/`, `reports/` and `contracts/` beside
`attest/` and refused flat-layout auto-discovery. Fixed by naming the packages
in `pyproject.toml`. The development venv predated those directories, so nothing
in the project had ever noticed.

## 2. Run the tests

```bash
./.venv/bin/python -m pytest tests/ -q
```

Three outcomes, all measured on a fresh clone:

| environment | result |
|---|---|
| Playwright and `ortools` installed, `attest.web` running | **297 passed** |
| Playwright installed, server not running, no `ortools` | **138 passed, 134 skipped** |

Measured on a fresh extraction, not remembered. The 133 browser contracts skip
themselves when nothing is listening on `:8420`. Without Playwright the whole
module skips as one, so the count of what did not run is *invisible* — which is
why `ci/verify.sh` asserts that the number which RAN equals the number DEFINED
in the file rather than trusting a green exit code. It counts them from the
source; a literal there went stale the first time a contract was added, and a
stale literal fails a green suite.

`tests/test_partition.py` needs `ortools`, which is not a dependency of the
package because the engine does not require it. Without it that module skips
too:

```bash
./.venv/bin/pip install ortools
```

## 3. Run the safety gates

```bash
./.venv/bin/python -m attest.eval.gate 250
```

Six gates, pooled over the two held-out evaluation seeds. It exits non-zero if
safety regressed. **This is read-only** — it compares against
`benchmark/baseline.json` and changes nothing.

It did not used to be. A plain gate run rewrote `benchmark/results.json`, which
is what generates README's figures, so *checking* the gates republished the
headline numbers as a side effect. On a machine without the Rust extension that
meant silently rewriting them to the numpy path's smaller values. Fixed;
regression: `test_running_the_gates_does_not_republish_the_numbers_they_check`.

To deliberately refresh the published numbers:

```bash
./.venv/bin/python -m attest.eval.gate 250 --update   # then commit the artifacts
```

## 4. Run the adversarial pass

```bash
./.venv/bin/python -m attest.eval.adversarial
```

35 attacks from SOURCE to LEDGER. Exits non-zero on a breach, a broken control,
or a harness error. See `docs/ADVERSARIAL.md`.

## 5. Check the claim register

```bash
./.venv/bin/python -m attest.eval.claims
```

Every percentage in README must trace to a registered claim reading a named
artifact. This one **does write** — it regenerates the README blocks from the
artifacts, and the real check is that regenerating changes nothing:

```bash
git diff --quiet -- README.md docs/CLAIMS.md && echo "no drift"
```

## 6. Launch the Case Desk

```bash
./.venv/bin/python -m attest.web
```

Opens `http://localhost:8420/`. One subject, seven lenses, three axes.

## 7. Run the browser contracts

Needs the server from step 6 already running, in another terminal:

```bash
./.venv/bin/pip install playwright
./.venv/bin/python -m playwright install chromium
./.venv/bin/python -m pytest tests/test_shell_contract.py -q
```

Expect **133 passed**. If you see them skipped, the server is not running — and a
skip is not a pass, which is why `ci/verify.sh` asserts the count rather than
the exit code.

## 8. Everything at once

```bash
./ci/verify.sh
```

Ten stages, the same ones CI runs. It starts and stops the server itself.

---

## Two execution paths, and why the numbers differ

The engine runs on **numpy** by default and on a **Rust kernel** if
`attest_native` is importable. The Rust path is not a speed optimisation with
identical output — it has a wider envelope, so it resolves cases the numpy path
declines:

| pooled, 2 held-out seeds × 250 | native | numpy |
|---|---|---|
| value accounted for | 66.7% | 23.6% |
| exact set recovery | 16.0% | 15.4% |
| coverage | 16.8% | 16.2% |
| proof precision | 95.2% | 95.1% |
| false-proof rate | 0.8% | 0.8% |
| safe resolution rate | 2.2% | 1.6% |

**The committed artifacts are the native path.** The numpy column was measured
on the clean clone described above, by reading the `benchmark/results.json` that
a gate run there produced.

The safety gates hold on both, which is the point of running CI without a Rust
toolchain. Look at which rows move: value accounted for falls by two thirds and
safe resolution by a quarter, while **the false-proof rate does not move at all**
and precision moves by a tenth of a point. The numpy path resolves less and is
not less correct — coverage falling is an allowed trade, the false-proof rate
rising is not, and that asymmetry is the whole gate policy (D20).

If you reproduce the numbers on a fresh clone with no Rust toolchain, expect the
numpy column. That is not a failed reproduction, and the gate says so in words
rather than leaving you to wonder.

## What this exercise found

Running this document rather than writing it turned up three real defects:

1. **D1 was still live.** A clean clone on macOS reproduced
   `dataclass() got an unexpected keyword argument 'slots'` exactly. The failure
   map had recorded the defence as "the interpreter check in docs/REPRODUCE.md"
   — a document that did not exist. Now `attest/__init__.py` refuses with an
   explanation, which is executable where a README is not.
2. **`pip install -e .` did not work** on a clean checkout at all.
3. **The gates rewrote the numbers they check.** On a machine without Rust that
   meant a verification run silently republishing README's "value accounted for"
   from 66.7% to 23.6% — the document drift of D13, arriving through the door
   marked "verification".

None of the three was visible from inside the development environment, because
the development environment was configured before the conditions that break
them existed. That is the argument for doing this at all.
