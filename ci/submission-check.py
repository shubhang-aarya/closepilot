"""The submission verification list, run as one thing.

    ./.venv/bin/python ci/submission-check.py

Separate from `ci/verify.sh`, which defends the ENGINE. This defends the
SUBMISSION: that the two settlements the README and the demo name by id are
still the settlements they describe, that the held-out figures on screen are
the ones in the artifact, that both kernel defects stay closed, and that no
figure from a calibration seed has crept back onto a reading surface.

It exists because the claim register checks percentages, and every defect it
failed to catch was a rupee figure, a candidate count or a settlement id.
`reports/` is excluded deliberately: a defect report states what WAS true
before its fix, and rewriting those figures would destroy the only evidence
that the defect was real.
"""
import json, pathlib, subprocess, sys
from attest import api
from attest.eval.benchmark import CALIBRATION_SEEDS, EVALUATION_SEEDS, _run_seed
from attest.policy import Costs, Decision, calibrate, decide
from attest.verdict import Verdict, check
from attest.ledger import JournalEntry, post

ok = True
def say(label, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label:<52} {detail}")

print("\nHELD-OUT PANEL")
res = json.loads((pathlib.Path("benchmark/results.json")).read_text())
p = res["pooled"]
say("held-out seed panel is [555001, 999983]", res["evaluation_seeds"] == [555001, 999983])
say("calibration seeds disjoint from evaluation",
    not set(res["calibration_seeds"]) & set(res["evaluation_seeds"]))
say("review cost is Rs 250", res["costs"]["review_paise"] == 25000)
say("exact set recovery 16.0%", p["exact_set_recovery"] == 0.16, f'{p["exact_set_recovery"]:.4f}')
say("ambiguity rate 82.4%", p["ambiguity_rate"] == 0.824, f'{p["ambiguity_rate"]:.4f}')
say("proof precision 0.9524", p["proof_precision"] == 0.9524)
say("false proofs = 4", p["false_proofs"] == 4)
say("auto-posted = 33", p["auto_post"] == 33)
say("posted = Rs 2,52,431.44", p["auto_posted_paise"] == 25243144,
    f'Rs {p["auto_posted_paise"]/100:,.2f}')
say("Rs 0 wrongly auto-posted", p["incorrectly_auto_posted_paise"] == 0)

print("\n33/33 POSTINGS RE-VERIFIED AGAINST GROUND TRUTH")
cal = {s: _run_seed(s, 250) for s in CALIBRATION_SEEDS}
risk = calibrate({s: (v[0], v[1]) for s, v in cal.items()})
n_auto = n_wrong = n_kernel = 0
for seed in EVALUATION_SEEDS:
    findings, truth, st, _, _ = _run_seed(seed, 250)
    orders = None
    for f in findings:
        if f.verdict is not Verdict.PROVEN or not f.proofs: continue
        j = decide(f, st[f.settlement_id], risk, Costs())
        if j.decision is not Decision.AUTO_POST: continue
        n_auto += 1
        if set(f.proofs[0].order_ids) != truth[f.settlement_id]: n_wrong += 1
say("auto-posts across the panel", n_auto == 33, f"{n_auto}")
say("of those, WRONG against ground truth", n_wrong == 0, f"{n_wrong}")

print("\nKERNEL SAFETY")
from attest.generate.generator import build
from attest.blocking import PoolIndex
from attest.model import tolerance_paise
from attest.verdict import Proof, Finding
from attest.searchspace import SearchSpace, Reduction
from attest.policy import RiskModel
ds = build(250, seed=555001); by_id = {o.order_id: o for o in ds.orders}
idx = PoolIndex(ds.orders); truth = {t.settlement_id: set(t.order_ids) for t in ds.truth}
acc = led = tried = 0
rm = RiskModel()
for s in ds.settlements:
    pool, space = idx.audited_pool(s, 0)
    if len(pool) < 3: continue
    for k in (1, 2, 3):
        m = pool[:k]
        if set(o.order_id for o in m) == truth[s.settlement_id]: continue
        net = sum(o.net for o in m); adj = s.net_paise - net
        if adj == 0: continue
        tried += 1
        pr = Proof(s.settlement_id, tuple(o.order_id for o in m),
                   sum(o.gross_paise for o in m), sum(o.gross_paise for o in m)-net,
                   0, adj, net+adj, s.net_paise-(net+adj), tolerance_paise(len(m)), {})
        f = Finding(s.settlement_id, Verdict.PROVEN, (pr,), space=space, layer="L3-dp/r0")
        if check(pr, s, by_id): acc += 1
        rm.rates[rm.key(f)] = (1, 152)
        if isinstance(post(f, s, decide(f, s, rm, Costs()), by_id), JournalEntry): led += 1
say(f"forged adjustments the kernel accepts (of {tried})", acc == 0, f"{acc}")
say("forged proofs reaching the ledger", led == 0, f"{led}")

print("\nTHE ADVISOR CANNOT ALTER LEDGER STATE")
r = api.execute(250, 555001)
before = [(f.settlement_id, f.verdict, tuple(p.order_ids for p in f.proofs)) for f in r.findings]
loops = {sid: api.control_loop(r, sid) for sid in ("setl_000233", "setl_000225")}
after = [(f.settlement_id, f.verdict, tuple(p.order_ids for p in f.proofs)) for f in r.findings]
say("reading the loop mutates no finding", before == after)
for sid, d in loops.items():
    adv = next(x for x in d["stages"] if x["key"] == "advisor")
    say(f"{sid}: advisor names no amount",
        not any(k.endswith("_paise") for k in adv["advisor"]))
    say(f"{sid}: advisor.changed is False", adv["advisor"]["changed"] is False)
    say(f"{sid}: ledger entry iff AUTO_POST",
        bool(next(x for x in d["stages"] if x["key"]=="ledger")["lines"])
        == (d["decision"] == "AUTO_POST"))
say("provenance still reports model_version=none",
    r.provenance.to_json()["model_version"] == "none")

print("\nDEMO NUMBERS")
lp, lq = loops["setl_000233"], loops["setl_000225"]
say("PROVEN case posts", lp["verdict"] == "PROVEN" and lp["acted"] is True,
    f'Rs {lp["amount_paise"]/100:,.2f}')
say("AMBIGUOUS case does not", lq["verdict"] == "AMBIGUOUS" and lq["acted"] is False,
    f'Rs {lq["amount_paise"]/100:,.2f}')

print("\nEVERY FRONTIER ROW AGREES WITH THE ARTIFACT")
# The policy docstring publishes the automate/check trade at five prices. It
# was typed by hand once and disagreed with benchmark/results.json on every
# row -- inside the module that decides whether money moves. Re-derived here.
_pol = (pathlib.Path("attest/policy.py")).read_text()
runs = [_run_seed(s_, 250) for s_ in EVALUATION_SEEDS]
for rc, want_a, want_p in ((15000, 11, 4046420), (25000, 33, 25243144)):
    a = post = 0
    for findings, truth, st, _, _ in runs:
        for f in findings:
            if f.verdict is not Verdict.PROVEN or not f.proofs: continue
            if decide(f, st[f.settlement_id], risk,
                      Costs(review_paise=rc)).decision is Decision.AUTO_POST:
                a += 1; post += st[f.settlement_id].net_paise
    say(f"frontier at Rs {rc//100}: {want_a} auto-posted", a == want_a, f"{a}")
    say(f"frontier at Rs {rc//100}: Rs {want_p/100:,.2f} posted", post == want_p,
        f"Rs {post/100:,.2f}")
    from attest.money import rupees as _r
    say("the docstring quotes that row", _r(post).lstrip("₹") in _pol,
        _r(post))

print("\nPROVENANCE STRINGS ON READING SURFACES ARE LIVE")
# These are content hashes. They move when a deciding module moves -- CORE-004
# moved solver_version -- and a document quoting the old one is claiming a run
# that no longer exists. The claim register cannot see them: they are not
# percentages.
import re as _re
from attest.rules import DEFAULT as _RULES, dataset_version, policy_version, solver_version
_live = {"rules": _RULES.version, "policy": policy_version(Costs()),
         "solver": solver_version(), "synthetic": dataset_version(250, 555001)}
for _f in ("FREEZE.txt", "docs/GOLDEN-DATASET.md", "docs/REPRODUCE.md",
           "README.md"):
    _p = pathlib.Path(_f)
    if not _p.is_file(): continue
    _t = _p.read_text()
    for _kind, _want in _live.items():
        for _m in sorted(set(_re.findall(_kind + r"_[a-f0-9]{8,}|" + _kind + r"_n\d+_s\d+", _t))):
            say(f"{_f}: {_m}", _m == _want, "" if _m == _want else f"live is {_want}")

print("\nNO STALE CALIBRATION CLAIMS")
_raw = subprocess.run(["grep", "-rln", "setl_000089", "README.md", "docs", "run-demo"],
                      capture_output=True, text=True).stdout
bad = _raw.strip()
say("no setl_000089 on any submission surface", not bad, bad or "clean")
for tok in ("1,00,036.83", "97,759.84", "7,292.03", "2,368", "53,02,701"):
    hit = subprocess.run(["grep", "-rl", tok, "README.md", "docs", "run-demo"],
                         capture_output=True, text=True).stdout.strip()
    hit = "\n".join(l for l in hit.splitlines() if "archive" not in l and "FAILURES" not in l)
    say(f"no stale figure {tok}", not hit, hit or "clean")

print("\n" + ("ALL CHECKS PASSED" if ok else "SOMETHING FAILED"))
sys.exit(0 if ok else 1)
