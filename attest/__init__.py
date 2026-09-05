"""ATTEST — settlement reconciliation as constrained optimisation.

The interpreter check below is here rather than in a README because a README is
not executable. FAILURES.md D1 is `dataclass(slots=True)` exploding on import
under the Python that macOS ships as `python3` — 3.9, where `slots=` does not
exist. The error it produces is

    TypeError: dataclass() got an unexpected keyword argument 'slots'

raised from `attest/model.py`, which tells a newcomer nothing about the actual
problem. This was re-confirmed on 2026-08-22 by cloning the repository into an
empty directory and following the obvious commands: the failure is not
historical, it is what a new engineer gets by default on a Mac.

`requires-python` in pyproject.toml does not prevent it. The pip that ships with
3.9 is old enough to install anyway, and `import attest` then appears to work
from inside the repository directory because the package is simply on the path.
"""

import sys as _sys

if _sys.version_info < (3, 11):
    raise RuntimeError(
        f"ATTEST needs Python 3.11 or newer; this is "
        f"{_sys.version_info.major}.{_sys.version_info.minor} "
        f"({_sys.executable}).\n\n"
        f"  macOS ships 3.9 as `python3`. Use an explicit version:\n"
        f"      python3.13 -m venv .venv && ./.venv/bin/pip install -e .\n\n"
        f"  Without this check the first symptom is\n"
        f"      TypeError: dataclass() got an unexpected keyword argument 'slots'\n"
        f"  from attest/model.py, which points at the wrong thing entirely.\n"
        f"  See FAILURES.md D1 and docs/REPRODUCE.md.")
