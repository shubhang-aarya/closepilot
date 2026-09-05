//! The counting DP from `attest/subsetsum.py::_reachable`, packed to two bits.
//!
//! The Python reference stores one `u8` per reachable sum. That is 3 MB at
//! `MAX_TARGET_PAISE`, re-read and re-written once per order, and numpy widens
//! it to `u16` for the add -- roughly six bytes of memory traffic per cell per
//! order. The DP itself is three ALU ops. It is bandwidth-bound, not
//! compute-bound, so the only optimisation that matters is making the array
//! smaller.
//!
//! Two bits is the floor, because the verdict only distinguishes
//! none / exactly one / more than one. Rather than interleaving 2-bit lanes
//! (which forces lane-masking on every shift), the counter is split into two
//! **bitplanes** of one bit per sum:
//!
//! * `one[s]`  -- exactly one subset of the orders seen so far sums to `s`
//! * `many[s]` -- two or more do
//!
//! The two are mutually exclusive, so `(one, many)` encodes 0/1/2 exactly, in
//! the same two bits, and each plane shifts with a plain bit-shift. The whole
//! saturating add becomes six bitwise ops over 64 sums at a time:
//!
//! ```text
//! both  = (one | many) & (s_one | s_many)   // both sides non-zero => sum >= 2
//! many' = many | s_many | both
//! one'  = (one | s_one) & !both
//! ```
//!
//! Truth table over the nine (a, b) pairs in {0,1,2}^2 is verified in
//! `tests::merge_matches_saturating_add`.

/// Mirrors `attest.subsetsum.MAX_TARGET_PAISE`. Not enforced here -- the Python
/// side raises `OutOfEnvelope` -- but it is what the buffer sizes are budgeted
/// against, so a change there should be noticed here.
pub const MAX_TARGET_PAISE: u64 = 3_000_000;

const WORD_BITS: usize = 64;

/// The packed DP state: two bitplanes, `words` u64s each.
pub struct Packed {
    pub one: Vec<u64>,
    pub many: Vec<u64>,
    pub target: usize,
}

impl Packed {
    pub fn words(&self) -> usize {
        self.one.len()
    }

    /// Bytes of DP state actually held, both planes. This is the number the
    /// port exists to shrink, so it is reported rather than derived by the
    /// caller from a formula that could drift from the implementation.
    pub fn footprint_bytes(&self) -> usize {
        2 * self.one.len() * (WORD_BITS / 8)
    }

    /// Saturating count at one sum, unpacked from the two planes.
    #[inline]
    pub fn count_at(&self, s: usize) -> u8 {
        let (w, b) = (s / WORD_BITS, s % WORD_BITS);
        let one = (self.one[w] >> b) & 1;
        let many = (self.many[w] >> b) & 1;
        (one | (many << 1)) as u8
    }
}

/// Keeps every bit above `target` clear, so `hi` below stays exact and the
/// final expansion needs no tail fixup. Shifts only move bits upward, so this
/// could be deferred to the end -- it is done per order because two ops per
/// order is cheaper than an invariant a reader has to reconstruct.
#[inline]
fn mask_tail(plane: &mut [u64], target: usize) {
    let used = target % WORD_BITS + 1;
    if used < WORD_BITS {
        let last = plane.len() - 1;
        plane[last] &= (1u64 << used) - 1;
    }
}

/// One 0/1-knapsack step: fold in a single order of net value `net`.
///
/// Words run high-to-low for the same reason the Python loop runs descending in
/// `s`: the source word for index `j` is at `j - q`, strictly below it, so the
/// source is still the pre-update state when it is read. That is what makes
/// this 0/1 rather than unbounded -- an order spent once, not repeatedly.
#[inline]
fn step(one: &mut [u64], many: &mut [u64], net: usize, top: usize) {
    let q = net / WORD_BITS;
    let r = net % WORD_BITS;

    if r == 0 {
        for j in (q..=top).rev() {
            let (so, sm) = (one[j - q], many[j - q]);
            let both = (one[j] | many[j]) & (so | sm);
            many[j] |= sm | both;
            one[j] = (one[j] | so) & !both;
        }
    } else {
        // Rust shifts by >= 64 are UB-adjacent (debug panic, release garbage),
        // so the r == 0 case is split out above rather than guarded per word.
        let inv = WORD_BITS - r;
        for j in (q..=top).rev() {
            let carry_o = if j > q { one[j - q - 1] >> inv } else { 0 };
            let carry_m = if j > q { many[j - q - 1] >> inv } else { 0 };
            let so = (one[j - q] << r) | carry_o;
            let sm = (many[j - q] << r) | carry_m;
            let both = (one[j] | many[j]) & (so | sm);
            many[j] |= sm | both;
            one[j] = (one[j] | so) & !both;
        }
    }
}

/// Saturating count of subsets of `nets` reaching each sum in `[0, target]`.
///
/// `net == 0 || net > target` is skipped to mirror the reference exactly; the
/// caller in `solve` already filters those, so the branch is about being a
/// drop-in replacement rather than about correctness of the engine.
pub fn reachable_packed(nets: &[u64], target: u64) -> Packed {
    dp_packed(nets, target, true)
}

/// Same DP with the reachability bound switched off, so the benchmark can
/// attribute the speedup. The numpy reference does not carry the bound, and
/// without this variant the packing and the bound would be credited together.
pub fn reachable_packed_unbounded(nets: &[u64], target: u64) -> Packed {
    dp_packed(nets, target, false)
}

fn dp_packed(nets: &[u64], target: u64, bounded: bool) -> Packed {
    let target = target as usize;
    let words = target / WORD_BITS + 1;

    let mut one = vec![0u64; words];
    let mut many = vec![0u64; words];
    one[0] = 1; // the empty subset reaches 0, exactly one way

    // Highest reachable sum so far. Everything above it is provably zero, and
    // on real pools -- order nets of a few thousand rupees against a credit of
    // a few lakh -- the bound stays below `target` for the whole pass, so most
    // word visits are skipped outright.
    let mut hi: usize = 0;

    for &net in nets {
        if net == 0 || net as usize > target {
            continue;
        }
        let net = net as usize;
        let reach = (hi + net).min(target);
        let top = if bounded { reach / WORD_BITS } else { words - 1 };
        step(&mut one, &mut many, net, top);
        mask_tail(&mut one, target);
        mask_tail(&mut many, target);
        hi = reach;
    }

    Packed { one, many, target }
}

/// Byte `i` of `SPREAD[x]` is bit `i` of `x`. Turns one byte of a bitplane into
/// eight output bytes with a single load, which keeps the expansion from
/// costing more than the DP it is expanding.
const SPREAD: [u64; 256] = {
    let mut t = [0u64; 256];
    let mut x = 0usize;
    while x < 256 {
        let mut i = 0;
        while i < 8 {
            if x >> i & 1 == 1 {
                t[x] |= 1u64 << (8 * i);
            }
            i += 1;
        }
        x += 1;
    }
    t
};

/// Expand the bitplanes to one `u8` per sum -- the exact layout the numpy
/// reference returns, so the Python boundary is a memcpy into an ndarray.
pub fn expand(p: &Packed) -> Vec<u8> {
    let n = p.target + 1;
    let mut out = vec![0u8; p.words() * WORD_BITS];
    for w in 0..p.words() {
        let (o, m) = (p.one[w].to_le_bytes(), p.many[w].to_le_bytes());
        for b in 0..8 {
            let bytes = (SPREAD[o[b] as usize] | (SPREAD[m[b] as usize] << 1)).to_le_bytes();
            out[w * WORD_BITS + b * 8..w * WORD_BITS + b * 8 + 8].copy_from_slice(&bytes);
        }
    }
    out.truncate(n);
    out
}

pub fn reachable(nets: &[u64], target: u64) -> Vec<u8> {
    expand(&reachable_packed(nets, target))
}

/// The same DP with one `u8` per sum, kept as the control for the packing
/// claim. If this ever beats `reachable`, the contract's premise about memory
/// bandwidth is wrong and that is the finding worth reporting.
pub fn reachable_u8(nets: &[u64], target: u64) -> Vec<u8> {
    dp_u8(nets, target, true)
}

pub fn reachable_u8_unbounded(nets: &[u64], target: u64) -> Vec<u8> {
    dp_u8(nets, target, false)
}

fn dp_u8(nets: &[u64], target: u64, bounded: bool) -> Vec<u8> {
    let target = target as usize;
    let mut c = vec![0u8; target + 1];
    c[0] = 1;
    let mut hi: usize = 0;

    for &net in nets {
        if net == 0 || net as usize > target {
            continue;
        }
        let net = net as usize;
        let reach = (hi + net).min(target);
        let top = if bounded { reach } else { target };
        for s in (net..=top).rev() {
            // Max 2 + 2 = 4, so the u8 add cannot wrap before the clamp.
            c[s] = (c[s] + c[s - net]).min(2);
        }
        hi = reach;
    }
    c
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Brute force over all 2^n subsets, saturating at 2. Independent of the
    /// DP, so it catches an error in the recurrence rather than in its coding.
    fn brute(nets: &[u64], target: u64) -> Vec<u8> {
        let mut c = vec![0u8; target as usize + 1];
        let usable: Vec<u64> = nets.iter().copied().filter(|&n| n != 0 && n <= target).collect();
        for mask in 0u64..(1u64 << usable.len()) {
            let mut s = 0u64;
            for (i, &n) in usable.iter().enumerate() {
                if mask >> i & 1 == 1 {
                    s += n;
                    if s > target {
                        break;
                    }
                }
            }
            if s <= target {
                c[s as usize] = (c[s as usize] + 1).min(2);
            }
        }
        c
    }

    #[test]
    fn merge_matches_saturating_add() {
        for a in 0u8..3 {
            for b in 0u8..3 {
                let mut one = vec![if a == 1 { 1u64 } else { 0 }];
                let mut many = vec![if a == 2 { 1u64 } else { 0 }];
                let (so, sm) = (if b == 1 { 1u64 } else { 0 }, if b == 2 { 1u64 } else { 0 });
                let both = (one[0] | many[0]) & (so | sm);
                many[0] |= sm | both;
                one[0] = (one[0] | so) & !both;
                let got = (one[0] | (many[0] << 1)) as u8;
                assert_eq!(got, (a + b).min(2), "a={a} b={b}");
                assert_eq!(one[0] & many[0], 0, "planes must stay disjoint");
            }
        }
    }

    #[test]
    fn packed_matches_brute_force() {
        let mut seed = 0x2026_0821u64;
        let mut next = move || {
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            seed
        };
        for _ in 0..400 {
            let target = next() % 400;
            let n = (next() % 12) as usize;
            let nets: Vec<u64> = (0..n).map(|_| next() % (target + 2)).collect();
            assert_eq!(reachable(&nets, target), brute(&nets, target));
            assert_eq!(reachable_u8(&nets, target), brute(&nets, target));
        }
    }

    #[test]
    fn word_boundary_shifts() {
        // Nets at and around multiples of 64 exercise the r == 0 split and the
        // cross-word carry, which is where a packed shift goes wrong.
        for net in [1u64, 63, 64, 65, 127, 128, 129, 191, 192] {
            let nets = vec![net, net, 1, 64, 64];
            let target = 600u64;
            assert_eq!(reachable(&nets, target), reachable_u8(&nets, target), "net={net}");
        }
    }

    #[test]
    fn degenerate_inputs() {
        assert_eq!(reachable(&[], 0), vec![1u8]);
        assert_eq!(reachable(&[0, 0], 4), vec![1u8, 0, 0, 0, 0]);
        assert_eq!(reachable(&[9], 4), vec![1u8, 0, 0, 0, 0]);
        assert_eq!(reachable(&[4], 4), vec![1u8, 0, 0, 0, 1]);
        assert_eq!(reachable(&[2, 2], 4), vec![1u8, 0, 2, 0, 1]);
    }
}
