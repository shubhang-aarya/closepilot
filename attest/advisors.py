"""A real language model in the advisory slot, and the wall it does not cross.

`attest/hypothesis.py` defines `Proposer = Callable[[Evidence], list[Hypothesis]]`
and ships `batch_proposer`, a deterministic stand-in that picks the densest
same-day capture batch. The stand-in exists so the loop can be tested and
benchmarked with no network and no key. It is not a model, and the product has
always said so: provenance stamps `model_version: none`.

This module fills the same slot with an actual model, so the claim the
architecture makes can be tested against the thing it was built to constrain
rather than against a placeholder.

**What the model is shown, and what it is not.** `Evidence` has no field that can
carry a net or a gross — the omission is structural, not an oversight. This
proposer withholds one field further: `residual_hint` is an integer in paise,
derived from amounts, and although its magnitude is a fact about the SEARCH
rather than about any candidate, sending it would make "the model never saw an
amount" a claim with a footnote. It is dropped, so the sentence is simply true.
The model sees identifiers, customer names, capture dates, a narration, and
which anchors have already been refuted.

**What the model can do with a wrong answer: nothing.** It returns order ids. An
anchor is admitted only when it is a subset of exactly one explanation the
solver already validated over the full pool (`hypothesis.falsify`), the survivor
is re-derived by the 35-line kernel, and `pipeline.py` never imports this module
or `hypothesis` at all. A hallucinated order id is refuted on existence. A
plausible but wrong anchor is refuted on uniqueness. The blast radius of a bad
proposal is a wasted search.

Failure is silence, deliberately: no key, a refused call, a malformed body or an
unparseable answer all return no hypotheses, which the loop reads as "nothing to
say" and the verdict stands. A proposer that raises could otherwise take down a
reconciliation run, and an advisor must never be able to do that.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from attest.hypothesis import Evidence, Hypothesis

ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

#: Chosen for a 131k context and for being an open-weights model, so the
#: measurement below is reproducible by someone who does not have this key.
MODEL = "openai/gpt-oss-120b"

#: Zero, because a measurement that changes between runs is not a measurement.
TEMPERATURE = 0.0

TIMEOUT_S = 45

SYSTEM = (
    "You are an investigative advisor for settlement reconciliation. A bank "
    "credit paid for some subset of a list of candidate orders. You are shown "
    "identifiers, customer names and capture dates. You are NOT shown any "
    "amount, and you cannot compute one.\n\n"
    "Name the 2-4 candidate orders you believe were settled together, and say "
    "why in one short sentence, using only what you were shown - a shared "
    "capture date, a name matching the narration, an obvious batch.\n\n"
    "You are not deciding anything. A solver has already enumerated every "
    "subset that satisfies the amount exactly; your answer is only used to "
    "break a tie between those, and it is discarded if it does not match one. "
    "If nothing in the records distinguishes any group, return an empty list - "
    "that is a useful answer, not a failure.\n\n"
    'Reply with JSON only: {"order_ids": [...], "reasoning": "..."}'
)


def _payload(ev: Evidence) -> dict:
    """Exactly what the model is shown. Note what is absent."""
    return {
        "settlement_id": ev.settlement_id,
        "value_date": str(ev.value_date),
        "utr": ev.utr,
        "narration": ev.narration,
        "candidates": [
            {"order_id": oid, "customer": name, "captured_on": str(day)}
            for oid, name, day in ev.candidates
        ],
        "already_refuted": [list(a) for a in ev.tried],
        "orders_ruled_out": list(ev.rejected),
    }


class AdvisorUnavailable(Exception):
    """The model could not be reached, or refused. NOT the same as saying nothing.

    The product treats both as silence, which is right: an advisor that is down
    must not stop a reconciliation. A MEASUREMENT must not treat them as the
    same thing, because "the model had nothing to say" and "the model was rate
    limited" produce identical empty lists and opposite conclusions. A pilot run
    here reported the model silent on 100% of cases; it was HTTP 429 on eight
    calls in a row. That number would have been a lie told in good faith.
    """


def _ask(req: urllib.request.Request) -> dict:
    """One call. Raises AdvisorUnavailable rather than returning an empty answer."""
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            answer = json.loads(r.read())["choices"][0]["message"]["content"]
        return json.loads(answer)
    except urllib.error.HTTPError as e:
        raise AdvisorUnavailable(f"HTTP {e.code}") from e
    except (urllib.error.URLError, OSError, KeyError, IndexError,
            json.JSONDecodeError, TimeoutError) as e:
        raise AdvisorUnavailable(type(e).__name__) from e


def _request(ev: Evidence, key: str) -> urllib.request.Request:
    body = json.dumps({
        "model": MODEL,
        "temperature": TEMPERATURE,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(_payload(ev))},
        ],
    }).encode()
    return urllib.request.Request(
        ENDPOINT, data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "User-Agent": "attest/0.1 (+https://github.com/kunalKumar-13/attest)"})


def _hypotheses(parsed: dict) -> list[Hypothesis]:
    ids = parsed.get("order_ids") or []
    if not isinstance(ids, list):
        return []
    seen: list[str] = []
    for i in ids:
        if isinstance(i, str) and i not in seen:
            seen.append(i)
    anchor = tuple(seen[:4])
    if len(anchor) < 2:
        return []
    why = parsed.get("reasoning")
    return [Hypothesis(
        order_ids=anchor,
        lens="model",
        reasoning=(why if isinstance(why, str) else "")[:240] or "no reason given",
        admits_missing=("no reference links these to the credit",),
    )]


def strict_proposer(retries: int = 6, backoff: float = 20.0):
    """A proposer for MEASUREMENT: retries a refusal, then gives up loudly.

    The token budget is the binding limit — roughly six of these prompts per
    minute — so a run without backoff measures the rate limiter rather than the
    model. After `retries` it raises, and the harness aborts instead of
    recording an empty answer as an opinion.
    """
    import time as _t

    def propose(ev: Evidence) -> list[Hypothesis]:
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise AdvisorUnavailable("GROQ_API_KEY is not set")
        if not ev.candidates:
            return []
        last = ""
        for attempt in range(retries):
            try:
                return _hypotheses(_ask(_request(ev, key)))
            except AdvisorUnavailable as e:
                last = str(e)
                _t.sleep(backoff * (attempt + 1))
        raise AdvisorUnavailable(f"gave up after {retries} attempts: {last}")

    return propose


def groq_proposer(ev: Evidence) -> list[Hypothesis]:
    """Ask a model which orders belong together. Never tell it what they cost."""
    key = os.environ.get("GROQ_API_KEY")
    if not key or not ev.candidates:
        return []

    req = _request(ev, key)

    try:
        parsed = _ask(req)
    except AdvisorUnavailable:
        return []                       # silence, never an exception

    return _hypotheses(parsed)
