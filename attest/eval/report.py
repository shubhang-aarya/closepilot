"""Render a run as a single self-contained HTML page.

Not a product UI. It is the engine's output artifact, the way a compiler emits a
listing — one file, no server, no framework, no build step, opens from `file://`
with the network off.

The page exists to make one thing checkable that a terminal table cannot: the
*proof*. A reader must be able to take a settlement, follow the arithmetic down
the column, and satisfy themselves that the number is right without trusting the
tool that produced it. That is the whole reason the engine emits proofs rather
than confidence scores, and a report that only showed a verdict would throw the
distinction away.

AMBIGUOUS and CONTRADICTED are styled as outcomes, not errors. No red, no warning
triangles, no apologetic language. An engine declining to guess is behaving
correctly, and a page that renders that as failure teaches the reader the wrong
thing about the system.
"""

from __future__ import annotations

import html
from collections import Counter

from attest.money import rupees as _rs
from attest.eval.harness import Report
from attest.model import Order, Settlement
from attest.verdict import Finding, Verdict

_CSS = """
:root{--bg:#fbfaf8;--panel:#fff;--ink:#16150f;--dim:#6d685c;--line:#e4e0d6;
--proven:#1f7a4d;--ambiguous:#8a6a12;--contradicted:#5a5550;--accent:#1a4f8a}
@media (prefers-color-scheme:dark){:root{--bg:#12120f;--panel:#1a1a16;--ink:#eceae2;
--dim:#9a958a;--line:#2c2b25;--proven:#5fc98e;--ambiguous:#d8ad3e;--contradicted:#8b867e;
--accent:#7cb0e8}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Inter,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:48px 24px 96px}
h1{font-size:30px;margin:0;letter-spacing:-.02em}
.sub{color:var(--dim);margin:6px 0 36px;font-size:15px}
.num{font-variant-numeric:tabular-nums;font-family:ui-monospace,"SF Mono",Menlo,monospace}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:1px;background:var(--line);border:1px solid var(--line);border-radius:10px;
overflow:hidden;margin-bottom:14px}
.stat{background:var(--panel);padding:16px 18px}
.stat .k{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim)}
.stat .v{font-size:25px;margin-top:5px;font-variant-numeric:tabular-nums;
font-family:ui-monospace,"SF Mono",Menlo,monospace}
.bar{display:flex;height:9px;border-radius:5px;overflow:hidden;margin:22px 0 8px}
.bar i{display:block}
.legend{display:flex;gap:20px;flex-wrap:wrap;color:var(--dim);font-size:13px;margin-bottom:38px}
.legend b{color:var(--ink);font-weight:600}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:7px;
vertical-align:1px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim);
margin:40px 0 12px;font-weight:600}
details{background:var(--panel);border:1px solid var(--line);border-radius:9px;
margin-bottom:7px}
summary{padding:13px 16px;cursor:pointer;display:flex;align-items:center;gap:14px;
list-style:none}
summary::-webkit-details-marker{display:none}
summary .sid{font-family:ui-monospace,Menlo,monospace;font-size:13px;color:var(--dim);
min-width:104px}
summary .amt{font-family:ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums;
margin-left:auto;font-size:14px}
.tag{font-size:11px;font-weight:700;letter-spacing:.06em;padding:3px 8px;border-radius:4px}
.body{padding:4px 16px 18px;border-top:1px solid var(--line)}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:12px}
th{text-align:left;font-weight:600;color:var(--dim);font-size:11px;
text-transform:uppercase;letter-spacing:.07em;padding:7px 8px;
border-bottom:1px solid var(--line)}
td{padding:6px 8px;border-bottom:1px solid var(--line);
font-family:ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}
td.r,th.r{text-align:right}
tr.sum td{border-top:2px solid var(--line);border-bottom:none;font-weight:700}
tr.derived td{color:var(--dim)}
.note{color:var(--dim);font-size:13px;margin:14px 0 0;line-height:1.6}
.alt{border:1px dashed var(--line);border-radius:7px;padding:11px 13px;margin-top:9px}
.alt .h{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);
margin-bottom:5px}
.ids{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--dim);
word-break:break-all;line-height:1.7}
code{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;background:var(--bg);
padding:2px 5px;border-radius:3px}
.scroll{overflow-x:auto}
footer{margin-top:64px;padding-top:20px;border-top:1px solid var(--line);
color:var(--dim);font-size:13px}
"""

_COLOUR = {Verdict.PROVEN: "var(--proven)",
           Verdict.AMBIGUOUS: "var(--ambiguous)",
           Verdict.CONTRADICTED: "var(--contradicted)"}


def _proof_table(finding: Finding, orders: dict[str, Order]) -> str:
    p = finding.proofs[0]
    rows = [
        f"<tr><td>{html.escape(oid)}</td>"
        f"<td>{html.escape(orders[oid].method.value)}</td>"
        f"<td class=r>{_rs(orders[oid].gross_paise)}</td>"
        f"<td class=r>{_rs(orders[oid].gross_paise - orders[oid].net)}</td>"
        f"<td class=r>{_rs(orders[oid].net)}</td></tr>"
        for oid in p.order_ids
    ]
    rows.append(
        f"<tr class=sum><td colspan=2>{len(p.order_ids)} orders</td>"
        f"<td class=r>{_rs(p.gross_paise)}</td><td class=r>{_rs(p.fee_paise)}</td>"
        f"<td class=r>{_rs(p.net_paise)}</td></tr>")
    rows.append(
        f"<tr class=derived><td colspan=4>residual against the bank credit</td>"
        f"<td class=r>{_rs(p.residual_paise)}</td></tr>")
    rows.append(
        f"<tr class=derived><td colspan=4>tolerance, "
        f"{len(p.order_ids)} orders × 1 paisa of rounding</td>"
        f"<td class=r>{p.tolerance_paise} paise</td></tr>")
    return ("<div class=scroll><table><tr><th>order</th><th>method</th>"
            "<th class=r>gross</th><th class=r>fee + GST</th><th class=r>net</th></tr>"
            + "".join(rows) + "</table></div>")


def _detail(f: Finding, s: Settlement, orders: dict[str, Order]) -> str:
    colour = _COLOUR[f.verdict]
    head = (f"<summary><span class=sid>{html.escape(s.settlement_id)}</span>"
            f"<span class=tag style='color:{colour};border:1px solid {colour}'>"
            f"{f.verdict.value}</span>"
            f"<span class=amt>{_rs(s.net_paise)}</span></summary>")

    if f.verdict is Verdict.PROVEN:
        body = _proof_table(f, orders) + (
            "<p class=note>Every value above is recomputed from the order records by "
            "<code>verdict.check</code>, a 35-line kernel that shares no code with the "
            "solver. The proof was accepted because exactly one subset of the candidate "
            "pool satisfies the amount constraint within the rounding bound.</p>")
    elif f.verdict is Verdict.AMBIGUOUS:
        alts = "".join(
            f"<div class=alt><div class=h>explanation {i + 1} — "
            f"{len(p.order_ids)} orders, net {_rs(p.net_paise)}, "
            f"residual {_rs(p.residual_paise)}</div>"
            f"<div class=ids>{html.escape(' '.join(p.order_ids))}</div></div>"
            for i, p in enumerate(f.proofs))
        body = (alts or "<p class=note>Out of envelope — not attempted.</p>") + (
            "<p class=note>More than one subset satisfies every constraint exactly. "
            "Arithmetic cannot choose between them, so the engine reports the field "
            "rather than picking one. Resolving this needs evidence beyond the amount — "
            "a reference, a counterparty — not a better search.</p>")
    else:
        core = "".join(f"<li>{html.escape(c)}</li>" for c in f.unsat_core)
        body = (f"<ul class=note>{core}</ul>"
                "<p class=note>No subset of any candidate window satisfies the amount "
                "constraint. The engine reports which constraint fails rather than "
                "forcing a plausible answer.</p>")

    return f"<details>{head}<div class=body>{body}</div></details>"


def render(rep: Report, findings: list[Finding], settlements: list[Settlement],
           orders: list[Order], seed: int) -> str:
    by_id = {o.order_id: o for o in orders}
    st_by_id = {s.settlement_id: s for s in settlements}
    counts = Counter(f.verdict for f in findings)
    total = max(len(findings), 1)

    bar = "".join(
        f"<i style='width:{counts[v] / total:.4%};background:{_COLOUR[v]}'></i>"
        for v in (Verdict.PROVEN, Verdict.AMBIGUOUS, Verdict.CONTRADICTED))
    legend = "".join(
        f"<span><i class=dot style='background:{_COLOUR[v]}'></i>"
        f"<b>{counts[v]}</b> {v.value.lower()}</span>"
        for v in (Verdict.PROVEN, Verdict.AMBIGUOUS, Verdict.CONTRADICTED))

    # Money first. A settlement is not worth its row count, and a finance page
    # that leads with percentages is answering a question nobody asked.
    money = {v: 0 for v in Verdict}
    for f in findings:
        money[f.verdict] += st_by_id[f.settlement_id].net_paise

    stats = "".join(f"<div class=stat><div class=k>{k}</div>"
                    f"<div class=v{c}>{v}</div></div>"
                    for k, v, c in [
                        ("processed", _rs(rep.rupees_total), ""),
                        ("auto-reconciled", _rs(money[Verdict.PROVEN]),
                         " style='color:var(--proven)'"),
                        ("needs review", _rs(money[Verdict.AMBIGUOUS]),
                         " style='color:var(--ambiguous)'"),
                        ("unexplained", _rs(money[Verdict.CONTRADICTED]),
                         " style='color:var(--contradicted)'"),
                        ("false proofs", f"{rep.wrong}", ""),
                        ("wall clock", f"{rep.seconds:.2f}s", ""),
                    ])

    order = {Verdict.PROVEN: 0, Verdict.AMBIGUOUS: 1, Verdict.CONTRADICTED: 2}
    shown = sorted(findings, key=lambda f: (order[f.verdict],
                                            -st_by_id[f.settlement_id].net_paise))[:60]
    cards = "".join(_detail(f, st_by_id[f.settlement_id], by_id) for f in shown)

    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>ATTEST — run report</title><style>{_CSS}</style></head><body><div class=wrap>
<h1>ATTEST</h1>
<p class=sub>Settlement reconciliation as constrained optimization ·
seed {seed} · {rep.n_settlements:,} settlements</p>
<div class=stats>{stats}</div>
<div class=bar>{bar}</div><div class=legend>{legend}</div>
<h2>Settlements</h2>{cards}
<footer>Every proof shown is recomputed from source records by
<code>verdict.check</code> — 35 lines, sharing no code with the solver that
produced it. A bug in the prover can cost recall; it cannot post a wrong entry.
<br>Showing {len(shown)} of {rep.n_settlements:,}.</footer>
</div></body></html>"""
