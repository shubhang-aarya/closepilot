"""Agent permissions and the action pipeline. §41, §42, §43, §68, §69.

§43 draws this:

    Agent → Intent → Evidence → Verification → Policy → Action

A diagram is not a control. This module is that path as code, and the only way to
reach an action is through it — every stage can refuse, every refusal is recorded
with a reason, and a stage that has not run is indistinguishable from one that
refused.

The permission model is deliberately lopsided (§42). Agents get broad READ and
PROPOSE rights, because reading and proposing cannot move money and constraining
them buys nothing. Nothing gets a write capability at all:

    POST_ENTRY, TRIGGER_REFUND, MODIFY_RECORD are defined and granted to no one.

They exist as named, refusable things rather than as absences, because an
absence is silent and a refusal is auditable. When an agent asks, the log says
what it asked for and that it was denied — which is the record you want when
someone asks what the automation tried to do.

The engine posts entries. It does so after a unique explanation has been
kernel-checked and the policy has priced the risk. No agent is in that path, and
that is the point of §68: the pipeline has no bypass, so there is no
configuration in which one appears.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Capability(str, Enum):
    READ_ORDERS = "read_orders"
    READ_SETTLEMENTS = "read_settlements"
    READ_EVIDENCE = "read_evidence"
    SEARCH_EVIDENCE = "search_evidence"
    PROPOSE_HYPOTHESIS = "propose_hypothesis"
    RUN_SOLVER = "run_solver"
    CREATE_EXCEPTION = "create_exception"
    CREATE_INVESTIGATION = "create_investigation"
    EXPLAIN = "explain"
    RECOMMEND = "recommend"

    # -- defined, granted to nothing -------------------------------------
    POST_ENTRY = "post_accounting_entry"
    MARK_RECONCILED = "mark_reconciled"
    TRIGGER_REFUND = "trigger_refund"
    MODIFY_RECORD = "modify_record"


#: The capabilities no agent may hold, in any configuration. Enforced at grant
#: time, not just at call time — a permission that can be granted and then
#: refused later is a permission someone will eventually be surprised by.
NEVER_GRANTED = frozenset({
    Capability.POST_ENTRY, Capability.MARK_RECONCILED,
    Capability.TRIGGER_REFUND, Capability.MODIFY_RECORD,
})


class Stage(str, Enum):
    CAPABILITY = "capability"
    EVIDENCE = "evidence"
    VERIFICATION = "verification"
    POLICY = "policy"
    ACTION = "action"


@dataclass(frozen=True)
class Agent:
    id: str
    name: str
    purpose: str
    capabilities: frozenset[Capability]

    def __post_init__(self) -> None:
        bad = self.capabilities & NEVER_GRANTED
        if bad:
            raise PermissionError(
                f"{self.id} was configured with {sorted(c.value for c in bad)}, "
                f"which no agent may hold. Financial state is mutated by the "
                f"engine after verification and policy, never by an agent.")

    def can(self, c: Capability) -> bool:
        return c in self.capabilities

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id, "name": self.name, "purpose": self.purpose,
            "allowed": sorted(c.value for c in self.capabilities),
            "blocked": sorted(c.value for c in NEVER_GRANTED),
        }


ROSTER: dict[str, Agent] = {
    a.id: a for a in [
        Agent("reconciliation", "Reconciliation Agent",
              "Runs the engine over a portfolio and reports what it decided.",
              frozenset({Capability.READ_ORDERS, Capability.READ_SETTLEMENTS,
                         Capability.RUN_SOLVER, Capability.EXPLAIN})),
        Agent("investigation", "Investigation Agent",
              "Proposes explanations for abstentions and has them tested. Its "
              "proposals are never accepted on their own account — see D8.",
              frozenset({Capability.READ_ORDERS, Capability.READ_EVIDENCE,
                         Capability.SEARCH_EVIDENCE, Capability.PROPOSE_HYPOTHESIS,
                         Capability.RUN_SOLVER, Capability.CREATE_INVESTIGATION,
                         Capability.RECOMMEND})),
        Agent("evidence", "Evidence Agent",
              "Assembles and links records into the evidence graph.",
              frozenset({Capability.READ_ORDERS, Capability.READ_SETTLEMENTS,
                         Capability.READ_EVIDENCE, Capability.SEARCH_EVIDENCE})),
        Agent("explanation", "Explanation Agent",
              "Turns a verdict and its evidence into language a human can check.",
              frozenset({Capability.READ_EVIDENCE, Capability.EXPLAIN})),
        Agent("policy", "Policy Agent",
              "Prices risk and decides whether an action is permitted. Decides; "
              "does not act.",
              frozenset({Capability.READ_SETTLEMENTS, Capability.RECOMMEND})),
    ]
}


@dataclass
class Step:
    stage: Stage
    passed: bool
    detail: str


@dataclass
class Attempt:
    """One request through the pipeline, and everything that happened to it."""

    agent_id: str
    intent: str
    subject: str
    at: datetime
    steps: list[Step] = field(default_factory=list)

    @property
    def permitted(self) -> bool:
        return bool(self.steps) and all(s.passed for s in self.steps)

    @property
    def stopped_at(self) -> Stage | None:
        for s in self.steps:
            if not s.passed:
                return s.stage
        return None

    def to_json(self) -> dict[str, object]:
        return {
            "agent": self.agent_id, "intent": self.intent, "subject": self.subject,
            "at": self.at.isoformat(timespec="seconds"),
            "permitted": self.permitted,
            "stopped_at": self.stopped_at.value if self.stopped_at else None,
            "steps": [{"stage": s.stage.value, "passed": s.passed,
                       "detail": s.detail} for s in self.steps],
        }

    def render(self) -> str:
        mark = {True: "✓", False: "✗"}
        head = f"{self.agent_id} · {self.intent} · {self.subject}"
        body = "\n".join(f"    {mark[s.passed]} {s.stage.value:<13s} {s.detail}"
                         for s in self.steps)
        tail = ("PERMITTED" if self.permitted
                else f"REFUSED at {self.stopped_at.value}")
        return f"{head}\n{body}\n    → {tail}"


class Pipeline:
    """The only route to an action. §43, §68.

    Stages run in order and stop at the first refusal, so a later stage cannot
    excuse an earlier one — an action that failed the capability check never
    reaches the policy, and no amount of policy configuration recovers it.
    """

    def __init__(self) -> None:
        self.attempts: list[Attempt] = []

    def request(self, agent_id: str, intent: str, subject: str,
                required: Capability,
                evidence: object = None,
                finding: object = None,
                judgement: object = None) -> Attempt:
        a = Attempt(agent_id, intent, subject, datetime.now(timezone.utc))
        self.attempts.append(a)
        agent = ROSTER.get(agent_id)

        if agent is None:
            a.steps.append(Step(Stage.CAPABILITY, False, f"unknown agent {agent_id}"))
            return a
        if required in NEVER_GRANTED:
            a.steps.append(Step(
                Stage.CAPABILITY, False,
                f"{required.value} is held by no agent; financial state is "
                f"mutated by the engine after verification and policy"))
            return a
        if not agent.can(required):
            a.steps.append(Step(
                Stage.CAPABILITY, False,
                f"{agent.name} does not hold {required.value}"))
            return a
        a.steps.append(Step(Stage.CAPABILITY, True,
                            f"{agent.name} holds {required.value}"))

        if evidence is None:
            a.steps.append(Step(Stage.EVIDENCE, False,
                                "no evidence supplied; an intent without records "
                                "is a preference"))
            return a
        a.steps.append(Step(Stage.EVIDENCE, True, str(evidence)))

        from attest.searchspace import why_not_postable
        from attest.verdict import Verdict
        v = getattr(finding, "verdict", None)
        if v is None:
            a.steps.append(Step(Stage.VERIFICATION, False,
                                "nothing was verified"))
            return a
        if v is not Verdict.PROVEN:
            a.steps.append(Step(
                Stage.VERIFICATION, False,
                f"verdict is {v.value}; only a unique, kernel-checked "
                f"explanation is actionable"))
            return a
        if not getattr(finding, "postable", False):
            a.steps.append(Step(
                Stage.VERIFICATION, False,
                f"proven, but {why_not_postable(finding)}"))
            return a
        a.steps.append(Step(Stage.VERIFICATION, True,
                            "unique explanation, kernel-checked, space intact"))

        from attest.policy import Decision
        d = getattr(judgement, "decision", None)
        if d is not Decision.AUTO_POST:
            a.steps.append(Step(
                Stage.POLICY, False,
                f"policy says {d.value if d else 'nothing'}; "
                + ((judgement.reasons or ("",))[-1] if judgement else "")))
            return a
        a.steps.append(Step(Stage.POLICY, True,
                            (judgement.reasons or ("permitted",))[-1]))

        a.steps.append(Step(Stage.ACTION, True,
                            "eligible — executed by the engine, not by the agent"))
        return a
