"""Backend selection for the layer-3 counting DP.

`attest/subsetsum.py` is human-authored and frozen, so the Rust extension cannot
be wired in by editing it. It is wired in here instead: this module exposes one
function with the reference's exact signature and picks a backend at import
time. A clone with no Rust toolchain imports this successfully and gets numpy;
a clone that ran `maturin develop` gets the packed kernel. Neither needs to know
which, and no caller branches on it.

The numpy path is not a reimplementation. It calls `attest.subsetsum._reachable`
itself, so there is exactly one reference and it cannot drift from what the
differential test validates against.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Callable, Final

if TYPE_CHECKING:
    import numpy as np

#: Set to "0" to force the numpy path even when the extension is installed.
#: The differential test uses this to exercise both branches in one process
#: without touching the frozen module -- monkeypatching it would be an edit.
_ENV: Final = "ATTEST_NATIVE"

_rust: Callable[[list[int], int], "np.ndarray"] | None
try:
    if os.environ.get(_ENV, "1") == "0":
        raise ImportError("disabled by " + _ENV)
    from attest_native import reachable as _rust
except ImportError:
    _rust = None

#: "rust" or "numpy". Read by the harness so a benchmark cannot silently
#: report the fallback's timings as the extension's.
BACKEND: Final[str] = "numpy" if _rust is None else "rust"


def reachable(nets: list[int], target: int) -> np.ndarray:
    """Saturating count of subsets of `nets` reaching each sum in [0, target].

    Byte-identical to `attest.subsetsum._reachable` on both backends; see
    `native/tests/differential.py`.
    """
    if _rust is not None:
        return _rust(nets, target)
    # Imported at call time, not module scope: `attest.subsetsum` is the
    # intended importer of this module, and a top-level import would close the
    # cycle. By the time anything calls this, that module is fully loaded.
    from attest.subsetsum import _reachable

    return _reachable(nets, target)
