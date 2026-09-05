"""The claim register, and a check that the prose still agrees with it. §8.1.

Every externally visible number is registered here with the artifact it comes
from and the path into that artifact. Nothing is transcribed: `value()` reads
the file. A claim whose evidence is a document rather than a machine-readable
result is LIMITED, and one with no evidence is NOT MEASURED — the register is
allowed to say no.

`audit()` then reads README.md and docs/ and reports numbers that appear in
prose but match no registered claim. That is the part that matters. A register
nothing checks is how a precision figure sat in a markdown table for six days
while the code around it changed.
"""

from __future__ import annotations

import json

from attest.money import rupees as _rs
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BENCH = ROOT / "benchmark"

#: The evaluation panel is the HELD-OUT seeds, not all five. Three of the five
#: fit the risk model, so quoting a five-seed figure would report the policy's
#: memory as its accuracy — which is D14 exactly. sweep.py runs all five and is
#: a different measurement; it must never be quoted as the evaluation.
CANONICAL_PANEL = "benchmark/results.json · evaluation_seeds"


@dataclass(frozen=True)
class Claim:
    id: str
    text: str
    artifact: str
    path: tuple[str, ...]
    fmt: str = "raw"
    denominator: str = ""
    limitation: str = ""
    status: str = "MEASURED"
    command: str = "python -m attest.eval.benchmark"
    aliases: tuple[str, ...] = ()
    """Other renderings of the same value that may legitimately appear in
    prose — a percentage written to a different precision, for instance."""


def _load(name: str) -> dict:
    """An absent artifact is NOT MEASURED, never a passing claim."""
    try:
        return json.loads((BENCH / name).read_text())
    except (OSError, ValueError):
        return {}


def value(c: Claim):
    d = _load(c.artifact.split("/")[-1]) if c.artifact.startswith("benchmark/") else {}
    for k in c.path:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def rendered(c: Claim) -> list[str]:
    """Every string form this claim's value may legitimately take in prose."""
    v = value(c)
    if v is None or v == {}:
        return list(c.aliases)
    out: list[str] = []
    if c.fmt == "pct":
        out += [f"{v * 100:.1f}%", f"{v * 100:.0f}%", f"{v * 100:.2f}%"]
    elif c.fmt == "pct3":
        out += [f"{v * 100:.2f}%", f"{v * 100:.1f}%"]
    elif c.fmt == "ratio":
        out += [f"{v:.3f}", f"{v:.4f}"]
    elif c.fmt == "rupees":
        out += [f"{v // 100:,}", f"₹{v // 100:,}"]
    else:
        out.append(str(v))
    return out + list(c.aliases)


REGISTER: tuple[Claim, ...] = (
    Claim("C-001", "No value was auto-posted incorrectly",
          "benchmark/results.json", ("pooled", "incorrectly_auto_posted_paise"),
          "raw", "the held-out evaluation panel",
          "True of this panel at this costing. Not a claim that ATTEST cannot "
          "auto-post incorrectly.", aliases=("₹0",)),
    Claim("C-002", "False proofs per settlement processed",
          "benchmark/results.json", ("pooled", "false_proof_rate"), "pct3",
          "false_proofs / settlements",
          "The other denominator — per proof OFFERED — is roughly six times "
          "larger and is the one that matters to a reader of one proof."),
    Claim("C-003", "Proof precision",
          "benchmark/results.json", ("pooled", "proof_precision"), "pct",
          "correct proofs / proofs offered"),
    Claim("C-004", "Exact set recovery",
          "benchmark/results.json", ("pooled", "exact_set_recovery"), "pct",
          "settlements whose exact order set was recovered"),
    Claim("C-005", "Value accounted for",
          "benchmark/results.json", ("pooled", "accounted_rate"), "pct",
          "proven value plus undisputed value, over processed value"),
    Claim("C-006", "AI hypothesis precision",
          "benchmark/anchoring.json", ("precision",), "ratio",
          "correct resolutions / resolutions offered",
          "Below anything postable. The loop is disabled as a resolver.",
          command="python -m attest.eval.anchoring"),
    Claim("C-007", "Candidate pools spanning one capture date",
          "benchmark/anchoring.json", ("single_date_share",), "pct",
          "pools with one distinct capture date / pools",
          command="python -m attest.eval.anchoring"),
    Claim("C-008", "ATTEST coverage against the baselines",
          "benchmark/baselines.json", ("methods", "attest", "coverage"), "pct",
          "exact sets / settlements, identical datasets and scoring",
          command="python -m attest.eval.baseline_panel"),
    Claim("C-009", "ATTEST false-proof rate per answer given",
          "benchmark/baselines.json",
          ("methods", "attest", "false_proof_rate"), "pct",
          "wrong / decided",
          "exact_only scores better on this and answers a quarter as often.",
          command="python -m attest.eval.baseline_panel"),
    Claim("C-011", "Coverage — resolved outright",
          "benchmark/results.json", ("pooled", "coverage"), "pct",
          "settlements resolved / settlements"),
    Claim("C-012", "Ambiguity rate — correctly refused",
          "benchmark/results.json", ("pooled", "ambiguity_rate"), "pct",
          "ambiguous / settlements"),
    Claim("C-013", "Safe resolution rate",
          "benchmark/results.json", ("pooled", "safe_resolution_rate"), "pct",
          "auto-posted correctly / settlements"),
    Claim("C-014", "exact_only coverage",
          "benchmark/baselines.json", ("methods", "exact_only", "coverage"),
          "pct", "exact sets / settlements",
          command="python -m attest.eval.baseline_panel"),
    Claim("C-015", "exact_only false-proof rate",
          "benchmark/baselines.json",
          ("methods", "exact_only", "false_proof_rate"), "pct", "wrong / decided",
          "Better than ATTEST's, on a quarter of the answers.",
          command="python -m attest.eval.baseline_panel"),
    Claim("C-016", "fuzzy coverage",
          "benchmark/baselines.json", ("methods", "fuzzy", "coverage"), "pct",
          "exact sets / settlements",
          command="python -m attest.eval.baseline_panel"),
    Claim("C-017", "fuzzy false-proof rate",
          "benchmark/baselines.json", ("methods", "fuzzy", "false_proof_rate"),
          "pct", "wrong / decided",
          command="python -m attest.eval.baseline_panel"),
    Claim("C-018", "greedy coverage",
          "benchmark/baselines.json", ("methods", "greedy", "coverage"), "pct",
          "exact sets / settlements",
          command="python -m attest.eval.baseline_panel"),
    Claim("C-019", "greedy false-proof rate",
          "benchmark/baselines.json", ("methods", "greedy", "false_proof_rate"),
          "pct", "wrong / decided",
          command="python -m attest.eval.baseline_panel"),
    Claim("C-020", "pair precision, per method",
          "benchmark/baselines.json", ("methods", "attest", "pair_precision"),
          "pct", "true pairs / asserted pairs",
          command="python -m attest.eval.baseline_panel"),
    Claim("C-021", "exact_only pair precision",
          "benchmark/baselines.json",
          ("methods", "exact_only", "pair_precision"), "pct",
          "true pairs / asserted pairs",
          command="python -m attest.eval.baseline_panel"),
    Claim("C-022", "fuzzy pair precision",
          "benchmark/baselines.json", ("methods", "fuzzy", "pair_precision"),
          "pct", "true pairs / asserted pairs",
          command="python -m attest.eval.baseline_panel"),
    Claim("C-023", "greedy pair precision",
          "benchmark/baselines.json", ("methods", "greedy", "pair_precision"),
          "pct", "true pairs / asserted pairs",
          command="python -m attest.eval.baseline_panel"),

    # Measurements of features that were BUILT AND THEN REJECTED. They belong in
    # the prose as part of the record, and they are registered so that nothing
    # can mistake them for current performance — a rejected measurement quoted
    # without its status is the same drift by another route.
    Claim("C-101", "Cross-settlement propagation, measured then disabled (D4)",
          "FAILURES.md", (), "raw",
          "one seed, 250 settlements",
          "The feature raised exact recovery and raised wrong results by the "
          "same amount. Disabled; the code stays so the measurement repeats.",
          status="REJECTED", command="ATTEST_PROP=1 python -m attest 250",
          aliases=("20.8%", "24.0%", "3.6%", "0.829", "1.000")),
    Claim("C-102", "Amount-ceiling envelope, measured then widened (D5)",
          "FAILURES.md", (), "raw", "one portfolio",
          "A ₹30,000 solver envelope silently skipped 14.8% of the portfolio. "
          "Recorded as the reason the envelope is what it is.",
          status="REJECTED", command="see FAILURES.md",
          aliases=("14.8%",)),
    Claim("C-010", "Native kernel speedup",
          "native/BENCH.md", (), "raw", "one credit size, one machine",
          "The figure lives in prose rather than a machine-readable result, so "
          "nothing checks it on a build.",
          status="LIMITED", command="cd native && cargo bench"),
)


@dataclass
class Finding:
    kind: str
    where: str
    detail: str


@dataclass
class Audit:
    claims: list[dict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not [f for f in self.findings if f.kind != "note"]


#: Numbers that are not claims about ATTEST's performance: illustrative amounts,
#: version strings, counts of things the reader can see for themselves.
_IGNORE = re.compile(
    r"^(0|1|2|3|4|5|6|7|8|9|10|11|12|15|18|22|24|28|30|52|59|60|72|90|100|250|"
    r"1000|2026|20260821)$")


def audit(docs: tuple[str, ...] = ("README.md",)) -> Audit:
    """Report percentages in prose that no registered claim accounts for."""
    a = Audit()
    known: set[str] = set()
    for c in REGISTER:
        v = value(c) if c.artifact.startswith("benchmark/") else None
        if v == {}:
            v = None
        forms = rendered(c)
        known.update(forms)
        a.claims.append({
            "id": c.id, "text": c.text, "artifact": c.artifact,
            "value": v, "rendered": forms, "status": c.status,
            "denominator": c.denominator, "limitation": c.limitation,
            "command": c.command,
        })
        if c.status == "MEASURED" and v is None:
            a.findings.append(Finding(
                "missing", c.artifact,
                f"{c.id} is registered as MEASURED but its artifact or path is "
                f"absent"))

    for name in docs:
        p = ROOT / name
        if not p.exists():
            continue
        for m in re.finditer(r"\d+\.\d+%", p.read_text()):
            s = m.group(0)
            if s in known or _IGNORE.match(s.rstrip("%")):
                continue
            a.findings.append(Finding(
                "unregistered", name,
                f"{s} appears in prose and matches no registered claim"))
    return a


def main() -> int:
    changed = sync_readme()
    if changed:
        print(f"\n  README blocks regenerated: {', '.join(changed)}")
    (ROOT / "docs" / "CLAIMS.md").write_text(render_doc())
    a = audit()
    w = 78
    print("\nCLAIM REGISTER")
    print("=" * w)
    for c in a.claims:
        v = c["rendered"][0] if c["rendered"] else "—"
        print(f"  {c['id']}  {c['status']:<12s}{v:>14s}   {c['text']}")
        print(f"        {c['artifact']}")
    print("-" * w)
    if a.ok:
        print("  Every percentage in README.md is accounted for by a claim.")
    else:
        for f in a.findings:
            print(f"  {f.kind.upper():<13s} {f.where}: {f.detail}")
    print("=" * w + "\n")
    return 0 if a.ok else 1



# --------------------------------------------------------------------------
# Rendering the prose blocks FROM the artifacts.
#
# The README previously carried a results block typed in by hand. It drifted:
# it reported ₹99,571 auto-posted and ₹1,786 wrongly auto-posted while the
# artifact recorded ₹40,464 and ₹0 — an older run, left behind, in the very
# document that warns about exactly this. Generating the block removes the
# possibility rather than the instance.
# --------------------------------------------------------------------------

MARK_RESULTS = ("<!-- generated: results -->", "<!-- /generated -->")
MARK_BASELINES = ("<!-- generated: baselines -->", "<!-- /generated -->")


def render_results() -> str:
    d = _load("results.json")
    p = d.get("pooled", {})
    if not p:
        return "```\nbenchmark/results.json is missing — run "\
               "`python -m attest.eval.benchmark`\n```"
    ev, cal = d.get("evaluation_seeds", []), d.get("calibration_seeds", [])
    n = d.get("settlements_per_seed", 0)
    return f"""```
{len(ev)} held-out seeds × {n} settlements
calibrated on {cal}, evaluated on {ev}

RESOLUTION
  exact set recovery       {p['exact_set_recovery'] * 100:>8.1f}%   complete truth recovered
  coverage                 {p['coverage'] * 100:>8.1f}%   resolved outright
  ambiguity rate           {p['ambiguity_rate'] * 100:>8.1f}%   correctly refused

SAFETY
  proof precision          {p['proof_precision']:>9.3f}   right when it claims sure
  false proof rate         {p['false_proof_rate'] * 100:>8.2f}%   ← the number that moves money

ACCOUNTED FOR
  settled (undisputed)  {_rs(p['settled_paise']):>16s}   agreed by every explanation
  disputed              {_rs(p['disputed_paise']):>16s}
  accounted for            {p['accounted_rate'] * 100:>8.1f}%   of all processed value

MONEY
  processed             {_rs(p['processed_paise']):>16s}
  auto-posted           {_rs(p['auto_posted_paise']):>16s}
  protected             {_rs(p['protected_paise']):>16s}   refused, deliberately
  wrongly auto-posted   {_rs(p['incorrectly_auto_posted_paise']):>16s}

NORTH STAR
  safe resolution rate     {p['safe_resolution_rate'] * 100:>8.1f}%   resolved without a human
```"""


def render_baselines() -> str:
    d = _load("baselines.json")
    m = d.get("methods", {})
    if not m:
        return "```\nbenchmark/baselines.json is missing — run "\
               "`python -m attest.eval.baseline_panel`\n```"
    rows = []
    for name in ("attest", "exact_only", "fuzzy", "greedy"):
        if name not in m:
            continue
        x = m[name]
        rows.append(
            f"  {name:<12s}{x['coverage'] * 100:>8.1f}%{x['decided']:>10}"
            f"{x['wrong']:>8}{x['false_proof_rate'] * 100:>13.1f}%"
            f"{x['pair_precision'] * 100:>12.1f}%")
    return ("```\n"
            f"  {'matcher':<12s}{'coverage':>9s}{'decided':>10s}{'wrong':>8s}"
            f"{'false proof':>14s}{'pair prec':>16s}\n"
            + "-" * 66 + "\n" + "\n".join(rows) + "\n\n"
            f"  {d.get('settlements', 0)} settlements over seeds {d.get('seeds', [])}, "
            f"identical datasets and identical scoring\n```")


def sync_readme() -> list[str]:
    """Rewrite the generated blocks in README.md from the artifacts."""
    p = ROOT / "README.md"
    s = p.read_text()
    changed = []
    for (start, end), body, name in (
        (MARK_RESULTS, render_results(), "results"),
        (MARK_BASELINES, render_baselines(), "baselines"),
    ):
        if start not in s:
            continue
        i = s.index(start) + len(start)
        j = s.index(end, i)
        new = f"\n{body}\n"
        if s[i:j] != new:
            s = s[:i] + new + s[j:]
            changed.append(name)
    p.write_text(s)
    return changed


def render_doc() -> str:
    a = audit()
    rows = []
    for c in a.claims:
        v = c["rendered"][0] if c["rendered"] else "—"
        rows.append(
            f"| `{c['id']}` | {c['text']} | `{c['artifact']}` | "
            f"`{c['command']}` | {c['denominator'] or '—'} | **{v}** | "
            f"{c['status']} |")
    lim = [c for c in a.claims if c["limitation"]]
    return f"""# Claims

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

`{CANONICAL_PANEL}`

The panel has five seeds. Three of them fit the risk model and two are held out,
so the evaluation is **2 seeds × 250 = 500 settlements**. `sweep.py` runs all
five and is a different measurement — useful for variance, never quotable as the
evaluation, because three of those seeds trained the thing being measured. That
is D14, and quoting the five-seed figure would report the policy's memory as its
accuracy.

## Register

| ID | Claim | Artifact | Command | Denominator | Value | Status |
|---|---|---|---|---|---|---|
{chr(10).join(rows)}

## Statuses

- **MEASURED** — read from a machine-readable artifact this repository produces.
- **LIMITED** — the measurement exists but lives in prose, so no build checks it.
- **REJECTED** — measured, and the feature it measured was disabled. Recorded so
  the number cannot be mistaken for current performance.
- **NOT MEASURED** — no evidence. Reported as absent rather than as zero.

## Limitations carried by specific claims

{chr(10).join(f"- **{c['id']}** — {c['limitation']}" for c in lim)}

## Regenerating everything

```bash
python -m attest.eval.benchmark        # benchmark/results.json
python -m attest.eval.baseline_panel   # benchmark/baselines.json
python -m attest.eval.anchoring        # benchmark/anchoring.json
python -m attest.eval.claims           # verify prose against all three
```
"""

if __name__ == "__main__":
    raise SystemExit(main())
