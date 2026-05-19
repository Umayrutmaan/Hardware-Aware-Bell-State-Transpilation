# GitHub Publishing Guide

Use a **repository**, not a GitHub Project. A repository is the correct place for your bachelor's monograph code, data, results, figures, and PDF.

## Recommended Repository Name

Good options:

```text
bell-state-hardware-aware-transpilation
quantum-bell-transpilation-benchmark
hardware-aware-bell-state-benchmark
```

The first one is the clearest.

## Before Uploading

Put your files in this structure:

```text
src/bell_benchmark.py
results/final_journal_data.csv
results/benchmark_metadata.json
figures/*.png
figures/*.pdf
docs/monograph.pdf
docs/figure_captions.md
```

If your benchmark script currently lives in Colab, download it as a `.py` file and save it as:

```text
src/bell_benchmark.py
```

## Option A: Publish Using GitHub Website

1. Go to GitHub.
2. Click **New repository**.
3. Repository name: `bell-state-hardware-aware-transpilation`.
4. Description:

```text
Bachelor's monograph project benchmarking hardware-aware Bell-state transpilation under heterogeneous noise using Qiskit.
```

5. Choose **Public**.
6. Do not add another README if you are uploading this folder, because this repository already has one.
7. Create the repository.
8. Upload this folder's files.
9. Commit with a message like:

```text
Initial release of Bell-state transpilation benchmark
```

## Option B: Publish Using Git Commands

Run these from the repository folder:

```bash
git init
git add .
git commit -m "Initial release of Bell-state transpilation benchmark"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/bell-state-hardware-aware-transpilation.git
git push -u origin main
```

Replace `YOUR-USERNAME` with your GitHub username.

## What to Put in the GitHub Description

Use this:

```text
Bachelor's monograph project on hardware-aware Bell-state transpilation under heterogeneous noise using Qiskit and FakeJakartaV2.
```

## Suggested Topics

Add these GitHub topics:

```text
quantum-computing
qiskit
transpilation
bell-states
noise-model
quantum-simulation
bachelor-thesis
research-project
```

## Important Presentation Advice

Do not oversell the result. Present it as a controlled simulation benchmark.

Strong wording:

```text
This project investigates how hardware-aware initial layout selection affects Bell-state transpilation performance under a heterogeneous depolarizing noise model.
```

Avoid wording like:

```text
This proves hardware-aware transpilation is always better.
```

## Final Checklist

- README explains the project clearly.
- Benchmark code is included.
- CSV data is included.
- Metadata JSON is included.
- Figures are included as PNG and PDF.
- Monograph PDF is included.
- Limitations are stated honestly.
- Repository is public.
- The README has a reproducibility command.
