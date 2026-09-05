#!/usr/bin/env bash
# Everything CI defends, runnable locally with the same command CI uses.
#
# Ten stages, each able to fail on its own, so a red build names what broke
# rather than saying "tests failed". Several stages are pytest selections that
# `pytest tests/` would also run — that is deliberate: the selection is what
# turns "a test failed" into "the AI action boundary is open".
#
# Two stages exist because the obvious check is superficial:
#
#   BROWSER CONTRACTS silently SKIP when attest.web is not listening, and a
#   skip is reported as a pass. This starts the server and then asserts that the
#   number that RAN equals the number pytest COLLECTED, so a suite that quietly
#   ran nothing fails. The expected number is never written here: a literal goes
#   stale the first time a contract is added, and a stale literal fails a green
#   suite, which teaches whoever sees it to stop believing this stage. Counting
#   `def test_` had the same fault one step removed — it misses parametrized
#   contracts, and it did, the moment one was added.
#
#   CLAIM REGISTER regenerates the README blocks from the artifacts. Running it
#   is not the check — the check is that running it changed nothing, which is
#   why the working tree is compared afterwards.

set -uo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-./.venv/bin/python}
# Collected, not grepped. `grep -c "^def test_"` counts DEFINITIONS, and a
# parametrized contract is one definition that runs several times — so the
# moment a contract gained @pytest.mark.parametrize this stage went red on a
# green suite, which is the exact failure mode the note above warns about.
# pytest's own collection is the only count that cannot drift from what runs.
CONTRACTS=$($PY -m pytest tests/test_shell_contract.py --collect-only -q 2>/dev/null \
            | tail -1 | grep -oE "^[0-9]+")
fail=0; n=0
STAGES=10

stage() {
  n=$((n+1)); printf '\n\033[1m[%d/%d] %s\033[0m\n' "$n" "$STAGES" "$1"; shift
  if "$@"; then printf '  \033[32mPASS\033[0m\n'
  else printf '  \033[31mFAIL\033[0m\n'; fail=1; fi
}

stage "PROPERTY AND INVARIANT TESTS" \
  $PY -m pytest tests/test_invariants.py tests/test_partition.py -q

stage "PROOF INTEGRITY — every proof survives a kernel that shares no code with the prover" \
  $PY -m pytest tests/test_invariants.py -q -k \
  "kernel or search_space or compromised or local_uniqueness or reductions or core001 or core002"

stage "MONEY MODEL — integer paise everywhere, rounding toward review" \
  $PY -m pytest tests/test_invariants.py tests/test_adapter.py -q -k \
  "money or paise or floating_point or rounds_toward or tolerance or 002_"

stage "ADAPTER INVARIANTS — identity, exactness, explicit rejection, fail-closed webhooks" \
  $PY -m pytest tests/test_adapter.py -q

stage "AI ACTION BOUNDARY — no model output can reach a posting" \
  $PY -m pytest tests/test_invariants.py -q -k \
  "agent or model_output or model_verdict or hypothesis_loop or capability"

stage "CLAIM REGISTER — every README number traces to an artifact, and nothing drifted" \
  bash -c "$PY -m attest.eval.claims > /dev/null && git diff --quiet -- README.md docs/CLAIMS.md"

stage "BENCHMARK ARTIFACTS — present, parseable, and read by the claims that cite them" \
  bash -c "$PY -c \"
import json, pathlib, sys
need = ['results.json', 'baselines.json', 'anchoring.json', 'baseline.json']
for f in need:
    p = pathlib.Path('benchmark') / f
    if not p.is_file():
        sys.exit(f'missing artifact: {p}')
    json.loads(p.read_text())
print(f'{len(need)} artifacts parse')
\" && $PY -m pytest tests/test_invariants.py -q -k 'claim or readme or panel'"

stage "ADVERSARIAL PASS — 34 attacks from SOURCE to LEDGER" \
  $PY -m attest.eval.adversarial

stage "SAFETY GATES — money wrongly auto-posted may not rise at all" \
  $PY -m attest.eval.gate 250

# --- browser contracts, with the skip trap closed --------------------------
printf '\n\033[1m[10/10] BROWSER CONTRACTS — %d, against a real page\033[0m\n' "$CONTRACTS"
$PY -m attest.web > /tmp/attest-ci-web.log 2>&1 &
web=$!
for _ in $(seq 1 30); do
  curl -sf -o /dev/null http://localhost:8420/api/observatory && break || sleep 1
done
out=$($PY -m pytest tests/test_shell_contract.py -q 2>&1 | tail -3)
kill $web 2>/dev/null; wait $web 2>/dev/null
echo "$out" | sed 's/^/  /'
if echo "$out" | grep -qE "^${CONTRACTS} passed"; then
  printf '  \033[32mPASS\033[0m\n'
else
  printf '  \033[31mFAIL\033[0m — expected exactly %d contracts to RUN.\n' "$CONTRACTS"
  printf '  A skip here is not a pass: the contracts skip themselves when\n'
  printf '  attest.web is not listening, so "0 passed" would otherwise be green.\n'
  fail=1
fi

printf '\n%s\n' "=============================================================="
[ $fail -eq 0 ] && printf '  \033[32mAll ten stages held.\033[0m\n' \
               || printf '  \033[31mAt least one stage failed.\033[0m\n'
printf '%s\n' "=============================================================="
exit $fail
