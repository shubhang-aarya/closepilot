"""The Failure Observatory. §38.

Nineteen documented failures, surfaced in the product rather than buried in a
file nobody opens. Most engineering artefacts show what works; this one shows
what did not, what it cost, and what changed as a result — which is the only
evidence that a number was ever doubted.

**It parses FAILURES.md rather than restating it.** A second copy of this
content would drift, and the drift would be in the direction of flattery: the
entries that got embarrassing would quietly stop being copied across. The file
on disk is the record and this reads it, so the product cannot show a kinder
version of the history than the repository holds.

Parsing is deliberately shallow. It reads the heading, the first bold sentence,
and the first fenced block, and it does not attempt to understand the prose. A
parser that tried to summarise would eventually summarise wrongly, and a wrong
summary of a failure log is a particularly stupid way to lose credibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "FAILURES.md"

_HEAD = re.compile(r"^## (.+?)$", re.M)
_BOLD = re.compile(r"^\*\*(.+?)\*\*", re.M | re.S)
_FENCE = re.compile(r"```\n(.*?)```", re.S)

#: Phrases that mark an entry as a decision to NOT ship something. Counted
#: separately because "we measured it and turned it off" is a different and more
#: useful claim than "we fixed a bug".
_REFUSALS = ("shipped it disabled", "shipped disabled", "shipped it off",
             "rejected the packing", "reject the packing", "default off",
             "disabled by default", "do not ship", "shipped disabled",
             "and shipped it off", "measured and refused", "refused for the same reason")


@dataclass(frozen=True)
class Failure:
    ref: str
    title: str
    date: str
    headline: str
    detail: str
    measurement: str
    refusal: bool
    words: int

    def to_json(self) -> dict[str, object]:
        return {"ref": self.ref, "title": self.title, "date": self.date,
                "headline": self.headline, "detail": self.detail,
                "measurement": self.measurement, "refusal": self.refusal,
                "words": self.words}


def read(path: Path = SOURCE) -> list[Failure]:
    if not path.exists():
        return []
    text = path.read_text()
    heads = list(_HEAD.finditer(text))
    out: list[Failure] = []

    for i, m in enumerate(heads):
        body = text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        # "D12 — 2026-08-21" carries a reference and a date and no title. The
        # title is the first bold sentence of the entry, which is where the
        # actual claim lives; using the heading would label every entry with a
        # date.
        heading = m.group(1).strip()
        ref = re.split(r"[—-]", heading)[0].strip() or f"#{i + 1}"
        date = heading.split("—")[-1].strip() if "—" in heading else ""

        b = _BOLD.search(body)
        headline = " ".join(b.group(1).split()) if b else ""
        title = headline.rstrip(".") if headline else heading

        # The title IS the headline with its full stop removed, so rendering
        # both puts the same sentence on the screen twice. What a reader wants
        # under the claim is the paragraph that argues it: the first prose block
        # after the bold line that is not a heading, a fence or a list.
        detail = ""
        after = body[b.end():] if b else body
        for para in re.split(r"\n\s*\n", after):
            t = " ".join(para.split())
            if not t or t.startswith(("#", "```", "|", "-", "*", ">")):
                continue
            # The source is markdown; the UI renders escaped text. Emphasis
            # markers would otherwise show up as literal asterisks mid-sentence.
            t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
            t = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", t)
            t = re.sub(r"`([^`]+)`", r"\1", t)
            detail = t
            break

        f = _FENCE.search(body)
        measurement = f.group(1).rstrip() if f else ""

        low = body.lower()
        out.append(Failure(
            ref=ref, title=title, date=date, headline=headline, detail=detail,
            measurement=measurement,
            refusal=any(p in low for p in _REFUSALS),
            words=len(body.split()),
        ))
    return out


def summary(path: Path = SOURCE) -> dict[str, object]:
    entries = read(path)
    return {
        "entries": [e.to_json() for e in entries],
        "count": len(entries),
        "refusals": sum(e.refusal for e in entries),
        "words": sum(e.words for e in entries),
        "note": (
            "Every entry is a failure this engine had, measured against ground "
            "truth, with what it cost and what changed. Entries marked REFUSED "
            "are features that were built, measured, and then not shipped "
            "because they raised the false-proof rate — the number that moves "
            "money in the wrong direction."),
    }


def render(path: Path = SOURCE) -> str:
    s = summary(path)
    w = 74
    out = ["", "FAILURE OBSERVATORY", "=" * w,
           f"  {s['count']} documented failures · {s['refusals']} features built, "
           f"measured and refused", "-" * w]
    for e in s["entries"]:
        flag = "  [BUILT, MEASURED, REFUSED]" if e["refusal"] else ""
        out.append(f"  {e['ref']:<8s}{e['title'][:88]}{flag}")
        if e["measurement"]:
            first = e["measurement"].strip().splitlines()[0][:80]
            out.append(f"          {first}")
    out.append("=" * w)
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    print(render())
