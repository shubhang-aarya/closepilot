# Claims

Every externally visible number, the artifact it is read from, and the command
that regenerates it. Nothing here is transcribed: `attest/eval/claims.py` reads
each value from its artifact, and `python -m attest.eval.claims` fails if a
percentage appears in README.md that no claim accounts for.

That check exists because the alternative was measured. The README carried a
results block typed in by hand; it reported **₹99,571** auto-posted and
**₹1,786** wrongly auto-posted while `benchmark/results.json` recorded
**₹40,464** and **₹0** — an older run left behind, in the same document that
warns about exactly this. The block is generated now.

## The canonical evaluation panel

`benchmark/results.json · evaluation_seeds`

The panel has five seeds. Three of them fit the risk model and two are held out,
so the evaluation is **2 seeds × 250 = 500 settlements**. `sweep.py` runs all
five and is a different measurement — useful for variance, never quotable as the
evaluation, because three of those seeds trained the thing being measured. That
is D14, and quoting the five-seed figure would report the policy's memory as its
accuracy.

## Register

| ID | Claim | Artifact | Command | Denominator | Value | Status |
|---|---|---|---|---|---|---|
| `C-001` | No value was auto-posted incorrectly | `benchmark/results.json` | `python -m attest.eval.benchmark` | the held-out evaluation panel | **0** | MEASURED |
| `C-002` | False proofs per settlement processed | `benchmark/results.json` | `python -m attest.eval.benchmark` | false_proofs / settlements | **0.80%** | MEASURED |
| `C-003` | Proof precision | `benchmark/results.json` | `python -m attest.eval.benchmark` | correct proofs / proofs offered | **95.2%** | MEASURED |
| `C-004` | Exact set recovery | `benchmark/results.json` | `python -m attest.eval.benchmark` | settlements whose exact order set was recovered | **16.0%** | MEASURED |
| `C-005` | Value accounted for | `benchmark/results.json` | `python -m attest.eval.benchmark` | proven value plus undisputed value, over processed value | **68.8%** | MEASURED |
| `C-006` | AI hypothesis precision | `benchmark/anchoring.json` | `python -m attest.eval.anchoring` | correct resolutions / resolutions offered | **0.429** | MEASURED |
| `C-007` | Candidate pools spanning one capture date | `benchmark/anchoring.json` | `python -m attest.eval.anchoring` | pools with one distinct capture date / pools | **53.0%** | MEASURED |
| `C-008` | ATTEST coverage against the baselines | `benchmark/baselines.json` | `python -m attest.eval.baseline_panel` | exact sets / settlements, identical datasets and scoring | **16.0%** | MEASURED |
| `C-009` | ATTEST false-proof rate per answer given | `benchmark/baselines.json` | `python -m attest.eval.baseline_panel` | wrong / decided | **4.8%** | MEASURED |
| `C-011` | Coverage — resolved outright | `benchmark/results.json` | `python -m attest.eval.benchmark` | settlements resolved / settlements | **16.8%** | MEASURED |
| `C-012` | Ambiguity rate — correctly refused | `benchmark/results.json` | `python -m attest.eval.benchmark` | ambiguous / settlements | **82.4%** | MEASURED |
| `C-013` | Safe resolution rate | `benchmark/results.json` | `python -m attest.eval.benchmark` | auto-posted correctly / settlements | **6.6%** | MEASURED |
| `C-014` | exact_only coverage | `benchmark/baselines.json` | `python -m attest.eval.baseline_panel` | exact sets / settlements | **4.4%** | MEASURED |
| `C-015` | exact_only false-proof rate | `benchmark/baselines.json` | `python -m attest.eval.baseline_panel` | wrong / decided | **0.0%** | MEASURED |
| `C-016` | fuzzy coverage | `benchmark/baselines.json` | `python -m attest.eval.baseline_panel` | exact sets / settlements | **3.6%** | MEASURED |
| `C-017` | fuzzy false-proof rate | `benchmark/baselines.json` | `python -m attest.eval.baseline_panel` | wrong / decided | **40.0%** | MEASURED |
| `C-018` | greedy coverage | `benchmark/baselines.json` | `python -m attest.eval.baseline_panel` | exact sets / settlements | **4.6%** | MEASURED |
| `C-019` | greedy false-proof rate | `benchmark/baselines.json` | `python -m attest.eval.baseline_panel` | wrong / decided | **95.0%** | MEASURED |
| `C-020` | pair precision, per method | `benchmark/baselines.json` | `python -m attest.eval.baseline_panel` | true pairs / asserted pairs | **95.9%** | MEASURED |
| `C-021` | exact_only pair precision | `benchmark/baselines.json` | `python -m attest.eval.baseline_panel` | true pairs / asserted pairs | **100.0%** | MEASURED |
| `C-022` | fuzzy pair precision | `benchmark/baselines.json` | `python -m attest.eval.baseline_panel` | true pairs / asserted pairs | **60.0%** | MEASURED |
| `C-023` | greedy pair precision | `benchmark/baselines.json` | `python -m attest.eval.baseline_panel` | true pairs / asserted pairs | **16.5%** | MEASURED |
| `C-101` | Cross-settlement propagation, measured then disabled (D4) | `FAILURES.md` | `ATTEST_PROP=1 python -m attest 250` | one seed, 250 settlements | **20.8%** | REJECTED |
| `C-102` | Amount-ceiling envelope, measured then widened (D5) | `FAILURES.md` | `see FAILURES.md` | one portfolio | **14.8%** | REJECTED |
| `C-010` | Native kernel speedup | `native/BENCH.md` | `cd native && cargo bench` | one credit size, one machine | **—** | LIMITED |

## Statuses

- **MEASURED** — read from a machine-readable artifact this repository produces.
- **LIMITED** — the measurement exists but lives in prose, so no build checks it.
- **REJECTED** — measured, and the feature it measured was disabled. Recorded so
  the number cannot be mistaken for current performance.
- **NOT MEASURED** — no evidence. Reported as absent rather than as zero.

## Limitations carried by specific claims

- **C-001** — True of this panel at this costing. Not a claim that ATTEST cannot auto-post incorrectly.
- **C-002** — The other denominator — per proof OFFERED — is roughly six times larger and is the one that matters to a reader of one proof.
- **C-006** — Below anything postable. The loop is disabled as a resolver.
- **C-009** — exact_only scores better on this and answers a quarter as often.
- **C-015** — Better than ATTEST's, on a quarter of the answers.
- **C-101** — The feature raised exact recovery and raised wrong results by the same amount. Disabled; the code stays so the measurement repeats.
- **C-102** — A ₹30,000 solver envelope silently skipped 14.8% of the portfolio. Recorded as the reason the envelope is what it is.
- **C-010** — The figure lives in prose rather than a machine-readable result, so nothing checks it on a build.

## Regenerating everything

```bash
python -m attest.eval.benchmark        # benchmark/results.json
python -m attest.eval.baseline_panel   # benchmark/baselines.json
python -m attest.eval.anchoring        # benchmark/anchoring.json
python -m attest.eval.claims           # verify prose against all three
```
