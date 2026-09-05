"""Proof that `attest_fast` works with and without the Rust extension.

The clone-and-run requirement is the one claim that cannot be checked by running
the happy path, because on this machine the extension is installed. So the third
case below is not a simulation: it runs the *repository's own* interpreter,
which has numpy and nothing else, with `native/` merely on `PYTHONPATH`. That is
exactly the state of a clone with no Rust toolchain, and it is the only case
that actually settles the question.

Subprocesses rather than reloads: `attest_fast` resolves its backend at import
time, which is the point, and re-importing it in-process would only prove that
`importlib.reload` works.

Run:  PYTHONPATH=<repo> native/.venv/bin/python native/tests/fallback.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

NATIVE = Path(__file__).resolve().parent.parent
REPO = NATIVE.parent
#: The interpreter a fresh clone would use. It has numpy and no `attest_native`.
REPO_PY = REPO / ".venv" / "bin" / "python"

#: A pool small enough to run instantly but carrying a saturated count -- 8 + 13
#: and 3 + 5 + 13 both reach 21 -- so a backend that lost the `min(_, 2)` clamp
#: would show up as a different byte rather than as a timing difference.
NETS = "[3, 5, 8, 8, 13, 21]"
TARGET = "34"

_SCRIPT = f"""
import attest_fast
counts = attest_fast.reachable({NETS}, {TARGET})
print(attest_fast.BACKEND, counts.dtype, counts.tobytes().hex())
"""


def _run(python: Path, env: dict[str, str]) -> tuple[str, str, str]:
    out = subprocess.run([str(python), "-c", _SCRIPT], capture_output=True, text=True,
                         env={**os.environ, **env}, check=True)
    return tuple(out.stdout.split())  # type: ignore[return-value]


def main() -> int:
    if not REPO_PY.exists():
        print(f"FAIL: {REPO_PY} missing; cannot test the toolchain-free path.")
        return 1

    paths = f"{REPO}:{NATIVE}"
    runs = {
        "native venv (extension built)": _run(Path(sys.executable), {"PYTHONPATH": paths}),
        "native venv, ATTEST_NATIVE=0": _run(Path(sys.executable),
                                             {"PYTHONPATH": paths, "ATTEST_NATIVE": "0"}),
        "repo venv (no Rust toolchain)": _run(REPO_PY, {"PYTHONPATH": paths}),
    }

    print(f"{'interpreter':<32} {'backend':<8} {'dtype':<8} counts")
    for name, (backend, dtype, digest) in runs.items():
        print(f"{name:<32} {backend:<8} {dtype:<8} {digest}")

    expected = ["rust", "numpy", "numpy"]
    got = [v[0] for v in runs.values()]
    payloads = {v[1:] for v in runs.values()}

    ok = True
    if got != expected:
        print(f"\nFAIL: backend selection was {got}, expected {expected}")
        ok = False
    if len(payloads) != 1:
        print(f"\nFAIL: the three paths disagree: {payloads}")
        ok = False

    print("\nRESULT: " + ("extension used when present, numpy when absent, "
                          "identical bytes from all three."
                          if ok else "fallback is broken."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
