//! Packed bitplanes vs. one byte per sum, at the shapes this engine actually
//! sees. Sizes come from the seed-20260821 portfolio (see `native/BENCH.md`):
//! rung-0 pools are p50 45 / p90 91 orders, rung-2 p50 107 / p90 199, and
//! credits run p50 1.37e6 / p90 6.03e6 paise -- the latter above
//! `MAX_TARGET_PAISE`, which is itself part of the finding.
//!
//! Five series, because three effects are being separated. `packed2bit` and
//! `bytes` both carry the reachability bound and both return one u8 per sum, so
//! their ratio isolates the packing. The `_unbounded` pair drops the bound and
//! so has the same shape as the numpy reference, which makes the Python-side
//! comparison attributable rather than one number covering every change.
//! `packed2bit_noexpand` stops at the bitplanes, so the gap to `packed2bit` is
//! exactly what the u8 output format costs.
//!
//! The `python` feature is off here on purpose -- linking libpython would put
//! interpreter noise into a measurement whose whole point is cache behaviour.

use attest_native::reachable::{
    expand, reachable, reachable_packed, reachable_packed_unbounded, reachable_u8,
    reachable_u8_unbounded,
};
use criterion::{criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};

/// Deterministic nets in the shape of real order values: a few hundred to a few
/// thousand rupees, in paise. Magnitude matters -- nets small relative to
/// `target` are what keep the reachability bound biting.
fn nets(n: usize, seed: u64) -> Vec<u64> {
    let mut s = seed | 1;
    (0..n)
        .map(|_| {
            s ^= s << 13;
            s ^= s >> 7;
            s ^= s << 17;
            20_000 + s % 480_000
        })
        .collect()
}

/// (pool size, target paise). Chosen to sweep the crossover rather than to
/// flatter either implementation.
const SHAPES: &[(usize, u64)] = &[
    (8, 50_000),
    (32, 200_000),
    (45, 1_365_000),  // rung-0 p50 pool at the p50 credit
    (91, 1_365_000),  // rung-0 p90 pool
    (107, 1_365_000), // rung-2 p50 pool
    (199, 3_000_000), // rung-2 p90 pool at MAX_TARGET_PAISE
    (430, 3_000_000),
    (900, 3_000_000), // MAX_POOL at MAX_TARGET_PAISE -- the production ceiling
];

fn bench(c: &mut Criterion) {
    let mut g = c.benchmark_group("reachable");
    g.sample_size(30);
    for &(n, target) in SHAPES {
        let v = nets(n, 0x2026_0821 ^ n as u64);
        // Cell updates, so ns/iter converts directly to ns per DP cell and the
        // implementations stay comparable across shapes.
        g.throughput(Throughput::Elements(n as u64 * (target + 1)));
        let id = format!("n{n}_t{target}");
        g.bench_with_input(BenchmarkId::new("packed2bit", &id), &v, |b, v| {
            b.iter(|| reachable(std::hint::black_box(v), target))
        });
        g.bench_with_input(BenchmarkId::new("bytes", &id), &v, |b, v| {
            b.iter(|| reachable_u8(std::hint::black_box(v), target))
        });
        g.bench_with_input(BenchmarkId::new("packed2bit_unbounded", &id), &v, |b, v| {
            b.iter(|| expand(&reachable_packed_unbounded(std::hint::black_box(v), target)))
        });
        // Same DP, expansion dropped. The gap to `packed2bit` is the cost of
        // materialising one u8 per sum purely so `solve` can sum a slice of it.
        g.bench_with_input(BenchmarkId::new("packed2bit_noexpand", &id), &v, |b, v| {
            b.iter(|| reachable_packed(std::hint::black_box(v), target))
        });
        g.bench_with_input(BenchmarkId::new("bytes_unbounded", &id), &v, |b, v| {
            b.iter(|| reachable_u8_unbounded(std::hint::black_box(v), target))
        });
    }
    g.finish();
}

criterion_group!(benches, bench);
criterion_main!(benches);
