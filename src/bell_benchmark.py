"""Benchmark Bell-state transpilation on a noisy fake-backend topology."""


from __future__ import annotations

import argparse
import json
import warnings
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np
import random
import pandas as pd
import seaborn as sns
from qiskit import QuantumCircuit, transpile
from qiskit.quantum_info import DensityMatrix, state_fidelity
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error

try:
    from qiskit_ibm_runtime.fake_provider import FakeJakartaV2
except ImportError as exc:  # pragma: no cover - user environment guard
    raise SystemExit(
        "qiskit-ibm-runtime is required for FakeJakartaV2. "
        "Install with: pip install -r requirements.txt"
    ) from exc


warnings.filterwarnings("ignore", category=UserWarning)

SEED = 42
BASIS_GATES = ["id", "rz", "sx", "x", "cx"]
BELL_STATES = ["phi_plus", "phi_minus", "psi_plus", "psi_minus"]
OPTIMIZATION_LEVELS = [1, 2, 3]
ROUTING_METHODS = ["sabre", "lookahead"]
NOISE_ADAPTIVE_SETTINGS = [True, False]
DEFAULT_NOISE_LEVELS = np.round(np.arange(0.01, 0.101, 0.01), 2)


@dataclass(frozen=True)
class HardwareErrorProfile:
    """Container for a synthetic, heterogeneous noise profile built from a fake backend topology."""

    backend_name: str
    num_qubits: int
    directed_edges: Tuple[Tuple[int, int], ...]
    undirected_edges: Tuple[Tuple[int, int], ...]
    blind_layout: Tuple[int, int]
    adaptive_layout: Tuple[int, int]
    adaptive_path: Tuple[int, ...]
    one_qubit_scale: Mapping[int, float]
    cx_scale: Mapping[Tuple[int, int], float]


def package_versions() -> Dict[str, str]:
    packages = [
        "qiskit",
        "qiskit-aer",
        "qiskit-ibm-runtime",
        "numpy",
        "pandas",
        "scipy",
        "matplotlib",
        "seaborn",
    ]
    versions = {}
    for package in packages:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = "not installed"
    return versions


np.random.seed(SEED)
random.seed(SEED)


def backend_name(backend) -> str:
    name = getattr(backend, "name", "unknown_backend")
    return name() if callable(name) else str(name)


def unique_undirected_edges(directed_edges: Iterable[Tuple[int, int]]) -> Tuple[Tuple[int, int], ...]:
    return tuple(sorted({tuple(sorted((int(u), int(v)))) for u, v in directed_edges if u != v}))


def graph_from_edges(edges: Sequence[Tuple[int, int]]) -> Dict[int, List[int]]:
    graph: Dict[int, List[int]] = {}
    for u, v in edges:
        graph.setdefault(u, []).append(v)
        graph.setdefault(v, []).append(u)
    return {node: sorted(neighbors) for node, neighbors in graph.items()}


def simple_paths_of_length(
    graph: Mapping[int, Sequence[int]], path_length_edges: int
) -> List[Tuple[int, ...]]:
    paths: List[Tuple[int, ...]] = []
    for start in sorted(graph):
        stack = [(start, (start,))]
        while stack:
            node, path = stack.pop()
            if len(path) == path_length_edges + 1:
                if path[0] < path[-1]:
                    paths.append(path)
                continue
            for neighbor in graph[node]:
                if neighbor not in path:
                    stack.append((neighbor, path + (neighbor,)))
    return sorted(set(paths))


def edge_key(u: int, v: int) -> Tuple[int, int]:
    return tuple(sorted((int(u), int(v))))


def build_error_profile(backend) -> HardwareErrorProfile:
    """Build a noise profile with one deliberately high-error edge (blind layout) and one low-error two-hop path (adaptive layout)."""

    coupling_map = backend.coupling_map
    directed_edges = tuple((int(u), int(v)) for u, v in coupling_map.get_edges())
    undirected_edges = unique_undirected_edges(directed_edges)
    graph = graph_from_edges(undirected_edges)

    if not undirected_edges:
        raise ValueError("Backend coupling map has no two-qubit edges.")

    
    blind_edge = undirected_edges[0]
    length_two_paths = [
        path
        for path in simple_paths_of_length(graph, 2)
        if blind_edge not in {edge_key(path[0], path[1]), edge_key(path[1], path[2])}
    ]
    if length_two_paths:
        adaptive_path = length_two_paths[-1]
    else:
        adaptive_path = undirected_edges[-1]

    adaptive_layout = (adaptive_path[0], adaptive_path[-1])

    one_qubit_scale = {
        qubit: 1.0 + 0.08 * (((qubit * 37) % 5) - 2)
        for qubit in range(backend.num_qubits)
    }
    for qubit in blind_edge:
        one_qubit_scale[qubit] = max(one_qubit_scale[qubit], 1.28)
    for qubit in adaptive_path:
        one_qubit_scale[qubit] = min(one_qubit_scale[qubit], 0.76)

    cx_scale = {edge: 1.35 for edge in undirected_edges}
    cx_scale[blind_edge] = 5.8
    adaptive_edges = {edge_key(u, v) for u, v in zip(adaptive_path[:-1], adaptive_path[1:])}
    for edge in adaptive_edges:
        cx_scale[edge] = 0.42

    return HardwareErrorProfile(
        backend_name=backend_name(backend),
        num_qubits=backend.num_qubits,
        directed_edges=directed_edges,
        undirected_edges=undirected_edges,
        blind_layout=blind_edge,
        adaptive_layout=adaptive_layout,
        adaptive_path=tuple(adaptive_path),
        one_qubit_scale=one_qubit_scale,
        cx_scale=cx_scale,
    )


def create_bell_state_circuit(state_name: str, measured: bool = False) -> QuantumCircuit:
    """Create one of the four Bell states on two logical qubits."""

    if state_name not in BELL_STATES:
        raise ValueError(f"Unknown Bell state {state_name!r}.")

    qc = QuantumCircuit(2, 2 if measured else 0)
    qc.h(0)
    qc.cx(0, 1)

    if state_name == "phi_minus":
        qc.z(0)
    elif state_name == "psi_plus":
        qc.x(1)
    elif state_name == "psi_minus":
        qc.x(1)
        qc.z(0)

    if measured:
        qc.measure([0, 1], [0, 1])

    return qc


def create_noise_model(profile: HardwareErrorProfile, p_noise: float) -> NoiseModel:
    """Return a depolarizing noise model where 1-qubit and CX errors are scaled by topology-dependent factors; RZ is treated as ideal."""

    noise_model = NoiseModel(basis_gates=BASIS_GATES)

    for qubit in range(profile.num_qubits):
        p1 = min(float(p_noise) * profile.one_qubit_scale[qubit], 0.999)
        if p1 > 0:
            one_qubit_error = depolarizing_error(p1, 1)
            for gate in ["id", "sx", "x"]:
                noise_model.add_quantum_error(one_qubit_error, [gate], [qubit])

    for directed_edge in profile.directed_edges:
        undirected = edge_key(*directed_edge)
        p2 = min(float(p_noise) * 1.5 * profile.cx_scale[undirected], 0.999)
        if p2 > 0:
            two_qubit_error = depolarizing_error(p2, 2)
            noise_model.add_quantum_error(two_qubit_error, ["cx"], list(directed_edge))

    return noise_model


def initial_layout_for(profile: HardwareErrorProfile, noise_adaptive: bool) -> List[int]:
    """Return logical-to-physical initial layout for two logical Bell qubits."""

    layout = profile.adaptive_layout if noise_adaptive else profile.blind_layout
    return [int(layout[0]), int(layout[1])]


def transpile_bell_circuit(
    circuit: QuantumCircuit,
    backend,
    profile: HardwareErrorProfile,
    optimization_level: int,
    routing_method: str,
    noise_adaptive: bool,
) -> QuantumCircuit:
    """Transpile using either blind or error-aware initial layout."""

    return transpile(
        circuit,
        backend=backend,
        initial_layout=initial_layout_for(profile, noise_adaptive),
        optimization_level=optimization_level,
        routing_method=routing_method,
        seed_transpiler=SEED,
    )


def density_matrix_from_circuit(
    transpiled_circuit: QuantumCircuit,
    simulator: AerSimulator,
) -> DensityMatrix:
    qc = transpiled_circuit.copy()
    qc.save_density_matrix(label="rho")
    result = simulator.run(qc, seed_simulator=SEED).result()
    return DensityMatrix(result.data(0)["rho"])


def success_rate_from_counts(state_name: str, counts: Mapping[str, int], shots: int) -> float:
    if state_name in {"phi_plus", "phi_minus"}:
        correct = counts.get("00", 0) + counts.get("11", 0)
    else:
        correct = counts.get("01", 0) + counts.get("10", 0)
    return correct / shots


def run_single_configuration(
    backend,
    profile: HardwareErrorProfile,
    ideal_cache: Dict[Tuple[str, int, str, bool], Tuple[QuantumCircuit, DensityMatrix]],
    p_noise: float,
    state_name: str,
    optimization_level: int,
    routing_method: str,
    noise_adaptive: bool,
    shots: int,
) -> Dict[str, object]:
    cache_key = (state_name, optimization_level, routing_method, noise_adaptive)

    if cache_key not in ideal_cache:
        ideal_circuit = create_bell_state_circuit(state_name, measured=False)
        transpiled_ideal = transpile_bell_circuit(
            ideal_circuit,
            backend,
            profile,
            optimization_level,
            routing_method,
            noise_adaptive,
        )
        ideal_simulator = AerSimulator(method="density_matrix", basis_gates=BASIS_GATES)
        ideal_density_matrix = density_matrix_from_circuit(transpiled_ideal, ideal_simulator)
        ideal_cache[cache_key] = (transpiled_ideal, ideal_density_matrix)

    transpiled_ideal, ideal_density_matrix = ideal_cache[cache_key]

    noise_model = create_noise_model(profile, p_noise)
    noisy_simulator = AerSimulator(
        method="density_matrix",
        noise_model=noise_model,
        basis_gates=BASIS_GATES,
    )

    noisy_density_matrix = density_matrix_from_circuit(transpiled_ideal, noisy_simulator)
    fidelity = float(state_fidelity(noisy_density_matrix, ideal_density_matrix))

    measured_circuit = create_bell_state_circuit(state_name, measured=True)
    transpiled_measured = transpile_bell_circuit(
        measured_circuit,
        backend,
        profile,
        optimization_level,
        routing_method,
        noise_adaptive,
    )
    counts = noisy_simulator.run(
        transpiled_measured,
        shots=shots,
        seed_simulator=SEED,
    ).result().get_counts(0)
    success_rate = success_rate_from_counts(state_name, counts, shots)
    ops = transpiled_ideal.count_ops()

    return {
        "p_noise": float(p_noise),
        "bell_state": state_name,
        "optimization_level": optimization_level,
        "routing_method": routing_method,
        "noise_adaptive": noise_adaptive,
        "fidelity": fidelity,
        "success_rate": success_rate,
        "depth": int(transpiled_ideal.depth()),
        "gate_count": int(sum(ops.values())),
        "cx_count": int(ops.get("cx", 0)),
        "sx_count": int(ops.get("sx", 0)),
        "x_count": int(ops.get("x", 0)),
        "rz_count": int(ops.get("rz", 0)),
        "initial_layout": str(initial_layout_for(profile, noise_adaptive)),
        "adaptive_path": str(list(profile.adaptive_path)),
        "blind_layout": str(list(profile.blind_layout)),
    }


def run_full_experiment(shots: int, noise_levels: Sequence[float]) -> Tuple[pd.DataFrame, HardwareErrorProfile]:
    backend = FakeJakartaV2()
    profile = build_error_profile(backend)
    ideal_cache: Dict[Tuple[str, int, str, bool], Tuple[QuantumCircuit, DensityMatrix]] = {}

    print("Running Bell-state transpilation benchmark...")
    print(f"Backend: {profile.backend_name} ({profile.num_qubits} qubits)")
    print(f"Blind layout: {profile.blind_layout}, Adaptive layout: {profile.adaptive_layout}")

    rows: List[Dict[str, object]] = []
    total_runs = (
        len(noise_levels)
        * len(BELL_STATES)
        * len(OPTIMIZATION_LEVELS)
        * len(ROUTING_METHODS)
        * len(NOISE_ADAPTIVE_SETTINGS)
    )

    completed = 0
    for p_noise in noise_levels:
        for state_name in BELL_STATES:
            for optimization_level in OPTIMIZATION_LEVELS:
                for routing_method in ROUTING_METHODS:
                    for noise_adaptive in NOISE_ADAPTIVE_SETTINGS:
                        rows.append(
                            run_single_configuration(
                                backend=backend,
                                profile=profile,
                                ideal_cache=ideal_cache,
                                p_noise=float(p_noise),
                                state_name=state_name,
                                optimization_level=optimization_level,
                                routing_method=routing_method,
                                noise_adaptive=noise_adaptive,
                                shots=shots,
                            )
                        )
                        completed += 1
        print(f"Completed p={p_noise:.2f} ({completed}/{total_runs} configurations)")

    return pd.DataFrame(rows), profile





def run_sanity_checks(df: pd.DataFrame, profile: HardwareErrorProfile) -> None:
    expected_rows = (
        len(DEFAULT_NOISE_LEVELS)
        * len(BELL_STATES)
        * len(OPTIMIZATION_LEVELS)
        * len(ROUTING_METHODS)
        * len(NOISE_ADAPTIVE_SETTINGS)
    )
    if len(df) != expected_rows:
        raise AssertionError(f"Expected {expected_rows} rows, got {len(df)}.")
    if not df["fidelity"].between(0.0, 1.0).all():
        raise AssertionError("Fidelity values must be in [0, 1].")
    if not df["success_rate"].between(0.0, 1.0).all():
        raise AssertionError("Success-rate values must be in [0, 1].")
    if profile.blind_layout == profile.adaptive_layout:
        raise AssertionError("Blind and adaptive layouts are identical; no adaptation is being tested.")
    if df[["depth", "gate_count"]].isna().any().any():
        raise AssertionError("Depth and gate-count columns must be populated.")


def create_figures(df: pd.DataFrame, out_dir: Path) -> None:
    sns.set_theme(context="paper", style="whitegrid", font_scale=1.15)
    plt.rcParams["figure.dpi"] = 180
    plt.rcParams["savefig.dpi"] = 300
    plt.rcParams["font.family"] = "serif"

    plot_df = df.copy()
    plot_df["Configuration"] = plot_df["noise_adaptive"].map(
        {True: "Adaptive (hardware-aware)", False: "Blind (standard)"}
    )
    plot_df["State Label"] = plot_df["bell_state"].str.replace("_", " ").str.title()
    plot_df["Routing Label"] = plot_df["routing_method"].str.title()

    plt.figure(figsize=(10, 6))
    sns.lineplot(
        data=plot_df,
        x="p_noise",
        y="fidelity",
        hue="Configuration",
        style="Configuration",
        markers=True,
        dashes=False,
        linewidth=2.4,
        errorbar="sd",
    )
    plt.title("Figure 1: Bell-State Fidelity Across Noise Regimes", fontweight="bold")
    plt.xlabel("Depolarizing Error Scale p")
    plt.ylabel("Density-Matrix Fidelity")
    plt.tight_layout()
    plt.savefig(out_dir / "Fig1_Fidelity_vs_Noise.png")
    plt.close()

    plt.figure(figsize=(11, 6))
    sns.barplot(
        data=plot_df,
        x="State Label",
        y="fidelity",
        hue="Configuration",
        errorbar="sd",
    )
    plt.title("Figure 2: Fidelity by Bell State", fontweight="bold")
    plt.xlabel("Bell State")
    plt.ylabel("Average Fidelity")
    plt.ylim(0.0, 1.0)
    plt.tight_layout()
    plt.savefig(out_dir / "Fig2_Bell_State_Performance.png")
    plt.close()

    pivot_best = plot_df[
        (plot_df["optimization_level"] == 3) & (plot_df["noise_adaptive"])
    ].pivot_table(index="p_noise", columns="State Label", values="fidelity", aggfunc="mean")
    plt.figure(figsize=(10, 8))
    sns.heatmap(pivot_best, annot=True, fmt=".3f", cmap="viridis", cbar_kws={"label": "Fidelity"})
    plt.title("Figure 3: Optimal Adaptive Configuration Heatmap", fontweight="bold")
    plt.xlabel("Bell State")
    plt.ylabel("Noise Level p")
    plt.tight_layout()
    plt.savefig(out_dir / "Fig3_Adaptive_Heatmap.png")
    plt.close()

    plt.figure(figsize=(10, 6))
    sns.pointplot(
        data=plot_df,
        x="p_noise",
        y="depth",
        hue="Configuration",
        dodge=True,
        errorbar="sd",
    )
    plt.title("Figure 4: Circuit Depth Overhead", fontweight="bold")
    plt.xlabel("Noise Level p")
    plt.ylabel("Transpiled Circuit Depth")
    plt.tight_layout()
    plt.savefig(out_dir / "Fig4_Circuit_Depth.png")
    plt.close()

    plt.figure(figsize=(11, 6))
    sns.violinplot(
        data=plot_df[plot_df["noise_adaptive"]],
        x="Routing Label",
        y="fidelity",
        hue="optimization_level",
        inner="quartile",
        palette="Blues",
    )
    plt.title("Figure 5: Routing-Method Stability in Adaptive Mode", fontweight="bold")
    plt.xlabel("Routing Method")
    plt.ylabel("Fidelity Distribution")
    plt.legend(title="Optimization")
    plt.tight_layout()
    plt.savefig(out_dir / "Fig5_Routing_Comparison.png")
    plt.close()

    plt.figure(figsize=(10, 6))
    sns.barplot(
        data=plot_df,
        x="optimization_level",
        y="fidelity",
        hue="Configuration",
        errorbar="sd",
    )
    plt.title("Figure 6: Optimization-Level Impact", fontweight="bold")
    plt.xlabel("Optimization Level")
    plt.ylabel("Average Fidelity")
    plt.ylim(0.0, 1.0)
    plt.tight_layout()
    plt.savefig(out_dir / "Fig6_Optimization_Impact.png")
    plt.close()
    # Figures 1-6 saved.


def write_metadata(profile: HardwareErrorProfile, out_dir: Path, shots: int) -> None:
    metadata_payload = {
        "versions": package_versions(),
        "seed": SEED,
        "shots": shots,
        "backend": profile.backend_name,
        "num_qubits": profile.num_qubits,
        "directed_edges": list(map(list, profile.directed_edges)),
        "blind_layout": list(profile.blind_layout),
        "adaptive_layout": list(profile.adaptive_layout),
        "adaptive_path": list(profile.adaptive_path),
        "one_qubit_scale": {str(k): v for k, v in profile.one_qubit_scale.items()},
        "cx_scale": {str(k): v for k, v in profile.cx_scale.items()},
        "noise_levels": [float(x) for x in DEFAULT_NOISE_LEVELS],
        "optimization_levels": OPTIMIZATION_LEVELS,
        "routing_methods": ROUTING_METHODS,
        "noise_adaptive_settings": NOISE_ADAPTIVE_SETTINGS,
    }
    with (out_dir / "benchmark_metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata_payload, handle, indent=2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shots", type=int, default=8192, help="Shots for measured success-rate runs.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("bell_benchmark_results"),
        help="Directory for CSV files and figures.",
    )
 
    args, _ = parser.parse_known_args()
    return args


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    df, profile = run_full_experiment(shots=args.shots, noise_levels=DEFAULT_NOISE_LEVELS)
    run_sanity_checks(df, profile)

    df.to_csv(args.out_dir / "final_journal_data.csv", index=False)
    write_metadata(profile, args.out_dir, args.shots)
    create_figures(df, args.out_dir)

    print(f"Results saved in {args.out_dir.resolve()}")


if __name__ == "__main__":
    main()
    
