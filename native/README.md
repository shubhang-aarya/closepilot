# `native/` — the packed layer-3 kernel

Rust port of `attest/subsetsum.py::_reachable` behind PyO3, plus the shim that
decides whether to use it.

**The repository clones and runs without any of this.** Nothing in `attest/`
imports from here today. If the extension is not built, `attest_fast` falls back
to the numpy reference and returns the same bytes; see
[the wiring proposal](PROPOSAL-subsetsum-wiring.md) for the two lines that would
switch the engine over, which are deliberately *not* applied because
`attest/subsetsum.py` is frozen under `AGENTS.md`.

| Path | What it is |
|---|---|
| `src/reachable.rs` | The kernel. Two bitplanes, one bit per sum each. No Python. |
| `src/lib.rs` | PyO3 surface. Compiled only with `--features python`. |
| `attest_fast/` | Pure-Python shim: extension if importable, numpy otherwise. |
| `tests/differential.py` | Byte-identical check vs. numpy, 1,777 instances. |
| `tests/fallback.py` | Proves both backends select correctly and agree. |
| `benches/reachable.rs` | Criterion: packed vs. bytes, bound vs. unbound. |
| `bench/pybench.py` | Wall clock through PyO3 on the real portfolio. |
| `BENCH.md` | The numbers. |

---

## Build

Nothing here is required to run the engine. Skip the whole section if you do not
have, or do not want, a Rust toolchain.

### 1. Rust

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
  | sh -s -- -y --default-toolchain stable --profile minimal
source "$HOME/.cargo/env"
```

Built and measured against `cargo 1.98.0` / `rustc 1.98.0`.

### 2. A venv for the extension

Separate from the repository's `.venv` on purpose: `maturin develop` installs
into whichever environment is active, and the repository's environment is meant
to stay a pure-Python clone-and-run.

```bash
cd native
python3.13 -m venv .venv
./.venv/bin/pip install 'maturin>=1.9,<2' 'numpy>=2'
```

### 3. Build and install

```bash
cd native
source "$HOME/.cargo/env"
VIRTUAL_ENV="$PWD/.venv" ./.venv/bin/maturin develop --release
```

`--release` is not optional for measurement. The debug build is roughly 20x
slower and would put the crossover point somewhere meaningless.

`VIRTUAL_ENV` is set explicitly because maturin resolves the target environment
from that variable, not from the interpreter it was invoked with.

### 4. Check it

```bash
cd /path/to/attest
PYTHONPATH="$PWD" native/.venv/bin/python -c \
  "import attest_fast; print(attest_fast.BACKEND)"     # -> rust
```

---

## Tests

```bash
cd native && source "$HOME/.cargo/env"

cargo test --release                                   # kernel vs. brute force

cd .. && PYTHONPATH="$PWD" \
  native/.venv/bin/python native/tests/differential.py  # kernel vs. numpy, ~90s
PYTHONPATH="$PWD" \
  native/.venv/bin/python native/tests/fallback.py      # both backends agree
```

`differential.py` builds the seed-20260821 dataset itself and harvests real
`(pool, target)` pairs at every rung of `LAG_LADDER`, grouped by the ground-truth
hazard label, so all fifteen families are covered by construction rather than by
assertion. It never touches the held-out seed.

## Benchmarks

```bash
cd native && source "$HOME/.cargo/env" && cargo bench     # ~6 min

cd .. && PYTHONPATH="$PWD" \
  native/.venv/bin/python native/bench/pybench.py         # ~3 min
```

`cargo bench` deliberately compiles **without** the `python` feature. Linking
libpython into a measurement whose entire subject is cache behaviour would add
noise for nothing.

## Forcing the fallback

```bash
ATTEST_NATIVE=0 ...     # use numpy even though the extension is installed
```

This exists so the numpy branch can be exercised in a process that has the
extension available. It is an environment variable rather than a monkeypatch
because patching a constant inside a frozen module at runtime is an edit wearing
a disguise.
