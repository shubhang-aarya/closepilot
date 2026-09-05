"""The evidence graph — §14.

A proof is a list of orders and a sum. That is checkable but not *legible*: a
human asked to believe a settlement wants to see where the money came from, and a
list of thirty-one order ids does not show that.

So the proof is also laid out as a flow. Width carries value, which makes the
composition readable without reading a single number: one order dominating a
settlement looks different from thirty even ones, and both look different from a
settlement whose fees are eating it.

Two design commitments:

**Layout is deterministic.** The same settlement draws identically every time.
A graph that reshuffles between renders cannot be reasoned about, and an
investigator comparing today against yesterday needs the shape to be stable.

**Model-asserted edges are marked in the data**, not merely coloured in a
stylesheet. A viewer must be able to ask "which of these relationships did a
model claim rather than the solver prove" and get the answer from the JSON. That
distinction is the entire thesis; hiding it in CSS would be a lie of omission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from attest.model import Order, Settlement
from attest.money import rupees
from attest.verdict import Finding, Verdict

#: Orders drawn individually before the tail is collapsed. Beyond this the flows
#: are thinner than a pixel and the picture stops being information.
MAX_LANES = 18


class NodeKind(str, Enum):
    ORDER = "order"
    REMAINDER = "remainder"
    """The collapsed tail. Carries its own count and value so the picture stays
    honest about what it is not showing."""
    FEE = "fee"
    ADJUSTMENT = "adjustment"
    SETTLEMENT = "settlement"
    BANK = "bank"


class EdgeKind(str, Enum):
    AMOUNT_MATCH = "amount_match"
    FEE_RULE = "fee_rule"
    SETTLEMENT_WINDOW = "settlement_window"
    SOLVER_VERIFIED = "solver_verified"
    EXACT_UTR = "exact_utr"
    AI_HYPOTHESIS = "ai_hypothesis"
    """Asserted by a model, not proven by the solver. Never load-bearing: an
    AI edge may suggest where to look and may never justify a posting."""


#: Which edge kinds were established deterministically. The UI reads this rather
#: than deciding for itself, so the two can never disagree.
DETERMINISTIC: frozenset[EdgeKind] = frozenset(
    {EdgeKind.AMOUNT_MATCH, EdgeKind.FEE_RULE, EdgeKind.SETTLEMENT_WINDOW,
     EdgeKind.SOLVER_VERIFIED, EdgeKind.EXACT_UTR}
)


@dataclass(frozen=True)
class Node:
    id: str
    kind: NodeKind
    label: str
    paise: int
    sub: str = ""
    x: float = 0.0
    y: float = 0.0
    h: float = 0.0


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    kind: EdgeKind
    paise: int
    why: str

    @property
    def proven(self) -> bool:
        return self.kind in DETERMINISTIC


@dataclass
class Graph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    width: float = 720.0
    height: float = 340.0

    def to_json(self) -> dict[str, object]:
        return {
            "width": self.width, "height": self.height,
            "nodes": [{"id": n.id, "kind": n.kind.value, "label": n.label,
                       "paise": n.paise, "sub": n.sub,
                       "x": round(n.x, 2), "y": round(n.y, 2), "h": round(n.h, 2)}
                      for n in self.nodes],
            "edges": [{"src": e.src, "dst": e.dst, "kind": e.kind.value,
                       "paise": e.paise, "why": e.why, "proven": e.proven}
                      for e in self.edges],
        }


def build(finding: Finding, settlement: Settlement,
          orders: dict[str, Order]) -> Graph:
    """Lay out one settlement's accepted explanation as a value flow.

    Geometry is computed here rather than in the browser so it is testable and so
    two clients cannot draw the same proof differently.
    """
    g = Graph()
    if not finding.proofs:
        return g

    p = finding.proofs[0]
    members = sorted((orders[o] for o in p.order_ids), key=lambda o: -o.net)

    lanes = members[:MAX_LANES]
    tail = members[MAX_LANES:]
    total = sum(o.net for o in members) or 1

    # Vertical space is divided by value, so a lane's height IS its contribution.
    top, usable, gap = 24.0, g.height - 48.0, 3.0
    slots = len(lanes) + (1 if tail else 0)
    avail = usable - gap * max(slots - 1, 0)

    y = top
    for o in lanes:
        h = max(avail * (o.net / total), 2.0)
        g.nodes.append(Node(o.order_id, NodeKind.ORDER, o.order_id.replace("ord_", ""),
                            o.net, o.method.value, x=0.0, y=y, h=h))
        g.edges.append(Edge(o.order_id, "settlement", EdgeKind.AMOUNT_MATCH, o.net,
                            f"net {rupees(o.net)}, captured {o.captured_on}"))
        y += h + gap

    if tail:
        tail_net = sum(o.net for o in tail)
        h = max(avail * (tail_net / total), 2.0)
        g.nodes.append(Node("remainder", NodeKind.REMAINDER,
                            f"+{len(tail)} more", tail_net,
                            "collapsed for legibility", x=0.0, y=y, h=h))
        g.edges.append(Edge("remainder", "settlement", EdgeKind.AMOUNT_MATCH,
                            tail_net, f"{len(tail)} further orders totalling "
                                      f"{rupees(tail_net)}"))

    # Fees leave the flow rather than joining it, which is why they are drawn
    # above the settlement and not beside the orders.
    if p.fee_paise:
        g.nodes.append(Node("fee", NodeKind.FEE, "fees + GST", -p.fee_paise,
                            "gateway rate by method", x=0.42, y=4.0, h=14.0))
        g.edges.append(Edge("settlement", "fee", EdgeKind.FEE_RULE, p.fee_paise,
                            "per-method basis points plus 18% GST on the fee"))

    if p.adjustment_paise:
        g.nodes.append(Node("adj", NodeKind.ADJUSTMENT, "adjustments",
                            p.adjustment_paise, "refunds and reversals",
                            x=0.42, y=g.height - 18.0, h=14.0))
        g.edges.append(Edge("adj", "settlement", EdgeKind.AMOUNT_MATCH,
                            p.adjustment_paise, "linked adjustment records"))

    g.nodes.append(Node("settlement", NodeKind.SETTLEMENT, settlement.settlement_id,
                        p.net_paise,
                        f"{len(members)} order{'' if len(members) == 1 else 's'}",
                        x=0.62, y=top, h=usable))
    g.nodes.append(Node("bank", NodeKind.BANK, "bank credit", settlement.net_paise,
                        settlement.settled_on.isoformat(), x=1.0, y=top, h=usable))

    g.edges.append(Edge(
        "settlement", "bank",
        EdgeKind.EXACT_UTR if settlement.utr else EdgeKind.AMOUNT_MATCH,
        settlement.net_paise,
        f"UTR {settlement.utr}" if settlement.utr else "amount and value date"))

    if finding.verdict is Verdict.PROVEN:
        g.edges.append(Edge("settlement", "bank", EdgeKind.SOLVER_VERIFIED,
                            settlement.net_paise,
                            f"unique subset within ±{p.tolerance_paise} paise"))

    return g
