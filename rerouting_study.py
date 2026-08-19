#!/usr/bin/env python3
"""
Computational study: risk-informed dynamic rerouting on an India-calibrated
intercity freight network.

Companion code for:
  "Aeolus: Risk-Informed Dynamic Rerouting for Resilient Logistics"
  (computational study section). Pure-stdlib Python; reproducible with the
  fixed master seed below.

Network: 30 major Indian cities; corridors = symmetrised 4-nearest-neighbour
graph on great-circle distance; road distance = haversine x 1.25 circuity
factor; effective long-haul speed 40 km/h (calibrated to Indian line-haul
conditions of roughly 350-450 km/day inclusive of rest and dwell).

Disruptions: corridor events (monsoon-stress scenario), onset U(0,144)h in a
168h week, duration U(24,72)h; 40% full closures (vehicle progress halts,
including mid-arc), otherwise slowdown multiplier U(2.5,5). True traversal
times integrate the piecewise speed profile, so a vehicle that enters a
corridor shortly before a closure begins is trapped for its remainder.

Information regimes (each policy = an information set, mapping to a market
archetype in the paper):
  P0 static    : no information; nominal shortest path fixed at dispatch.
  P1 local     : discovers a disruption only when standing at an endpoint of
                 the affected corridor while it is active (status-quo
                 trucking); remembers what it has seen.
  P1g global   : all *currently active* disruptions visible network-wide
                 (visibility-platform telemetry); future onsets unknown.
  P2 proactive : P1g + predictive risk signals received `lead` hours before
                 onset, priced in expectation with calibrated precision
                 (the Aeolus policy).
  P3 oracle    : full future knowledge (value-of-perfect-information bound).

Signals: each true disruption is detected with probability `recall`; false
signals are added so realised precision equals `precision`; false signals
reference undisrupted corridors with random windows.

Metrics: mean delay vs nominal ETA, on-time rate (due = depart + 1.2 x
nominal + 12h), for all shipments and for the disruption-exposed subset
(nominal path intersects a disruption window). 95% CIs across replications.
"""

import heapq
import json
import math
import random
import statistics
from collections import defaultdict

# ----------------------------------------------------------------------
# Network
# ----------------------------------------------------------------------

CITIES = {
    "Delhi": (28.61, 77.21), "Mumbai": (19.08, 72.88), "Kolkata": (22.57, 88.36),
    "Chennai": (13.08, 80.27), "Bengaluru": (12.97, 77.59), "Hyderabad": (17.38, 78.49),
    "Ahmedabad": (23.02, 72.57), "Pune": (18.52, 73.86), "Surat": (21.17, 72.83),
    "Jaipur": (26.91, 75.79), "Lucknow": (26.85, 80.95), "Kanpur": (26.45, 80.33),
    "Nagpur": (21.15, 79.09), "Indore": (22.72, 75.86), "Bhopal": (23.26, 77.41),
    "Patna": (25.59, 85.14), "Ludhiana": (30.90, 75.86), "Agra": (27.18, 78.01),
    "Varanasi": (25.32, 82.99), "Vadodara": (22.31, 73.19), "Nashik": (19.99, 73.79),
    "Coimbatore": (11.02, 76.96), "Kochi": (9.93, 76.27), "Visakhapatnam": (17.69, 83.22),
    "Guwahati": (26.14, 91.74), "Raipur": (21.25, 81.63), "Ranchi": (23.34, 85.31),
    "Jabalpur": (23.18, 79.99), "Amritsar": (31.63, 74.87), "Jodhpur": (26.24, 73.02),
}

CIRCUITY = 1.25      # road distance / great-circle distance
SPEED_KMH = 40.0     # effective line-haul speed
KNN = 4              # corridors per city (symmetrised)
HORIZON = 168.0      # one-week planning horizon (hours)
CLOSURE_SHARE = 0.40
EXP_MULT = 4.0       # severity multiplier assumed for signalled windows


def haversine(a, b):
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def build_network():
    names = list(CITIES)
    dist = {}
    for i, u in enumerate(names):
        for v in names[i + 1:]:
            dist[(u, v)] = dist[(v, u)] = haversine(CITIES[u], CITIES[v]) * CIRCUITY
    adj = defaultdict(set)
    for u in names:
        nearest = sorted((v for v in names if v != u), key=lambda v: dist[(u, v)])[:KNN]
        for v in nearest:
            adj[u].add(v)
            adj[v].add(u)
    edges = {}
    # Iterate in sorted order: set iteration order varies with Python hash
    # randomization, and disruption sampling consumes EDGES order, so this
    # is required for the fixed-seed reproducibility the paper promises.
    for u in sorted(adj):
        for v in sorted(adj[u]):
            key = (min(u, v), max(u, v))
            edges[key] = dist[key] / SPEED_KMH  # nominal traversal hours
    return names, adj, edges


NAMES, ADJ, EDGES = build_network()


def edge_key(u, v):
    return (min(u, v), max(u, v))


def nominal_time(u, v):
    return EDGES[edge_key(u, v)]


# ----------------------------------------------------------------------
# Scenario generation
# ----------------------------------------------------------------------

class Disruption:
    __slots__ = ("edge", "onset", "end", "closure", "mult")

    def __init__(self, rng):
        self.edge = rng.choice(list(EDGES))
        self.onset = rng.uniform(0.0, 144.0)
        self.end = self.onset + rng.uniform(24.0, 72.0)
        self.closure = rng.random() < CLOSURE_SHARE
        self.mult = 1.0 if self.closure else rng.uniform(2.5, 5.0)


class Signal:
    __slots__ = ("edge", "emit", "start", "end")

    def __init__(self, edge, emit, start, end):
        self.edge, self.emit, self.start, self.end = edge, emit, start, end


def gen_scenario(rng, n_disruptions, precision, recall, lead_lo, lead_hi):
    disruptions = [Disruption(rng) for _ in range(n_disruptions)]
    by_edge = defaultdict(list)
    for d in disruptions:
        by_edge[d.edge].append(d)
    signals = []
    for d in disruptions:
        if rng.random() < recall:
            lead = rng.uniform(lead_lo, lead_hi)
            signals.append(Signal(d.edge, max(0.0, d.onset - lead), d.onset, d.end))
    n_true = len(signals)
    n_false = round(n_true * (1.0 - precision) / precision) if precision < 1.0 else 0
    clean = [e for e in EDGES if e not in by_edge]
    for _ in range(n_false):
        e = rng.choice(clean)
        onset = rng.uniform(0.0, 144.0)
        end = onset + rng.uniform(24.0, 72.0)
        lead = rng.uniform(lead_lo, lead_hi)
        signals.append(Signal(e, max(0.0, onset - lead), onset, end))
    return disruptions, by_edge, signals


# ----------------------------------------------------------------------
# True dynamics: piecewise traversal with mid-arc effects
# ----------------------------------------------------------------------

def true_traversal(by_edge, u, v, t):
    """Traversal time entering (u,v) at t under the true piecewise speed
    profile: progress halts during closures (including closures that begin
    mid-traversal) and slows by `mult` during slowdown windows."""
    events = by_edge.get(edge_key(u, v))
    T_n = nominal_time(u, v)
    if not events:
        return T_n
    remaining = T_n           # remaining traversal in nominal-time units
    cur = t
    guard = 0
    while remaining > 1e-9:
        guard += 1
        if guard > 50:
            break
        active = [d for d in events if d.onset <= cur < d.end]
        closure_end = max((d.end for d in active if d.closure), default=None)
        if closure_end is not None:
            cur = closure_end
            continue
        mult = max((d.mult for d in active), default=1.0)
        future_onsets = [d.onset for d in events if d.onset > cur]
        active_ends = [d.end for d in active]
        nxt = min(future_onsets + active_ends, default=None)
        if nxt is None:
            cur += remaining * mult
            remaining = 0.0
        else:
            span = nxt - cur                    # wall-clock until next event
            possible = span / mult              # nominal progress achievable
            if possible >= remaining:
                cur += remaining * mult
                remaining = 0.0
            else:
                remaining -= possible
                cur = nxt
    return cur - t


# ----------------------------------------------------------------------
# Belief-based planning costs (entry-state approximation over beliefs)
# ----------------------------------------------------------------------

def belief_cost(u, v, t, known_by_edge, sigs, precision):
    """Planning cost of entering (u,v) at time t under a belief consisting of
    disruptions with known windows (evaluated exactly under the piecewise
    dynamics, including mid-traversal onset) and received predictive signals
    priced in expectation: the portion of the traversal expected to overlap a
    signalled window is inflated by precision x (EXP_MULT - 1)."""
    T_n = nominal_time(u, v)
    e = edge_key(u, v)
    cost = true_traversal(known_by_edge, u, v, t) if known_by_edge else T_n
    extra = 0.0
    for s in sigs:
        if s.edge == e:
            overlap = max(0.0, min(s.end, t + T_n) - max(s.start, t))
            extra = max(extra, precision * (EXP_MULT - 1.0) * overlap)
    return max(cost, T_n + extra)


def td_dijkstra(src, dst, t0, known_by_edge, sigs, precision):
    best = {src: t0}
    prev = {}
    pq = [(t0, src)]
    while pq:
        t, u = heapq.heappop(pq)
        if u == dst:
            break
        if t > best.get(u, math.inf):
            continue
        for v in ADJ[u]:
            ta = t + belief_cost(u, v, t, known_by_edge, sigs, precision)
            if ta < best.get(v, math.inf):
                best[v] = ta
                prev[v] = u
                heapq.heappush(pq, (ta, v))
    if dst not in prev and dst != src:
        return None, math.inf
    path, node = [dst], dst
    while node != src:
        node = prev[node]
        path.append(node)
    return path[::-1], best[dst]


def oracle_dijkstra(src, dst, t0, by_edge):
    """Time-dependent Dijkstra under true dynamics (entry-time evaluation)."""
    best = {src: t0}
    prev = {}
    pq = [(t0, src)]
    while pq:
        t, u = heapq.heappop(pq)
        if u == dst:
            break
        if t > best.get(u, math.inf):
            continue
        for v in ADJ[u]:
            ta = t + true_traversal(by_edge, u, v, t)
            if ta < best.get(v, math.inf):
                best[v] = ta
                prev[v] = u
                heapq.heappush(pq, (ta, v))
    return best.get(dst, math.inf)


# ----------------------------------------------------------------------
# Shipment simulation under each information regime
# ----------------------------------------------------------------------

def observe_local(disruptions, node, t, memory):
    """Standing at `node` at time t, observe active disruptions on incident
    corridors; remember them (window revealed once observed)."""
    for d in disruptions:
        if node in d.edge and d.onset <= t < d.end:
            memory.add(d)


def active_global(disruptions, t):
    return [d for d in disruptions if d.onset <= t < d.end]


def as_by_edge(known):
    d = defaultdict(list)
    for k in known:
        d[k.edge].append(k)
    return d


def simulate_shipment(policy, o, d, depart, disruptions, by_edge, signals,
                      precision):
    if policy == "P0":
        path, _ = td_dijkstra(o, d, depart, None, (), 0.0)
        t = depart
        for u, v in zip(path, path[1:]):
            t += true_traversal(by_edge, u, v, t)
        return t
    if policy == "P3":
        return oracle_dijkstra(o, d, depart, by_edge)

    node, t = o, depart
    memory = set()          # for P1 local
    hops = 0
    while node != d:
        if policy == "P1":
            observe_local(disruptions, node, t, memory)
            known, sigs = list(memory), ()
        elif policy == "P1g":
            known, sigs = active_global(disruptions, t), ()
        else:  # P2
            known, sigs = active_global(disruptions, t), \
                [s for s in signals if s.emit <= t]
        path, _ = td_dijkstra(node, d, t, as_by_edge(known), sigs, precision)
        if path is None or len(path) < 2:
            return math.inf
        nxt = path[1]
        t += true_traversal(by_edge, node, nxt, t)
        node = nxt
        hops += 1
        if hops > 3 * len(NAMES):  # safety valve
            return math.inf
    return t


# ----------------------------------------------------------------------
# Experiment driver
# ----------------------------------------------------------------------

def run_config(precision, recall=0.8, lead=(6.0, 18.0), n_disruptions=8,
               n_shipments=200, n_reps=200, master_seed=20260724,
               policies=("P0", "P1", "P1g", "P2", "P3")):
    per_rep = {p: {"delay": [], "otif": [], "exp_delay": [], "exp_otif": []}
               for p in policies}
    exposed_fracs = []
    for rep in range(n_reps):
        rng = random.Random(master_seed + rep)
        disruptions, by_edge, signals = gen_scenario(
            rng, n_disruptions, precision, recall, lead[0], lead[1])
        shipments = []
        for _ in range(n_shipments):
            o, dd = rng.sample(NAMES, 2)
            depart = rng.uniform(0.0, 120.0)
            nom_path, ta = td_dijkstra(o, dd, depart, None, (), 0.0)
            nominal = ta - depart
            due = depart + 1.2 * nominal + 12.0
            exposed = False
            t = depart
            for u, v in zip(nom_path, nom_path[1:]):
                e = edge_key(u, v)
                for dis in by_edge.get(e, ()):
                    if dis.onset < t + nominal_time(u, v) and dis.end > t:
                        exposed = True
                t += nominal_time(u, v)
            shipments.append((o, dd, depart, nominal, due, exposed))
        exposed_fracs.append(sum(1 for s in shipments if s[5]) / len(shipments))
        for p in policies:
            delays, otifs, e_delays, e_otifs = [], [], [], []
            for (o, dd, depart, nominal, due, exposed) in shipments:
                arr = simulate_shipment(p, o, dd, depart, disruptions,
                                        by_edge, signals, precision)
                delay = max(0.0, arr - (depart + nominal))
                ontime = arr <= due
                delays.append(delay)
                otifs.append(1.0 if ontime else 0.0)
                if exposed:
                    e_delays.append(delay)
                    e_otifs.append(1.0 if ontime else 0.0)
            per_rep[p]["delay"].append(statistics.fmean(delays))
            per_rep[p]["otif"].append(statistics.fmean(otifs))
            if e_delays:
                per_rep[p]["exp_delay"].append(statistics.fmean(e_delays))
                per_rep[p]["exp_otif"].append(statistics.fmean(e_otifs))
    out = {"exposed_frac": round(statistics.fmean(exposed_fracs), 4)}
    for p in policies:
        out[p] = {}
        for k, vals in per_rep[p].items():
            m = statistics.fmean(vals)
            sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
            ci = 1.96 * sd / math.sqrt(len(vals))
            out[p][k] = (round(m, 3), round(ci, 3))
    return out


def main():
    results = {}

    print("== Network ==")
    total_km = sum(t * SPEED_KMH for t in EDGES.values())
    print(f"cities={len(NAMES)} corridors={len(EDGES)} "
          f"total corridor length ~{total_km:,.0f} km")
    results["network"] = {"cities": len(NAMES), "corridors": len(EDGES),
                          "total_km": round(total_km)}

    print("\n== Experiment 1: policy comparison (precision 0.8) ==")
    r1 = run_config(precision=0.8)
    results["policy_comparison"] = r1
    print("exposed fraction:", r1["exposed_frac"])
    for p in ("P0", "P1", "P1g", "P2", "P3"):
        print(p, r1[p])

    print("\n== Experiment 2: precision sweep (P1g ref, P2 swept) ==")
    sweep = {}
    for prec in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        r = run_config(precision=prec, policies=("P1g", "P2"))
        sweep[prec] = r
        print(f"precision={prec}: P1g exp_delay={r['P1g']['exp_delay']} "
              f"P2 exp_delay={r['P2']['exp_delay']}")
    results["precision_sweep"] = {str(k): v for k, v in sweep.items()}

    print("\n== Experiment 3: lead-time sweep (precision 0.8) ==")
    leads = {"0-6": (0.0, 6.0), "6-18": (6.0, 18.0), "18-36": (18.0, 36.0)}
    lsweep = {}
    for name, lead in leads.items():
        r = run_config(precision=0.8, lead=lead, policies=("P1g", "P2"))
        lsweep[name] = r
        print(f"lead={name}h: P2 exp_delay={r['P2']['exp_delay']} "
              f"(P1g ref {r['P1g']['exp_delay']})")
    results["lead_sweep"] = lsweep

    with open("rerouting_results.json", "w") as f:
        json.dump(results, f, indent=1)
    print("\nWrote rerouting_results.json")


if __name__ == "__main__":
    main()
