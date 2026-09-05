"""Data sources. §34.

The engine must not know where records came from. Every adapter normalises an
external shape into `attest.model` and nothing downstream can tell the
difference — which is what makes the reconciliation logic testable against
synthetic data and runnable against a real gateway without a branch anywhere in
the solver.
"""

from attest.adapters.base import DataSource, Snapshot

__all__ = ["DataSource", "Snapshot"]
