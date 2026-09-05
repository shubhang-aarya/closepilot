# Benchmarks

Apple Silicon, `--release`, `attest_native` vs `attest/subsetsum.py::_reachable`.
Pool of 185 orders — the measured p50 candidate pool at rung 0.

```
credit        numpy       native     speedup   identical
Rs 20,000    275.6 ms    17.11 ms     16.1x      yes
Rs 80,000  1,342.8 ms    25.46 ms     52.7x      yes
```

The speedup widens with credit size. That is the expected shape: the DP is three
ALU ops per cell and bandwidth-bound, so shrinking the state from eight bits per
sum to two is the whole optimisation, and the win grows with the array.

```
DP footprint at Rs 200,000    4.8 MB     (one byte per sum: 19.5 MB)
```

## Parity

```
edge          27 instances    0 mismatches
random     1,000 instances    0 mismatches
harvested    750 instances    0 mismatches   (real pool/target pairs, all rungs)
--------------------------------------------
           1,777 instances    1.323e11 DP cells    15/15 hazard families
```

Compared with `tobytes()`, not `np.array_equal`: `solve` sums a slice of this
array, so a dtype difference would change the sum without failing an equality
test.

## End-to-end

```
                        before      after
envelope              Rs 30,000   Rs 200,000
portfolio reachable       85.2%       100.0%
wall clock, 250 stl       12.7 s       1.06 s
WRONG                         1            0
```

Opening the envelope removed the last false proof: the settlement that produced
it had been decided against a pool missing a large bundle that is now claimed
correctly elsewhere.
