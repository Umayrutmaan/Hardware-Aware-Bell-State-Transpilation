import matplotlib

matplotlib.use('Agg')

import numpy as np

import matplotlib.pyplot as plt

import matplotlib.patches as mpatches

from qiskit import QuantumCircuit, transpile

from qiskit_aer import AerSimulator

from qiskit_aer.noise import NoiseModel, depolarizing_error, thermal_relaxation_error

from qiskit_ibm_runtime.fake_provider import FakeVigoV2 as FakeVigo



SHOTS = 10_000

N_RUNS = 10





# bell circuit

def make_bell_circuit():

    # H on q0 then CNOT -> |00> + |11> / sqrt(2)

    qc = QuantumCircuit(2, 2)

    qc.h(0)

    qc.cx(0, 1)

    qc.measure([0, 1], [0, 1])

    return qc





# custom noise model

def build_custom_noise():

    # chose these cuz ibm uses smth similar for superconducting qubits

    # physical constraint T2 <= 2*T1, took time to figre this out

    nm = NoiseModel()



    T1 = 30e-6  # longitudinal relaxation (sec)

    T2 = 50e-6  # dephasing, must be < 2*T1

    t_h = 0.3e-6  # single qubit gate time

    t_cx = 0.6e-6  # 2q gate slower than 1q



    # thermal relax first then depolarizing on top, order matters

    th_h = thermal_relaxation_error(T1, T2, t_h)

    th_cx = thermal_relaxation_error(T1, T2, t_cx).tensor(thermal_relaxation_error(T1, T2, t_cx))



    h_err = th_h.compose(depolarizing_error(0.081, 1))

    cx_err = th_cx.compose(depolarizing_error(0.151, 2))



    nm.add_all_qubit_quantum_error(h_err, ['h'])

    nm.add_all_qubit_quantum_error(cx_err, ['cx'])



    # readout matrix, row=prepared col=measured

    nm.add_readout_error([[0.921, 0.079], [0.079, 0.921]], [0])

    nm.add_readout_error([[0.941, 0.059], [0.059, 0.941]], [1])



    return nm, [[0, 1], [1, 0]], ['h', 'cx', 'measure', 'id', 'reset']





def build_fakevigo_noise():

    # pulls real calibration from ibm fakevigo, not sure if best but works

    backend = FakeVigo()

    nm = NoiseModel.from_backend(backend)

    return nm, list(backend.coupling_map.get_edges()), nm.basis_gates





# run the simulation N_RUNS times, return bmf array + last counts

def run_trials(noise_model, coupling_map, basis_gates, label=""):

    # transpile once reuse for all runs, saves time

    sim = AerSimulator(noise_model=noise_model, coupling_map=coupling_map, basis_gates=basis_gates)

    circuit = transpile(make_bell_circuit(), backend=sim, optimization_level=1, initial_layout=[0, 1])



    bmf = np.empty(N_RUNS)

    last_ct = {}



    for i in range(N_RUNS):

        counts = sim.run(circuit, shots=SHOTS).result().get_counts()

        last_ct = counts

        bmf[i] = (counts.get('00', 0) + counts.get('11', 0)) / SHOTS

        print(f"  [{label}] run {i+1:02d}/{N_RUNS}  BMF={bmf[i]:.4f}  {dict(counts)}")



    return bmf, last_ct, circuit





# plot 4 panels

def plot_results(res, filename="Bell_state_bmf_analysis.png"):

    STATES = ['00', '01', '10', '11']

    BELL = {'00', '11'}

    names = list(res.keys())

    colors = ['#2980b9', '#c0392b']



    fig, axes = plt.subplots(2, 2, figsize=(13, 9))

    fig.suptitle("Bell State BMF: Custom Noise vs FakeVigoV2", fontsize=14, fontweight='bold')

    ax1, ax2, ax3, ax4 = axes.flat



    # panel 1 - mean bmf with errorbars

    means = [res[n]['bmf_mean'] for n in names]

    stds = [res[n]['bmf_std'] for n in names]

    bars = ax1.bar(names, means, yerr=stds, color=colors, alpha=0.8, edgecolor='black', capsize=8, width=0.5, error_kw={'linewidth': 2})

    ax1.axhline(1.0, color='green', linestyle='--', alpha=0.6, label='Ideal')

    ax1.set_ylim(0, 1.12)

    ax1.set_ylabel('BMF (mean +/- 1std)')

    ax1.set_title('Bell Measurement Fidelity')

    ax1.legend(fontsize=9)

    for bar, m, s in zip(bars, means, stds):

        ax1.text(bar.get_x() + bar.get_width()/2, m + s + 0.02, f'{m:.4f}\n+/-{s:.4f}', ha='center', fontsize=9, fontweight='bold')



    # panel 2 - error rate = 1 - bmf

    e_means = [res[n]['err_mean'] for n in names]

    e_stds = [res[n]['err_std'] for n in names]

    b2 = ax2.bar(names, e_means, yerr=e_stds, color=['#e67e22', '#c0392b'], alpha=0.8, edgecolor='black', capsize=8, width=0.5, error_kw={'linewidth': 2})

    ax2.set_ylabel('Error Rate (1 - BMF)')

    ax2.set_title('Mean Error Rate')

    for bar, m, s in zip(b2, e_means, e_stds):

        ax2.text(bar.get_x() + bar.get_width()/2, m + s + 0.005, f'{m:.4f}\n+/-{s:.4f}', ha='center', fontsize=9, fontweight='bold')



    # panel 3 - scatter of each run's bmf value, seed=42 so jitter is reproducible

    rng = np.random.default_rng(42)

    x_pos = {'Custom': 1, 'FakeVigo': 2}

    for name, col in zip(names, colors):

        xc = x_pos[name]

        x = xc + rng.uniform(-0.08, 0.08, N_RUNS)

        m = res[name]['bmf_mean']

        s = res[name]['bmf_std']

        ax3.scatter(x, res[name]['bmf_runs'], color=col, alpha=0.8, s=55, label=name)

        ax3.hlines(m, xc-0.22, xc+0.22, colors=col, linewidth=2.5)

        ax3.hlines([m-s, m+s], xc-0.14, xc+0.14, colors=col, linewidth=1.5, linestyle='--')

    ax3.set_xticks([1, 2])

    ax3.set_xticklabels(names)

    ax3.set_ylabel('BMF')

    ax3.set_title(f'Per-Run BMF ({N_RUNS} runs, {SHOTS} shots each)')

    ax3.set_xlim(0.5, 2.5)

    ax3.legend(fontsize=9)



    # panel 4 - outcome probs from last run

    bar_w = 0.35

    x = np.arange(len(STATES))

    sc = ['#27ae60' if s in BELL else '#e74c3c' for s in STATES]

    for k, (name, col, offset) in enumerate(zip(names, colors, [-bar_w/2, bar_w/2])):

        ct = res[name]['last_counts']

        tot = sum(ct.get(s, 0) for s in STATES)

        probs = [ct.get(s, 0)/tot for s in STATES]

        ax4.bar(x + offset, probs, width=bar_w, color=sc, alpha=0.75 - k*0.15, edgecolor='black', label=name)

    ax4.set_xticks(x)

    ax4.set_xticklabels([f'|{s}>' for s in STATES])

    ax4.set_ylabel('Probability')

    ax4.set_title('Outcome Dist. (last run)')

    gp = mpatches.Patch(color='#27ae60', alpha=0.75, label='Bell |00>,|11>')

    rp = mpatches.Patch(color='#e74c3c', alpha=0.75, label='Error |01>,|10>')

    ax4.legend(handles=[gp, rp], fontsize=8)



    plt.tight_layout()

    plt.savefig(filename, dpi=150, bbox_inches='tight')

    print(f"\nsaved plot: {filename}")





def main():

    print("="*55)

    print("Bell State BMF Analysis")

    print(f"shots={SHOTS}  runs={N_RUNS}")

    print("BMF = P(00)+P(11), not real fidelity")

    print("="*55)



    # run custom noise first

    print("\n--- custom noise model (T1=30us T2=50us) ---")

    c_nm, c_cmap, c_bg = build_custom_noise()

    bmf_c, ct_c, qc_c = run_trials(c_nm, c_cmap, c_bg, label="Custom")



    bmf_mean_c = np.mean(bmf_c)

    bmf_std_c = np.std(bmf_c, ddof=1)

    err_c = 1.0 - bmf_c



    print(f"\n BMF={bmf_mean_c:.4f} +/- {bmf_std_c:.4f}")

    print(f" err={np.mean(err_c):.4f} +/- {np.std(err_c, ddof=1):.4f}")

    print(f" depth={qc_c.depth()}  ops={dict(qc_c.count_ops())}")



    # now fakevigo

    print("\n--- FakeVigoV2 (real ibm calibration) ---")

    v_nm, v_cmap, v_bg = build_fakevigo_noise()

    print(f" basis: {v_bg}")

    bmf_v, ct_v, qc_v = run_trials(v_nm, v_cmap, v_bg, label="FakeVigo")



    bmf_mean_v = np.mean(bmf_v)

    bmf_std_v = np.std(bmf_v, ddof=1)

    err_v = 1.0 - bmf_v



    print(f"\n BMF={bmf_mean_v:.4f} +/- {bmf_std_v:.4f}")

    print(f" err={np.mean(err_v):.4f} +/- {np.std(err_v, ddof=1):.4f}")

    print(f" depth={qc_v.depth()}  ops={dict(qc_v.count_ops())}")



    results = {

        "Custom": {

            "bmf_mean": bmf_mean_c, "bmf_std": bmf_std_c,

            "err_mean": np.mean(err_c), "err_std": np.std(err_c, ddof=1),

            "bmf_runs": bmf_c, "last_counts": ct_c,

        },

        "FakeVigo": {

            "bmf_mean": bmf_mean_v, "bmf_std": bmf_std_v,

            "err_mean": np.mean(err_v), "err_std": np.std(err_v, ddof=1),

            "bmf_runs": bmf_v, "last_counts": ct_v,

        },

    }



    print("\n" + "="*55)

    print("RESULTS")

    print("="*55)

    for name, r in results.items():

        print(f"\n{name}:")

        print(f"  BMF = {r['bmf_mean']:.4f} +/- {r['bmf_std']:.4f}")

        print(f"  err = {r['err_mean']:.4f} +/- {r['err_std']:.4f}")

        tot = sum(r['last_counts'].get(s, 0) for s in ['00','01','10','11'])

        for s in ['00','01','10','11']:

            c = r['last_counts'].get(s, 0)

            tag = "ok" if s in ('00','11') else "err"

            print(f"  |{s}>: {c}  ({c/tot*100:.1f}%)  [{tag}]")



    print(f"\ndelta BMF = {bmf_mean_c - bmf_mean_v:+.4f}  (custom - fakevigo)")

    print("note: BMF != fidelity, need tomography for actual fidelity")

    print("="*55)



    plot_results(results)

    print("done")





if __name__ == "__main__":

    main() 

