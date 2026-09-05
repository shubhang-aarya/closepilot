# ATTEST — the whole product in one process: static UI and JSON API, same origin.
#
# The Rust kernel is built rather than skipped. Without it `subsetsum` falls back
# to the numpy reference, whose envelope is Rs 30,000 instead of Rs 2,00,000 — a
# 250-settlement run goes from ~5s to ~21s and 41 settlements come back
# INSUFFICIENT because the solver refuses a space it cannot finish. That is
# correct behaviour and a bad first impression, so the extension is part of the
# image.

# ---- stage 1: build the native wheel -------------------------------------
FROM python:3.13-slim AS native

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential curl \
 && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --profile minimal --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"

RUN pip install --no-cache-dir "maturin>=1.9,<2.0"

WORKDIR /build
COPY native/ ./native/
RUN cd native && maturin build --release --out /wheels

# ---- stage 2: runtime ----------------------------------------------------
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    ATTEST_OPEN_BROWSER=0

WORKDIR /app

# The package is installed EDITABLE, from the source tree, deliberately.
#
# `api._artifact` resolves `Path(__file__).parent.parent / "benchmark"` — the
# measured claims are read off disk at request time rather than baked into
# strings, which is the whole point of the claim register. A normal `pip install`
# moves `attest/` into site-packages, that path becomes `site-packages/benchmark`,
# the read fails, and every claim degrades to NOT MEASURED. Fail-closed, so the
# demo would still serve — just with an empty Trust lens and no numbers, which is
# the worst way to find out.
COPY pyproject.toml README.md ./
COPY attest/ ./attest/
COPY benchmark/ ./benchmark/
COPY FAILURES.md ./
COPY docs/ ./docs/
RUN pip install --no-cache-dir -e .

# The Rust kernel, built above.
COPY --from=native /wheels/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl

# Fail the BUILD rather than the demo. Each of these has a fail-closed runtime
# path, which means a broken image serves a quiet, wrong-looking product instead
# of crashing — so they are asserted here, where someone is watching.
RUN python -c "\
from attest import subsetsum, api; \
assert subsetsum._native_reachable is not None, 'native kernel missing'; \
assert subsetsum.MAX_TARGET_PAISE == 20_000_000, subsetsum.MAX_TARGET_PAISE; \
assert api.kernel_measurement()['lines'], 'kernel measurement unreadable'; \
assert api.anchoring_measurement()['ambiguous'], 'anchoring artifact unreadable'; \
assert api.baselines_measurement().get('present'), 'baseline panel unreadable'; \
assert api.seed_basis(555001)['held_out'] is True, 'panel artifact unreadable'; \
d = api.summary(api.execute(60, 555001)); \
assert d['seed_basis']['held_out'] is True, d['seed_basis']; \
print('OK: kernel', subsetsum.MAX_TARGET_PAISE, '| seed', d['seed'], d['seed_basis']['short'])"

EXPOSE 8420
CMD ["python", "-m", "attest.web"]
