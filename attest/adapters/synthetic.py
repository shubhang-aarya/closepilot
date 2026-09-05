"""The synthetic source, labelled as such everywhere it appears. §39.

This is what the engine runs on today, and every snapshot it produces says so.
There is no configuration that makes it report `live`, because the one thing an
integration must never do is let a demo look like a connection.
"""

from __future__ import annotations

from datetime import datetime, timezone

from attest.adapters.base import Snapshot
from attest.generate.generator import build


class SyntheticAdapter:
    name = "synthetic"

    def status(self) -> dict[str, object]:
        return {"provider": "synthetic", "connected": True, "live": False,
                "note": ("Generated portfolio with exact ground truth. Not a "
                         "connection to anything, and labelled as such on every "
                         "snapshot it produces.")}

    def fetch(self, n: int = 250, seed: int = 20260821) -> Snapshot:
        ds = build(n, seed=seed)
        return Snapshot(
            orders=ds.orders, settlements=ds.settlements, credits=ds.credits,
            source=f"synthetic n={n} seed={seed}", live=False,
            fetched_at=datetime.now(timezone.utc),
            coverage="90 days",
            # Zero by construction. The generator emits no order-level reference
            # on a settlement, which is exactly why the engine abstains on 82% of
            # this data and why the anchoring loop measured as a coin flip (D8).
            linked_orders=0,
            warnings=["synthetic data — every figure derived from it describes "
                      "the engine, not a merchant's books"])
