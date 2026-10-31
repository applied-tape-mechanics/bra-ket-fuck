# `|BF>` (Bra-Ket-Fuck)

> **[Applied Tape Mechanics](https://github.com/applied-tape-mechanics)** — *Empirical computation and discrete field dynamics on minimal linear substrates.*

**A Minimalist 1D Pointer-Based Quantum Programming Language, Statevector Virtual Machine, and OpenQASM 3.0 Compiler.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Dependencies: Zero](https://img.shields.io/badge/Dependencies-Zero-brightgreen.svg)](#running-the-verification-suites)
[![Target: OpenQASM 3.0](https://img.shields.io/badge/Compiler-OpenQASM%203.0-purple.svg)](#compiling-to-openqasm-30-hardware-assembly)
[![BQP: Universal](https://img.shields.io/badge/Complexity-BQP%20Universal-orange.svg)](papers/bra_ket_fuck_technical_whitepaper.pdf)

> **What if Urban Müller's 1993 Brainfuck tape held entangled qubits instead of 8-bit bytes?**
>
> **`|BF>` (Bra-Ket-Fuck)** replaces the classical byte array with a linear $N$-qubit Hilbert register $\mathcal{H} = (\mathbb{C}^2)^{\otimes N}$ and lifts the 8 classical Brainfuck tokens into a **12-character Clifford+$T$ instruction set** capable of expressing **Shor's Prime Factorization Algorithm ($N = 15 \to 3 \times 5$) in 132 characters** (or **112 characters** on a 6-qubit coherent register) — with **zero ancilla qubits** and **zero external dependencies**. Try the **[Live Quantum Tape Workbench on GitHub Pages](https://applied-tape-mechanics.github.io/bra-ket-fuck/)** to step through statevectors, Bloch spheres, and Shor's algorithm directly in your browser.

---

## Why `|BF>` Matters: The 132-Token Shor's Algorithm

Below is the **complete, executable 132-token `|BF>` source code** for Shor's prime factorization of $N = 15$ (coprime base $a = 7$) using semiclassical single-control qubit recycling on a 5-qubit 1D quantum tape:

```text
>+<H[>^H>H<^>H<H^>^H>H<^>H<H^<^H>H<^>H<H^<]H.[>>>>+<<<<,]H>>>>[<<<<-->>>>,]<<<<[>^H>H<^>H<H^>^H>H<^>H<H^>^H>H<^>H<H^<<+>+>+>+<<<<]H.
```

Run it directly from your terminal using only standard Python 3 (no `numpy`, no `qiskit`, no `pip install`):

```bash
python src/braketfuck.py examples/shor_15_recycled_opt.bfk -q 5 -s 256 --shor
```

**Sample Output:**
```text
|BF> Dirac-Muller Quantum Tape VM | Register Width: N = 5 qubits | Tokens: 132
------------------------------------------------------------------------------
Measurement Transcript Histogram (256 shots):
  '00':   55 ( 21.5%) [########                                ] -> phase=0.00 (trivial branch, resample)
  '01':   69 ( 27.0%) [##########                              ] -> phase=0.50 (1/2), candidate r'=2 fails a^r'=1; multiple r=4 gives factors=[3, 5]
  '10':   72 ( 28.1%) [###########                             ] -> phase=0.25 (1/4), r=4, factors=[3, 5]
  '11':   60 ( 23.4%) [#########                               ] -> phase=0.75 (3/4), r=4, factors=[3, 5]
```

Every shot landing on odd harmonic $s \in \{1, 3\}$ (50.0% of all runs) directly yields exact phase $\phi \in \{0.25, 0.75\}$, verified order $r = 4$, and non-trivial prime factors $\gcd(7^{4/2} \pm 1, 15) = \{3, 5\}$. On harmonic $s = 2$ (`'01'`, 25.0% of runs), the reduced continued-fraction denominator $r' = 2$ fails the order check $7^2 \equiv 4 \not\equiv 1 \pmod{15}$, and testing small multiples $r = 2r' = 4$ recovers the full order and factors $\{3, 5\}$ (75.0% total recovery).

---

## Interactive Web Workbench (`index.html`)

Open [`index.html`](index.html) directly in any browser (even via `file://` — no web server or build step required), or use the hosted GitHub Pages Quantum Workbench.

- **Dual Desktop Themes**: Switch seamlessly between **OS 9** and **OS X**.
- **Live 1D Quantum Tape Visualizer**: Inspect per-qubit marginal probabilities $P(|0\rangle)$ and $P(|1\rangle)$ and active pointer head $p$.
- **Statevector & Multi-Shot Monte Carlo Sampler**: Run 1-shot exact statevector inspection or 4,096-shot measurement sampling with interactive Bar Chart, Shot-by-Shot Convergence Trace, Data Table views, and verified Shor continued-fractions factor extraction.
- **Built-in OpenQASM 3.0 Compiler Tab**: Compile any `|BF>` program into OpenQASM 3.0 with one click, including a gate-count / CNOT-equivalent summary and optional open-chain LNN routing (`SWAP` insertion).

---

## The 12-Character `|BF>` Instruction Set Architecture

`|BF>` preserves all 8 symbols of classical Brainfuck (`> < + - . , [ ]`) and introduces 4 quantum tokens (`H Z T ^`) to achieve fault-tolerant Clifford+$T$ universality with a nearest-neighbor native entangling gate (`^`) on a 1D circular quantum tape:

| Token | Category | Operation Name | Action at Pointer Head `p` | Classical BF Analogy |
| :---: | :--- | :--- | :--- | :--- |
| `>` | Pointer | Move Head Right | `p <- (p + 1) mod N` | `>` (increment pointer) |
| `<` | Pointer | Move Head Left | `p <- (p - 1) mod N` | `<` (decrement pointer) |
| `+` | Unitary | Pauli-X (Bit Flip) | `X_p = \|0><1\| + \|1><0\|` | `+` (increment cell mod 2) |
| `Z` | Unitary | Pauli-Z (Phase Flip) | `Z_p = diag(1, -1)` | Phase dual of `+` |
| `H` | Unitary | Hadamard Gate | `H_p = (\|0> + (-1)^b \|1>) / sqrt(2)` | Equal superposition |
| `T` | Unitary | pi/8 Phase Gate (`T`) | `T_p = diag(1, exp(i*pi/4))` | Fine phase increment (`+pi/4`) |
| `-` | Unitary | Adjoint Phase (`T†`) | `T†_p = diag(1, exp(-i*pi/4))` | `-` (phase decrement `-pi/4`) |
| `^` | Entangle | Adjacent CNOT | `CNOT_{p -> (p+1) mod N}` | Nearest-neighbor link |
| `[` | Control | Block Open | Coherent `C_p(U_body)` or Measured Loop | `[` (conditional entry) |
| `]` | Control | Block Close | Matching block delimiter (`Δp = 0`) | `]` (conditional exit) |
| `.` | I/O | Projective Measure | Measure `q_p` in Z-basis; emit `'0'` or `'1'` | `.` (output cell) |
| `,` | I/O | Active Reset | Reset `q_p -> \|0>` via measure-and-flip | `,` (clear / input cell) |

> **Syntactic Universality without Ancillas:**
> - Phase gate $S = T^2$ is `TT`, and inverse phase $S^\dagger = (T^\dagger)^2$ is `--`.
> - Reversed adjacent $\mathrm{CNOT}_{p+1 \to p}$ is synthesized via conjugating Hadamards: `H>H<^>H<H` (9 tokens).
> - Adjacent $\mathrm{SWAP}_{p, p+1}$ is synthesized in 7 tokens: `^>H^H<^`.

---

## Canonical Quantum Benchmark Gallery (`examples/`)

| Program | File | Qubits | Tokens | Description |
| :--- | :--- | :---: | :---: | :--- |
| **Bell State `\|Φ⁺>`** | [`examples/bell_pair.bfk`](examples/bell_pair.bfk) | 2 | **5** | `H^.>.` — Maximal 2-qubit entanglement |
| **3-Qubit GHZ State** | [`examples/ghz_3.bfk`](examples/ghz_3.bfk) | 3 | **10** | `H^>^<.>.>.` — Multipartite cat state |
| **Quantum Teleportation** | [`examples/teleportation.bfk`](examples/teleportation.bfk) | 3 | **28** | `+>H^<^H.>. [>+<+] < [>>Z<<+] >>.` — Dynamic feed-forward |
| **2-Qubit Grover Search** | [`examples/grover_2q.bfk`](examples/grover_2q.bfk) | 2 | **33** | Marks and amplifies `\|11>` to `P(\|11>) = 100%` |
| **Shor N=15 (5Q Opt)** | [`examples/shor_15_recycled_opt.bfk`](examples/shor_15_recycled_opt.bfk) | 5 | **132** | Subspace-reduced semiclassical recycled Shor |
| **Shor N=15 (6Q Full)** | [`examples/shor_15_full.bfk`](examples/shor_15_full.bfk) | 6 | **149** | Coherent 6-qubit Shor with exact `QFT_2†` |
| **Shor N=15 (6Q Opt)** | [`examples/shor_15_full_opt.bfk`](examples/shor_15_full_opt.bfk) | 6 | **112** | Same, with the provably idle `SWAP(y1,y3)` removed from `U_4` |
| **Shor N=15 (5Q General)** | [`examples/shor_15_recycled.bfk`](examples/shor_15_recycled.bfk) | 5 | **169** | General-oracle 5-qubit semiclassical recycled Shor |

---

## Compiling to OpenQASM 3.0 Hardware Assembly

Because the 1D pointer position $p$ is statically resolvable across every balanced `[...]` block ($\Delta p = 0$), `|BF>` compiles in $O(1)$ per token to **OpenQASM 3.0** dynamic circuits:

```bash
python src/braketfuck.py examples/shor_15_recycled_opt.bfk -q 5 --qasm      # emit OpenQASM 3.0
python src/braketfuck.py examples/shor_15_full.bfk -q 6 --report            # gate counts, CNOT-equivalents, depth
python src/braketfuck.py examples/shor_15_full.bfk -q 6 --report --no-optimize
python src/braketfuck.py examples/shor_15_full.bfk -q 6 --qasm --lnn         # route onto an open linear chain
python src/braketfuck.py examples/shor_15_full.bfk -q 6 --report --lnn
```

Coherent (Profile C) blocks are lowered with **conjugation-aware control**: by the identity
$C(VUV^{-1}) = V\,C(U)\,V^{-1}$, gates that are undone inside a block never receive the extra control.
For the 6-qubit Shor program this reduces the cost from 206 to 58 CNOT-equivalents (per-token vs.
conjugation-aware lowering; Toffoli = 6, controlled-phase = 2, CX/CZ/CH = 1). Note that coherent
control couples the control cell to non-adjacent cells, so Profile C blocks are not nearest-neighbor
operations. The `--lnn` mode (and the "Route for linear chain" switch in the web IDE) makes this
explicit: it decomposes every 3+-qubit gate exactly into 1-/2-qubit gates and inserts SWAPs so that
every 2-qubit gate acts on adjacent qubits of an open chain. The 6-qubit Shor program then needs 22
SWAPs and 124 CNOT-equivalents (the optimized 5-qubit recycled program: 17 SWAPs, 93).

---

## Docker Setup (GHCR & Docker Compose)

A pre-built container image is published to **GitHub Container Registry (`ghcr.io`)**:

```bash
# Run the 132-token Shor N=15 factorization directly from GHCR
docker run --rm ghcr.io/applied-tape-mechanics/bra-ket-fuck:latest

# Compile any built-in example to OpenQASM 3.0 with LNN routing
docker run --rm ghcr.io/applied-tape-mechanics/bra-ket-fuck:latest \
  /app/examples/shor_15_full.bfk -q 6 --qasm --lnn
```

### Using Docker Compose

```bash
# Run the full Python + Node.js + Differential Fuzzing test suite in Docker
docker compose run --rm test

# Run the CLI runner via Docker Compose
docker compose run --rm bra-ket-fuck

# Serve the interactive Quantum Workbench on http://localhost:8085
docker compose up -d workbench
```

---

## Repository Structure

```text
bra-ket-fuck/
├── index.html                                    # Standalone Web IDE & Quantum Tape Visualizer (OS 9 / OS X)
├── README.md                                     # Documentation & Quickstart
├── Dockerfile                                    # Multi-stage container (test suite & production CLI/workbench)
├── docker-compose.yml                            # CLI runner, Web Workbench (port 8085) & verification runner
├── LICENSE                                       # MIT License
├── src/
│   ├── braketfuck.py                             # Zero-dependency Python 3 Quantum VM, Shor Analyzer & OpenQASM 3.0 CLI
│   └── braketfuck.js                             # Zero-dependency UMD JS Quantum VM (Browser & Node.js)
├── ui/
│   ├── bff-theme.css                             # OS 9 & OS X UI stylesheet
│   └── bff-ui.js                                 # Theme switcher, clipboard, download & toast controller
├── examples/
│   ├── bell_pair.bfk                             # 5-token Bell state |Phi+>
│   ├── ghz_3.bfk                                 # 10-token 3-qubit GHZ state
│   ├── teleportation.bfk                         # 28-token Quantum Teleportation with mid-circuit feed-forward
│   ├── grover_2q.bfk                             # 33-token 2-qubit Grover search algorithm
│   ├── shor_15_recycled_opt.bfk                  # 132-token 5-qubit subspace-reduced recycled Shor (N=15, a=7)
│   ├── shor_15_full.bfk                          # 149-token 6-qubit coherent full-register Shor (N=15, a=7)
│   ├── shor_15_full_opt.bfk                      # 112-token 6-qubit Shor without the idle SWAP(y1, y3)
│   └── shor_15_recycled.bfk                      # 169-token 5-qubit general-oracle recycled Shor (N=15, a=7)
├── papers/
│   ├── bra_ket_fuck_technical_whitepaper.pdf     # Formal Language Specification & BQP Universality Whitepaper (PDF)
│   ├── bra_ket_fuck_technical_whitepaper.tex     # LaTeX source for the Technical Whitepaper
│   ├── shors_algorithm_bra_ket_fuck.pdf          # Shor's Algorithm in |BF>: 6Q Coherent & 5Q Recycled Synthesis (PDF)
│   ├── shors_algorithm_bra_ket_fuck.tex          # LaTeX source for the Shor's Algorithm Paper
│   └── generated/shor_resources.tex              # Resource table, AUTO-GENERATED from the transpiler
├── tools/
│   └── gen_paper_tables.py                       # Regenerates (or --check's) the paper tables from the code
└── tests/
    ├── test_vm.py                                # Python 3 automated verification suite (unittest)
    ├── test_vm.js                                # Node.js automated verification suite (assert)
    ├── test_fuzz.py                              # Differential fuzzing: VM vs. emitted QASM vs. Python/JS transpilers
    └── qasm_interpreter.py                       # Independent exact interpreter for the emitted OpenQASM subset
```

---

## Running the Verification Suites

Both the Python 3 and Node.js test suites run out-of-the-box with zero third-party packages:

```bash
# Run Python 3 verification suite (20 tests)
python tests/test_vm.py

# Run Node.js verification suite (13 suites)
node tests/test_vm.js

# Differential fuzzing (400 random programs; exact distributions, statevectors, Python == JS)
python tests/test_fuzz.py

# Check that the paper's resource table matches the current transpiler
python tools/gen_paper_tables.py --check
```

---

## Research Whitepapers Included

1. **[`|BF>` (Bra-Ket-Fuck): A Minimalist 1D Pointer-Based Quantum Programming Language](papers/bra_ket_fuck_technical_whitepaper.pdf)** — Defines the Dirac–Müller Abstract Machine (DMM), proves BQP universality with a nearest-neighbor native CNOT, formalizes the Coherent (Profile C) and Dynamic Copenhagen (Profile D) loop semantics, and specifies the OpenQASM 3.0 transpiler.
2. **[Implementing Shor's Factoring Algorithm in `|BF>` (Bra-Ket-Fuck)](papers/shors_algorithm_bra_ket_fuck.pdf)** — Presents the complete algebraic and circuit synthesis of Shor's algorithm for $N = 15$ ($a = 7$) on a 6-qubit register (149 tokens; 112 optimized) and a 5-qubit recycled register (169 tokens general / 132 tokens subspace-optimized), including exact statevector validation across all four quantum phase estimation branches.
