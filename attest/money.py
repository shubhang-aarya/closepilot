"""Rendering an amount for a person to read.

The mirror of `adapters/money.py`, which reads an amount *in* from a source and
refuses anything it cannot read exactly. This one writes an amount *out*, to a
human, and the two are separate modules on purpose: reading is part of the proof
boundary and may raise; rendering never fails and never touches a decision.

Paise remain the only unit the engine computes in. Nothing here is ever parsed
back — a formatted string is a terminal value, for eyes only.

## Why this is not a style preference

It lived in `policy.py` as `_rs`, where its docstring made the argument:

    the reasons are read by a person deciding whether to trust a posting;
    "11613 paise" makes them do the arithmetic, and money that has to be
    converted before it can be judged is money that will be misjudged.

`exceptions.py` had independently written the same rule into its own module
docstring — promising "Six orders explain all but ₹680.74" — and then emitted
integer paise at four sites anyway. A stranger reading the screen found the drift
screen: a contradicted settlement reading "4 orders explain 586898 paise of
631603" directly beneath the ₹447.05 residual it had already formatted
correctly.

So the rule was decided twice, in two modules, and honoured in neither. It lives
here now because `policy`, `exceptions`, `searchspace` and `graph` all narrate
money and none of them may depend on each other. This module imports nothing.

## The one place it is deliberately not applied

A tolerance. `±31 paise` is sub-rupee, and `±₹0.31` reads worse than the truth.
`tests/test_operator_units.py` pins that exemption so a later sweep does not
"fix" it.
"""

from __future__ import annotations


def rupees(paise: int) -> str:
    """Indian digit grouping, two decimal places, always signed if negative.

    >>> rupees(586898)
    '₹5,868.98'
    >>> rupees(4796811_78)
    '₹47,96,811.78'
    >>> rupees(-450)
    '-₹4.50'
    >>> rupees(0)
    '₹0.00'
    """
    neg, v = paise < 0, abs(paise)
    r, pa = divmod(v, 100)
    s = str(r)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"{'-' if neg else ''}₹{s}.{pa:02d}"
