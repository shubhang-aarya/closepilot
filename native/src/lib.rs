//! PyO3 surface for the packed counting DP.
//!
//! Everything real lives in `reachable`, which knows nothing about Python --
//! that is what lets `cargo bench` and `cargo test` link the core without
//! libpython, and what keeps the criterion numbers free of interpreter noise.

pub mod reachable;

#[cfg(feature = "python")]
mod py {
    use numpy::{IntoPyArray, PyArray1};
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;

    use crate::reachable as core;

    /// Drop-in for `attest.subsetsum._reachable`. Returns `uint8[target + 1]`
    /// with byte-for-byte the values the numpy reference produces.
    ///
    /// The interpreter is detached for the DP itself: the kernel touches no Python
    /// object once `nets` is copied out, and settlements are independent, so a
    /// caller is free to thread over them.
    #[pyfunction]
    #[pyo3(signature = (nets, target))]
    fn reachable<'py>(
        py: Python<'py>,
        nets: Vec<u64>,
        target: u64,
    ) -> PyResult<Bound<'py, PyArray1<u8>>> {
        if target > u32::MAX as u64 {
            return Err(PyValueError::new_err(format!("target {target} exceeds addressable range")));
        }
        let counts = py.detach(|| core::reachable(&nets, target));
        Ok(counts.into_pyarray(py))
    }

    /// The `u8`-per-sum control. Exposed so the packing claim can be re-measured
    /// from Python on any machine rather than trusted from this report.
    #[pyfunction]
    #[pyo3(signature = (nets, target))]
    fn reachable_u8<'py>(
        py: Python<'py>,
        nets: Vec<u64>,
        target: u64,
    ) -> PyResult<Bound<'py, PyArray1<u8>>> {
        let counts = py.detach(|| core::reachable_u8(&nets, target));
        Ok(counts.into_pyarray(py))
    }

    /// Bytes of DP state the packed path holds for a given target, measured
    /// from the allocation rather than recomputed from a formula.
    #[pyfunction]
    fn footprint_bytes(target: u64) -> usize {
        core::reachable_packed(&[], target).footprint_bytes()
    }

    /// Band sum over `counts[lo ..= hi]`, saturating at 2.
    ///
    /// `solve` only ever asks whether the band holds none / one / more than one
    /// subset, and answering that from the bitplanes is two popcounts instead
    /// of materialising three megabytes of `u8`. Not wired in -- the contract
    /// pins the signature to return counts -- but measured in the report,
    /// because it is where the next factor of two is.
    #[pyfunction]
    #[pyo3(signature = (nets, target, lo, hi))]
    fn band_total(py: Python<'_>, nets: Vec<u64>, target: u64, lo: u64, hi: u64) -> u64 {
        py.detach(|| {
            let p = core::reachable_packed(&nets, target);
            let (lo, hi) = (lo as usize, (hi as usize).min(p.target));
            let mut total = 0u64;
            for s in lo..=hi {
                total += p.count_at(s) as u64;
                if total >= 2 {
                    return 2;
                }
            }
            total
        })
    }

    #[pymodule]
    fn attest_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_function(wrap_pyfunction!(reachable, m)?)?;
        m.add_function(wrap_pyfunction!(reachable_u8, m)?)?;
        m.add_function(wrap_pyfunction!(footprint_bytes, m)?)?;
        m.add_function(wrap_pyfunction!(band_total, m)?)?;
        m.add("MAX_TARGET_PAISE", core::MAX_TARGET_PAISE)?;
        Ok(())
    }
}
