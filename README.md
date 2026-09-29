# Aeolus — Risk-Informed Dynamic Rerouting: Computational Study

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22008789.svg)](https://doi.org/10.5281/zenodo.22008789)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A small, dependency-free Python simulation that measures how much each kind of
disruption information is worth when rerouting freight trucks, on a 30-city
network calibrated to Indian line-haul conditions. It is for readers of the
paper who want to check or extend its numbers, and for anyone studying
value-of-information in dynamic routing.

Companion code and results for:

> **Risk-Informed Dynamic Rerouting for Resilient Logistics: The Aeolus
> Framework and a Computational Study on an India-Calibrated Freight Network**
> Punarbasu Pradhan (independent researcher) and Lekshmi Madhusudhanan
> (Department of Ocean Engineering, Indian Institute of Technology Madras)

This repository contains everything needed to reproduce **every number in the
paper's computational study** from a fixed seed: one self-contained Python
script and the exact results file it emits.

---

## What the study measures

Commercial supply-chain software senses disruptions and it optimises routes,
but the two rarely compose: risk intelligence seldom becomes a same-day
routing decision. The paper calls that the *Intelligence Orchestration Gap*.

This study quantifies what each increment of information is actually worth for
line-haul rerouting. Five policies are simulated on the same disruption
scenarios; each policy is an **information set**, not a different algorithm,
so differences between them isolate the value of information rather than the
value of a better optimiser.

| Policy | Information available | Market archetype |
|--------|----------------------|------------------|
| `P0`  | None. Nominal shortest path fixed at dispatch. | Static planning |
| `P1`  | Local discovery only — a disruption is seen when the vehicle stands at an endpoint of the affected corridor while it is active. Memory persists. | Status-quo trucking |
| `P1g` | All *currently active* disruptions, network-wide. Future onsets unknown. | Visibility platforms |
| `P2`  | `P1g` + predictive signals received `lead` hours before onset, priced in expectation at calibrated precision. | **Aeolus** |
| `P3`  | Full future knowledge. | Oracle / value-of-perfect-information bound |

### Headline result

Predictive signals cut mean delay on disruption-exposed shipments by **29.2%**
relative to global-telemetry rerouting:

| Metric (disruption-exposed shipments) | `P1g` global telemetry | `P2` predictive | `P3` oracle |
|---|---|---|---|
| Mean delay vs nominal ETA (h) | 10.52 ± 0.72 | **7.44 ± 0.57** | 4.40 ± 0.29 |
| On-time-in-full rate | 83.4% | **91.2%** | 98.1% |

`P2` captures **50%** of the residual value of perfect information. Two
secondary findings: the benefit persists down to **50% signal precision** —
a false-alarm detour is cheap, a mid-corridor trap is not, so the loss
function is asymmetric — and **lead time is worth as much as precision**.

11.09% of shipments are disruption-exposed (their nominal path intersects a
disruption window). Unexposed shipments are unaffected by construction, so
the exposed subset is where the policy difference lives; network-wide means
are reported too and are correspondingly diluted.

---

## Install

No dependencies. Pure Python standard library, Python 3.9+. Clone and run:

```sh
git clone https://github.com/ShrewdLemon/aeolus-rerouting-study.git
cd aeolus-rerouting-study
```

## Reproducing

```sh
python3 rerouting_study.py
```

Runtime is about **2m20s** on an Apple M-series laptop (single-threaded,
200 replications x 200 shipments x 3 experiments). Progress prints to stdout;
the script overwrites `rerouting_results.json` in the working directory.

### Verifying you got the same thing

The committed `rerouting_results.json` is byte-identical across runs and
machines. Check it:

```sh
python3 rerouting_study.py
sha256sum rerouting_results.json      # on macOS: shasum -a 256 rerouting_results.json
# 64fa2056e5c6e940b92287c2a700cf81da35003da38103d8f24bea296840e4e0
```

That digest is quoted in the paper's data-availability statement and pins the
archived artefact on Zenodo.

> **Note on determinism.** `build_network()` iterates adjacency sets in
> `sorted()` order (see the comment at the function). This matters: Python's
> hash randomisation varies set iteration order between interpreter runs, and
> disruption sampling consumes edge order, so unsorted iteration silently made
> the results seed-dependent. Preserve the `sorted()` calls if you modify the
> network builder.

### How it is checked

There is no unit-test suite and no CI. The check is end-to-end: rerun the
script and compare the SHA-256 of the results file with the digest above.
On 29 Sep 2026 a fresh run on Python 3.14.7 (Apple M-series, macOS) matched
it byte for byte in 2m22s.

### Design principles

- Every result in the paper and in this README is read from
  `rerouting_results.json`, and that file comes from one seeded run.
- Policies differ only in what they know, never in how they optimise.
- Standard library only, so the result does not drift with package versions.
- Confidence intervals are reported next to every mean.

---

## Model

**Network.** 30 major Indian cities. Corridors are a symmetrised
4-nearest-neighbour graph on great-circle distance, giving 74 corridors and
~34,009 km of road. Road distance = haversine x 1.25 circuity factor.
Effective line-haul speed is 40 km/h, calibrated to Indian conditions of
roughly 350-450 km/day inclusive of statutory rest and dwell.

**Disruptions.** A monsoon-stress scenario over a 168-hour week: 8 corridor
events, onset ~ U(0, 144) h, duration ~ U(24, 72) h. 40% are full closures —
vehicle progress halts, *including mid-arc* — and the rest apply a slowdown
multiplier ~ U(2.5, 5.0).

True traversal times integrate the piecewise speed profile, so a vehicle that
enters a corridor shortly before a closure begins is **trapped for the
remainder of that closure**. This is the mechanism that separates the
policies. Without mid-arc trapping and local-only discovery, reactive policies
with global telemetry perform almost identically to the oracle and the study
has nothing to measure.

**Signals (`P2`).** Each true disruption is detected with probability
`recall`; false signals are then added so that *realised* precision equals the
`precision` parameter. False signals reference undisrupted corridors with
random windows. Signalled windows are priced at an assumed severity multiplier
of 4.0 in expectation.

**Routing.** Time-dependent Dijkstra over belief costs, re-planned on an
event-triggered rolling horizon. `P3` uses a separate oracle Dijkstra against
ground truth.

**Metrics.** Mean delay against nominal ETA, and on-time-in-full rate where
due = depart + 1.2 x nominal + 12 h. Both are reported for all shipments and
for the disruption-exposed subset, with 95% confidence intervals across
replications.

### Parameters

| Parameter | Value | Constant |
|---|---|---|
| Master seed | 20260724 | `master_seed` |
| Replications | 200 | `n_reps` |
| Shipments per replication | 200 | `n_shipments` |
| Disruptions per scenario | 8 | `n_disruptions` |
| Planning horizon | 168 h | `HORIZON` |
| Signal precision (baseline) | 0.8 | `precision` |
| Signal recall | 0.8 | `recall` |
| Signal lead time (baseline) | U(6, 18) h | `lead` |
| Circuity factor | 1.25 | `CIRCUITY` |
| Line-haul speed | 40 km/h | `SPEED_KMH` |
| Corridors per city (pre-symmetrisation) | 4 | `KNN` |
| Full-closure share | 0.40 | `CLOSURE_SHARE` |
| Assumed severity of signalled windows | 4.0x | `EXP_MULT` |

---

## Results file

`rerouting_results.json` has four top-level keys. Every metric is a
`[mean, half-width-of-95%-CI]` pair.

```
network              cities, corridors, total_km
policy_comparison    exposed_frac, then P0 / P1 / P1g / P2 / P3
precision_sweep      keyed "0.5" ... "0.95"; each has exposed_frac, P1g, P2
lead_sweep           keyed "0-6" / "6-18" / "18-36" (hours); same shape
```

Each policy object carries four metrics:

| Key | Meaning |
|---|---|
| `delay`     | Mean delay vs nominal ETA, all shipments (h) |
| `otif`      | On-time-in-full rate, all shipments |
| `exp_delay` | Mean delay, disruption-exposed shipments only (h) |
| `exp_otif`  | On-time-in-full rate, disruption-exposed shipments only |

Reading the headline number straight out of the file:

```python
import json
d = json.load(open("rerouting_results.json"))
p = d["policy_comparison"]
a = p["P1g"]["exp_delay"][0]
b = p["P2"]["exp_delay"][0]
print(f"{(a - b) / a * 100:.1f}% delay reduction ({b} vs {a} h)")
# 29.2% delay reduction (7.441 vs 10.516 h)
```

### Mapping to the paper

| Paper element | Source |
|---|---|
| Policy comparison table | `policy_comparison` |
| Precision-robustness figure | `precision_sweep` |
| Lead-time figure | `lead_sweep` |
| Network description | `network` |

---

## Scope and limitations

This is a **simulation study on a synthetic-but-calibrated network**, not a
field trial. Corridor topology is generated from city coordinates rather than
taken from a road network database; disruption processes are parametric rather
than fitted to historical incident data; and the predictive signal is modelled
by its precision/recall/lead-time characteristics rather than produced by a
trained model. The numbers should be read as *what this class of information
is worth under these assumptions*, not as a forecast of realised savings for
any operator. The paper specifies a difference-in-differences field-validation
protocol for the latter.

---

## Citing

If you use this code or these results, please cite the paper. Machine-readable
metadata is in `CITATION.cff`; GitHub renders a "Cite this repository" button
from it.

To cite the archived software itself:

> Pradhan, P., & Madhusudhanan, L. (2026). *Aeolus — Risk-Informed Dynamic
> Rerouting: Computational Study* (v1.0.0) [Software]. Zenodo.
> https://doi.org/10.5281/zenodo.22008789

```bibtex
@software{aeolus_rerouting_study_2026,
  author  = {Pradhan, Punarbasu and Madhusudhanan, Lekshmi},
  title   = {Aeolus --- Risk-Informed Dynamic Rerouting: Computational Study},
  version = {1.0.0},
  year    = {2026},
  doi     = {10.5281/zenodo.22008789},
  url     = {https://doi.org/10.5281/zenodo.22008789}
}
```

## Licence

MIT. See `LICENSE`.

## Contact

Issues and questions: [github.com/ShrewdLemon](https://github.com/ShrewdLemon)
or open an issue on this repository.
