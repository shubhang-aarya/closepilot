"""Reading an amount from a source, exactly or not at all. ADAPTER-002.

The adapter is part of the proof boundary. If the reader changes the money, the
solver proves the reader's mistake — so this module has one job and refuses
everything it cannot do exactly.

`int(10.5)` used to give `10`. That is a money value altered by the reader with
nobody told, and no amount of care further down the pipeline recovers it.

## The unit is declared, never inferred

The bug underneath the truncation is that `10.50` is ambiguous without a
contract. Under Razorpay's recon API, which quotes **integer paise**, `10.50` is
ten and a half paise — not ten rupees fifty. A reader that guesses is a reader
that will eventually guess wrong by a factor of a hundred, so `Unit` is required
and each adapter declares its own.

## What is accepted

Under `Unit.PAISE`:

    1050        int              -> 1050
    1050.0      integral float   -> 1050    exact, no fraction lost
    "1050"      digits           -> 1050
    "1050.00"   decimal, .00     -> 1050    exact under Decimal, not float

Under `Unit.RUPEES` (no Razorpay endpoint uses this; it exists so a source that
does can be read without the adapter inventing a convention):

    "10.50"     decimal          -> 1050
    10          int              -> 1000

## What is refused, and why refusal rather than rounding

    10.5    under PAISE   fractional paise — the source is not in the unit
                          it declared, and rounding picks a side silently
    "10.001" under RUPEES more precision than paise can hold
    NaN, Infinity         not amounts
    "", None, "abc"       not numbers
    negative              an amount, not a direction; sign belongs to the
                          credit/debit column the source already provides

A refusal is returned as a reason, never raised: one bad row must not lose a
page (ADAPTER-003).
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from enum import Enum


class Unit(str, Enum):
    PAISE = "paise"
    RUPEES = "rupees"


class AmountError(ValueError):
    """Carries why, so an ingestion can report it rather than swallow it."""


_HUNDRED = Decimal(100)


def parse_amount(raw: object, unit: Unit) -> int:
    """Return integer paise, or raise `AmountError` naming the reason.

    Never truncates, never rounds, never coerces. Every accepted representation
    is exact under `Decimal`; `float` is admitted only when it is integral in
    the declared unit, because a float that is not integral has already lost the
    thing that would make it exact.
    """
    if raw is None:
        raise AmountError("amount is absent")
    if isinstance(raw, bool):
        raise AmountError("a boolean is not an amount")

    if isinstance(raw, int):
        d = Decimal(raw)
    elif isinstance(raw, float):
        if math.isnan(raw) or math.isinf(raw):
            raise AmountError(f"{raw} is not a finite amount")
        if raw != int(raw):
            # Decimal(0.1) is 0.1000000000000000055511151231257827, so a
            # non-integral float cannot be read exactly whatever we do with it.
            raise AmountError(
                f"{raw!r} is a non-integral float; a source that means "
                f"fractions must send them as a string so they can be read "
                f"exactly")
        d = Decimal(int(raw))
    elif isinstance(raw, str):
        t = raw.strip()
        if not t:
            raise AmountError("amount is an empty string")
        try:
            d = Decimal(t)
        except InvalidOperation:
            raise AmountError(f"{raw!r} is not a number") from None
        if not d.is_finite():
            raise AmountError(f"{raw!r} is not a finite amount")
    else:
        raise AmountError(f"{type(raw).__name__} is not an amount")

    if unit is Unit.RUPEES:
        d = d * _HUNDRED

    if d != d.to_integral_value():
        raise AmountError(
            f"{raw!r} in {unit.value} is {d} paise, which is not a whole "
            f"paisa; ATTEST holds money as integer paise and will not round "
            f"one for you")
    if d < 0:
        raise AmountError(
            f"{raw!r} is negative; direction belongs to the credit/debit "
            f"column, not to the magnitude")
    return int(d)
