#!/usr/bin/env python3
"""
|BF> (Bra-Ket-Fuck) Quantum Virtual Machine & OpenQASM 3.0 Transpiler.
Dirac-Muller Abstract Machine (DMM) reference implementation.
Zero external dependencies (Python 3 standard library only).
"""

import argparse
import cmath
import math
import random
import re
import sys
from fractions import Fraction
from typing import Dict, FrozenSet, List, Optional, Tuple

VALID_TOKENS = set("><+ZHT-^.,[]")

# Elementary single-qubit gates
INV_SQRT2 = 1.0 / math.sqrt(2.0)
GATE_X = ((0j, 1.0 + 0j), (1.0 + 0j, 0j))
GATE_Z = ((1.0 + 0j, 0j), (0j, -1.0 + 0j))
GATE_H = ((INV_SQRT2 + 0j, INV_SQRT2 + 0j), (INV_SQRT2 + 0j, -INV_SQRT2 + 0j))
GATE_T = ((1.0 + 0j, 0j), (0j, cmath.exp(1j * math.pi / 4.0)))
GATE_TDG = ((1.0 + 0j, 0j), (0j, cmath.exp(-1j * math.pi / 4.0)))


def clean_code(raw: str) -> str:
    """Strips # and // line comments, then filters to valid |BF> tokens."""
    no_comments = re.sub(r"(#|//).*$", "", raw, flags=re.MULTILINE)
    return "".join(c for c in no_comments if c in VALID_TOKENS)


def infer_qubit_count(code: str, minimum: int = 2) -> int:
    """Infers required tape register width N by dry-running pointer displacements."""
    tokens = clean_code(code)
    p = 0
    max_p = 0
    for c in tokens:
        if c == ">":
            p += 1
            if p > max_p:
                max_p = p
        elif c == "<":
            p = max(0, p - 1)
        elif c == "^":
            if p + 1 > max_p:
                max_p = p + 1
    return max(minimum, max_p + 1)


def match_brackets(tokens: str) -> Dict[int, int]:
    """Validates bracket balance and returns bidirectional jump map."""
    bmap: Dict[int, int] = {}
    stack: List[int] = []
    for idx, ch in enumerate(tokens):
        if ch == "[":
            stack.append(idx)
        elif ch == "]":
            if not stack:
                raise SyntaxError(f"Unmatched ']' at instruction index {idx}")
            open_idx = stack.pop()
            bmap[open_idx] = idx
            bmap[idx] = open_idx
    if stack:
        raise SyntaxError(f"Unmatched '[' at instruction index {stack[-1]}")
    return bmap


class BraKetFuckVM:
    """
    Dirac-Muller Abstract Machine (DMM) statevector simulator.
    Supports both Profile C (Coherent Bounded Unitary) and Profile D (Dynamic Copenhagen Loops).
    """

    def __init__(self, num_qubits: int = 6, seed: Optional[int] = None):
        if num_qubits < 1 or num_qubits > 20:
            raise ValueError("num_qubits must be between 1 and 20")
        self.num_qubits = num_qubits
        self.dim = 1 << num_qubits
        self.rng = random.Random(seed)
        self.reset()

    def reset(self) -> None:
        self.state: List[complex] = [0j] * self.dim
        self.state[0] = 1.0 + 0j  # Physical vacuum ground state |00...0>
        self.pointer: int = 0
        self.transcript: List[int] = []
        self.measurement_records: List[Tuple[int, int, float]] = []
        self.pre_measurement_state: Optional[List[complex]] = None

    def apply_1q(self, gate: Tuple[Tuple[complex, complex], Tuple[complex, complex]]) -> None:
        p = self.pointer
        bit_mask = 1 << (self.num_qubits - 1 - p)
        new_state = [0j] * self.dim
        g00, g01 = gate[0]
        g10, g11 = gate[1]
        for i in range(self.dim):
            amp = self.state[i]
            if amp == 0j:
                continue
            i0 = i & ~bit_mask
            i1 = i | bit_mask
            if i & bit_mask:
                new_state[i0] += g01 * amp
                new_state[i1] += g11 * amp
            else:
                new_state[i0] += g00 * amp
                new_state[i1] += g10 * amp
        self.state = new_state

    def apply_cnot(self) -> None:
        if self.num_qubits < 2:
            raise ValueError("'^' (CNOT) requires a tape of at least 2 qubits")
        p = self.pointer
        q_next = (p + 1) % self.num_qubits  # Ring topology: cell N-1 couples to cell 0
        ctrl_mask = 1 << (self.num_qubits - 1 - p)
        tgt_mask = 1 << (self.num_qubits - 1 - q_next)
        new_state = list(self.state)
        for i in range(self.dim):
            if (i & ctrl_mask) and not (i & tgt_mask):
                j = i | tgt_mask
                new_state[i], new_state[j] = new_state[j], new_state[i]
        self.state = new_state

    def measure_cell(self, p: int, forced_outcome: Optional[int] = None) -> Tuple[int, float]:
        mask = 1 << (self.num_qubits - 1 - p)
        prob0 = sum(abs(self.state[i]) ** 2 for i in range(self.dim) if not (i & mask))
        prob1 = sum(abs(self.state[i]) ** 2 for i in range(self.dim) if (i & mask))
        if forced_outcome is not None:
            m = forced_outcome
        else:
            m = 1 if self.rng.random() < prob1 else 0
        chosen_prob = prob1 if m == 1 else prob0
        if chosen_prob < 1e-12:
            m = 1 - m
            chosen_prob = prob1 if m == 1 else prob0
        norm = math.sqrt(max(chosen_prob, 1e-15))
        new_state = [0j] * self.dim
        for i in range(self.dim):
            b = 1 if (i & mask) else 0
            if b == m:
                new_state[i] = self.state[i] / norm
        self.state = new_state
        return m, chosen_prob

    def reset_cell(self, p: int) -> None:
        """Active reset (,): unconditionally projects and resets qubit p to |0>."""
        m, _ = self.measure_cell(p)
        if m == 1:
            old_p = self.pointer
            self.pointer = p
            self.apply_1q(GATE_X)
            self.pointer = old_p

    @staticmethod
    def is_coherent_block(body: str, start_p: int, num_qubits: int) -> bool:
        """
        Checks Profile C admissibility of a bracketed body ``[ body ]`` entered at cell start_p:
        1. No measurement (.) or reset (,) anywhere inside the body.
        2. Net pointer displacement delta_p == 0.
        3. No gate acts on the control cell start_p (nor on any enclosing control cell).
        4. Every nested block is itself Profile C admissible. (A nested Profile D loop would
           measure inside a coherently controlled branch, which is not a unitary operation.)
        """
        return BraKetFuckVM._coherent_check(body, start_p, num_qubits, frozenset((start_p,)))

    @staticmethod
    def _coherent_check(body: str, start_p: int, num_qubits: int, protected: frozenset) -> bool:
        if "." in body or "," in body:
            return False
        try:
            bmap = match_brackets(body)
        except SyntaxError:
            return False
        p = start_p
        i = 0
        while i < len(body):
            ch = body[i]
            if ch == ">":
                p = (p + 1) % num_qubits
            elif ch == "<":
                p = (p - 1) % num_qubits
            elif ch in "+ZHT-":
                if p in protected:
                    return False
            elif ch == "^":
                q_next = (p + 1) % num_qubits
                if p in protected or q_next in protected:
                    return False
            elif ch == "[":
                close_idx = bmap[i]
                inner = body[i + 1 : close_idx]
                # The nested control qubit is only read, so it may coincide with an enclosing control.
                if not BraKetFuckVM._coherent_check(inner, p, num_qubits, protected | {p}):
                    return False
                i = close_idx  # nested block has delta_p == 0
            i += 1
        return p == start_p

    def _execute_tokens(
        self,
        tokens: str,
        bmap: Dict[int, int],
        start: int,
        end: int,
        forced_outcomes: Optional[List[int]] = None,
        forced_idx_ref: Optional[List[int]] = None,
    ) -> None:
        if forced_idx_ref is None:
            forced_idx_ref = [0]
        i = start
        while i < end:
            c = tokens[i]
            if c == ">":
                self.pointer = (self.pointer + 1) % self.num_qubits
            elif c == "<":
                self.pointer = (self.pointer - 1) % self.num_qubits
            elif c == "+":
                self.apply_1q(GATE_X)
            elif c == "Z":
                self.apply_1q(GATE_Z)
            elif c == "H":
                self.apply_1q(GATE_H)
            elif c == "T":
                self.apply_1q(GATE_T)
            elif c == "-":
                self.apply_1q(GATE_TDG)
            elif c == "^":
                self.apply_cnot()
            elif c == ",":
                self.reset_cell(self.pointer)
            elif c == ".":
                if self.pre_measurement_state is None:
                    self.pre_measurement_state = list(self.state)
                fm = None
                if forced_outcomes is not None and forced_idx_ref[0] < len(forced_outcomes):
                    fm = forced_outcomes[forced_idx_ref[0]]
                    forced_idx_ref[0] += 1
                m, prob = self.measure_cell(self.pointer, fm)
                self.transcript.append(m)
                self.measurement_records.append((self.pointer, m, prob))
            elif c == "[":
                close_idx = bmap[i]
                body = tokens[i + 1 : close_idx]
                ctrl = self.pointer
                if self.is_coherent_block(body, ctrl, self.num_qubits):
                    # Profile C: Coherent Controlled Unitary C_p(U_B)
                    ctrl_mask = 1 << (self.num_qubits - 1 - ctrl)
                    sub_vm = BraKetFuckVM(self.num_qubits)
                    sub_vm.state = [
                        self.state[k] if (k & ctrl_mask) else 0j for k in range(self.dim)
                    ]
                    sub_vm.pointer = ctrl
                    sub_bmap = match_brackets(body)
                    sub_vm._execute_tokens(body, sub_bmap, 0, len(body))
                    for k in range(self.dim):
                        if k & ctrl_mask:
                            self.state[k] = sub_vm.state[k]
                else:
                    # Profile D: Dynamic Copenhagen measurement loop with Brainfuck semantics:
                    # '[' measures the cell under the head; on m=1 the body runs and ']' jumps
                    # back to '[', which re-measures the cell under the (possibly moved) head.
                    sub_bmap = match_brackets(body)
                    steps = 0
                    while True:
                        m, _ = self.measure_cell(self.pointer)
                        if m == 0:
                            break
                        steps += 1
                        if steps > 1024:
                            raise RuntimeError("Dynamic quantum loop exceeded 1024 iterations")
                        self._execute_tokens(body, sub_bmap, 0, len(body), forced_outcomes, forced_idx_ref)
                i = close_idx
            i += 1

    def run(self, code: str, forced_outcomes: Optional[List[int]] = None) -> str:
        self.reset()
        tokens = clean_code(code)
        bmap = match_brackets(tokens)
        self._execute_tokens(tokens, bmap, 0, len(tokens), forced_outcomes, [0])
        if self.pre_measurement_state is None:
            self.pre_measurement_state = list(self.state)
        return "".join(str(b) for b in self.transcript)

    def get_probabilities(self, use_pre_measurement: bool = False) -> List[Tuple[str, float, complex]]:
        vec = self.pre_measurement_state if (use_pre_measurement and self.pre_measurement_state) else self.state
        out = []
        for idx, amp in enumerate(vec):
            prob = abs(amp) ** 2
            if prob > 1e-6:
                bits = f"{idx:0{self.num_qubits}b}"
                out.append((bits, prob, amp))
        return out


#  ---------------------------------------------------------------------------------------------
#  OpenQASM 3.0 lowering
#
#  Internally every gate is normalised to (name, target, controls) with name in
#  {x, z, h, t, tdg, s, sdg}; '^' at p is ("x", p+1, {p}). Profile C blocks are lowered with a
#  conjugation-aware dynamic program based on the identity
#
#        C(V U V^-1) = V C(U) V^-1          (V, U arbitrary unitaries)
#
#  so gates that are undone later inside the block never need the extra control. For the SWAP
#  macro  ^ (H>H<^>H<H) ^  this yields CNOT . (H H) . Toffoli . (H H) . CNOT (8 CNOT-equivalents)
#  instead of 3 Toffolis + 4 controlled-H (22 CNOT-equivalents).
#  ---------------------------------------------------------------------------------------------

Gate = Tuple[str, int, FrozenSet[int]]

_TOKEN_GATE = {"+": "x", "Z": "z", "H": "h", "T": "t", "-": "tdg"}
_INVERSE = {"x": "x", "z": "z", "h": "h", "t": "tdg", "tdg": "t", "s": "sdg", "sdg": "s"}
_PHASE_EIGHTHS = {"t": 1, "s": 2, "z": 4, "sdg": 6, "tdg": 7}
_EIGHTHS_TO_GATES = {0: [], 1: ["t"], 2: ["s"], 3: ["z", "tdg"], 4: ["z"], 5: ["z", "t"], 6: ["sdg"], 7: ["tdg"]}
_MAX_DP_GATES = 120  # above this, Profile C bodies fall back to per-gate control


def _mcx_cost(k: int) -> int:
    """CNOT-equivalents of an X (or Z/H, up to local gates) with k controls."""
    if k <= 0:
        return 0
    if k == 1:
        return 1
    if k == 2:
        return 6
    return 12 * (k - 2) + 6  # ancilla-free linear-depth estimate


def gate_cost(name: str, k: int) -> int:
    """CNOT-equivalent cost of gate `name` with k controls (standard decompositions:
    CNOT/CZ/CH = 1, controlled-phase (T, T^dag, S, S^dag) = 2, Toffoli = 6)."""
    if k == 0:
        return 0
    if name in ("x", "z", "h"):
        return _mcx_cost(k)
    return 2 * _mcx_cost(k)


def _format_gate(gate: Gate) -> str:
    name, target, controls = gate
    cs = sorted(controls)
    k = len(cs)
    tq = f"q[{target}]"
    if k == 0:
        return f"{name} {tq};"
    cl = ", ".join(f"q[{c}]" for c in cs)
    if k == 1:
        native = {"x": "cx", "z": "cz", "h": "ch"}
        if name in native:
            return f"{native[name]} {cl}, {tq};"
        return f"ctrl @ {name} {cl}, {tq};"
    if k == 2 and name == "x":
        return f"ccx {cl}, {tq};"
    return f"ctrl({k}) @ {name} {cl}, {tq};"


def _fuse_phases(gates: List[Gate]) -> List[Gate]:
    """Merges adjacent diagonal phase gates on the same qubit/controls (e.g. T^dag T^dag -> S^dag)."""
    out: List[Gate] = []
    i = 0
    while i < len(gates):
        name, target, controls = gates[i]
        if name in _PHASE_EIGHTHS:
            total = 0
            j = i
            while (j < len(gates) and gates[j][0] in _PHASE_EIGHTHS
                   and gates[j][1] == target and gates[j][2] == controls):
                total += _PHASE_EIGHTHS[gates[j][0]]
                j += 1
            out.extend((g, target, controls) for g in _EIGHTHS_TO_GATES[total % 8])
            i = j
        else:
            out.append(gates[i])
            i += 1
    return out


def _lower_controlled(gates: List[Gate], ctrl: FrozenSet[int], optimize: bool = True) -> List[Gate]:
    """Returns a gate list implementing C_ctrl(gates)."""
    def full(g: Gate) -> Gate:
        return (g[0], g[1], g[2] | ctrl)

    n = len(gates)
    if not optimize or n == 0 or n > _MAX_DP_GATES:
        return [full(g) for g in gates]
    inv = [(_INVERSE[g[0]], g[1], g[2]) for g in gates]
    ucost = [gate_cost(g[0], len(g[2])) for g in gates]
    best: Dict[Tuple[int, int], Tuple[Tuple[int, int], tuple]] = {}
    for length in range(1, n + 1):
        for i in range(0, n - length + 1):
            j = i + length
            if length == 1:
                g = gates[i]
                best[(i, j)] = ((gate_cost(g[0], len(g[2] | ctrl)), 1), ("leaf",))
                continue
            cand_cost, cand_choice = None, None
            for k in range(i + 1, j):
                a, b = best[(i, k)][0], best[(k, j)][0]
                c = (a[0] + b[0], a[1] + b[1])
                if cand_cost is None or c < cand_cost:
                    cand_cost, cand_choice = c, ("split", k)
            uc = 0
            L = 1
            while 2 * L <= length and inv[i + L - 1] == gates[j - L]:
                uc += ucost[i + L - 1] + ucost[j - L]
                if 2 * L == length:
                    c = (0, 0)  # segment is V V^-1 = identity
                else:
                    inner = best[(i + L, j - L)][0]
                    c = (uc + inner[0], 2 * L + inner[1])
                if c < cand_cost:
                    cand_cost, cand_choice = c, ("conj", L)
                L += 1
            best[(i, j)] = (cand_cost, cand_choice)

    out: List[Gate] = []

    def build(i: int, j: int) -> None:
        choice = best[(i, j)][1]
        if choice[0] == "leaf":
            out.append(full(gates[i]))
        elif choice[0] == "split":
            build(i, choice[1])
            build(choice[1], j)
        else:
            L = choice[1]
            if 2 * L == j - i:
                return
            out.extend(gates[i:i + L])
            build(i + L, j - L)
            out.extend(gates[j - L:j])

    build(0, n)
    return out


def _lower_best(gates: List[Gate], ctrl: FrozenSet[int], optimize: bool = True) -> List[Gate]:
    """Lowers C_ctrl(gates) with and without phase fusion and keeps the cheaper result."""
    if not optimize:
        return _lower_controlled(gates, ctrl, False)

    def cost(gs: List[Gate]) -> Tuple[int, int]:
        return (sum(gate_cost(g[0], len(g[2])) for g in gs), len(gs))

    fused = _lower_controlled(_fuse_phases(gates), ctrl, True)
    plain = _lower_controlled(gates, ctrl, True)
    return fused if cost(fused) <= cost(plain) else plain


def _collect_block_gates(toks: str, start_p: int, num_qubits: int, optimize: bool) -> List[Gate]:
    """Gate list of a Profile C body (nested Profile C blocks are lowered recursively)."""
    bm = match_brackets(toks)
    p = start_p
    out: List[Gate] = []
    i = 0
    while i < len(toks):
        ch = toks[i]
        if ch == ">":
            p = (p + 1) % num_qubits
        elif ch == "<":
            p = (p - 1) % num_qubits
        elif ch in _TOKEN_GATE:
            out.append((_TOKEN_GATE[ch], p, frozenset()))
        elif ch == "^":
            q_next = (p + 1) % num_qubits
            if q_next == p:
                raise ValueError("'^' (CNOT) requires a tape of at least 2 qubits")
            out.append(("x", q_next, frozenset((p,))))
        elif ch == "[":
            close_idx = bm[i]
            inner = _collect_block_gates(toks[i + 1:close_idx], p, num_qubits, optimize)
            out.extend(_lower_best(inner, frozenset((p,)), optimize))
            i = close_idx
        i += 1
    return out


#  ---------------------------------------------------------------------------------------------
#  Linear-nearest-neighbour (LNN) backend
#
#  1. Every gate with three or more qubits is decomposed exactly into 1- and 2-qubit gates:
#       C^2 X  -> Nielsen & Chuang Toffoli (6 CNOT + T gates)
#       C^k P(phi) (k >= 2) -> cp(phi/2) . C^{k-1}X . cp(-phi/2) . C^{k-1}X . C^{k-1}P(phi/2)
#       C^k X = H C^k P(pi) H (k >= 3),  C^k Z = H C^k X H,  C^k H = Ry(pi/4) C^k Z Ry(-pi/4)
#       (operator order; in time order ry(-pi/4) is applied first)
#  2. Two-qubit gates are routed on an open chain of physical qubits by adjacent SWAPs while a
#     logical->physical layout is tracked. Dynamic loop bodies restore the layout they started
#     with, so every iteration (and the loop exit) sees the same layout.
#  Angles are exact rational multiples of pi.
#  ---------------------------------------------------------------------------------------------

_PHASE_ANGLE = {"t": Fraction(1, 4), "tdg": Fraction(-1, 4), "s": Fraction(1, 2), "sdg": Fraction(-1, 2), "z": Fraction(1)}
_CTRL_2Q = {"x": "cx", "z": "cz", "h": "ch"}


def _fmt_angle(a: Fraction) -> str:
    if a == 0:
        return "0"
    sign = "-" if a < 0 else ""
    num, den = abs(a.numerator), a.denominator
    core = "pi" if num == 1 else f"{num}*pi"
    return f"{sign}{core}" if den == 1 else f"{sign}{core}/{den}"


def _mcphase(controls: List[int], t: int, ang: Fraction) -> List[tuple]:
    if not controls:
        return [("1", "p", t, ang)]
    if len(controls) == 1:
        return [("2", "cp", controls[0], t, ang)]
    ck, rest = controls[-1], controls[:-1]
    return ([("2", "cp", ck, t, ang / 2)] + _mcx(rest, ck) + [("2", "cp", ck, t, -ang / 2)]
            + _mcx(rest, ck) + _mcphase(rest, t, ang / 2))


def _mcx(controls: List[int], t: int) -> List[tuple]:
    k = len(controls)
    if k == 0:
        return [("1", "x", t, None)]
    if k == 1:
        return [("2", "cx", controls[0], t, None)]
    if k == 2:
        a, b = controls
        return [
            ("1", "h", t, None), ("2", "cx", b, t, None), ("1", "tdg", t, None), ("2", "cx", a, t, None),
            ("1", "t", t, None), ("2", "cx", b, t, None), ("1", "tdg", t, None), ("2", "cx", a, t, None),
            ("1", "t", b, None), ("1", "t", t, None), ("1", "h", t, None), ("2", "cx", a, b, None),
            ("1", "t", a, None), ("1", "tdg", b, None), ("2", "cx", a, b, None),
        ]
    return [("1", "h", t, None)] + _mcphase(controls, t, Fraction(1)) + [("1", "h", t, None)]


def _decompose_gate(gate: Gate) -> List[tuple]:
    """Exact decomposition of a lowered gate into 1-/2-qubit operations."""
    name, t, controls = gate
    cs = sorted(controls)
    k = len(cs)
    if k == 0:
        return [("1", name, t, None)]
    if k == 1:
        if name in _CTRL_2Q:
            return [("2", _CTRL_2Q[name], cs[0], t, None)]
        return [("2", "ctrl @ " + name, cs[0], t, None)]
    if name == "x":
        return _mcx(cs, t)
    if name == "z":
        return [("1", "h", t, None)] + _mcx(cs, t) + [("1", "h", t, None)]
    if name == "h":
        # H = Ry(pi/4) Z Ry(-pi/4)  ->  time order: ry(-pi/4), C^k Z, ry(pi/4)
        return ([("1", "ry", t, Fraction(-1, 4)), ("1", "h", t, None)] + _mcx(cs, t)
                + [("1", "h", t, None), ("1", "ry", t, Fraction(1, 4))])
    return _mcphase(cs, t, _PHASE_ANGLE[name])


def _format_op(op: tuple, phys: List[int]) -> str:
    if op[0] == "1":
        _, name, q, ang = op
        head = name if ang is None else f"{name}({_fmt_angle(ang)})"
        return f"{head} q[{phys[q]}];"
    _, name, a, b, ang = op
    head = name if ang is None else f"{name}({_fmt_angle(ang)})"
    return f"{head} q[{phys[a]}], q[{phys[b]}];"


class _LnnRouter:
    """Tracks the logical->physical layout on an open chain and inserts adjacent SWAPs."""

    def __init__(self, n: int):
        self.n = n
        self.l2p = list(range(n))
        self.p2l = list(range(n))
        self.swaps = 0

    def _swap_phys(self, i: int, j: int, out: List[str], indent: str) -> None:
        out.append(f"{indent}swap q[{i}], q[{j}];")
        li, lj = self.p2l[i], self.p2l[j]
        self.p2l[i], self.p2l[j] = lj, li
        self.l2p[li], self.l2p[lj] = j, i
        self.swaps += 1

    def _lookahead_cost(self, l2p: List[int], upcoming: List[tuple]) -> int:
        cost = 0
        for w, op in enumerate(upcoming):
            cost += (abs(l2p[op[2]] - l2p[op[3]]) - 1) * (len(upcoming) - w)
        return cost

    def route(self, op: tuple, out: List[str], indent: str, upcoming: Optional[List[tuple]] = None) -> None:
        """Routes one operation. `upcoming` (the next 2-qubit operations) steers which endpoint
        moves: both candidate SWAPs are scored by the weighted distance of the upcoming gates."""
        if op[0] == "2":
            a, b = op[2], op[3]
            look = upcoming or []
            while abs(self.l2p[a] - self.l2p[b]) > 1:
                pa, pb = self.l2p[a], self.l2p[b]
                step = 1 if pb > pa else -1
                cands = [(pa, pa + step), (pb, pb - step)]
                best, best_cost = cands[0], None
                for i, j in cands:
                    trial = list(self.l2p)
                    li, lj = self.p2l[i], self.p2l[j]
                    trial[li], trial[lj] = j, i
                    c = self._lookahead_cost(trial, look)
                    if best_cost is None or c < best_cost:
                        best, best_cost = (i, j), c
                self._swap_phys(min(best), max(best), out, indent)
        out.append(indent + _format_op(op, self.l2p))

    def route_sequence(self, ops: List[tuple], out: List[str], indent: str, window: int = 8) -> None:
        two_q = [k for k, op in enumerate(ops) if op[0] == "2"]
        pos = 0
        for k, op in enumerate(ops):
            while pos < len(two_q) and two_q[pos] <= k:
                pos += 1
            upcoming = [ops[t] for t in two_q[pos:pos + window]]
            self.route(op, out, indent, upcoming)

    def restore(self, target_l2p: List[int], out: List[str], indent: str) -> None:
        """Bubble the layout back to target_l2p using adjacent swaps."""
        for pos in range(self.n):
            want = target_l2p.index(pos)          # logical qubit that must sit at `pos`
            cur = self.l2p[want]
            while cur > pos:
                self._swap_phys(cur - 1, cur, out, indent)
                cur -= 1


#  ---------------------------------------------------------------------------------------------
#  Program IR:  ("comment", text) | ("gate", Gate) | ("measure", k, q) | ("reset", q)
#               | ("loop", p, [items])
#  ---------------------------------------------------------------------------------------------

def _build_ir(tokens: str, num_qubits: int, optimize: bool) -> Tuple[List[tuple], int, bool]:
    bmap = match_brackets(tokens)
    meas_counter = [0]
    has_loop = [False]

    def build(toks: str, bm: Dict[int, int], start_p: int) -> Tuple[List[tuple], int]:
        items: List[tuple] = []
        p = start_p
        i = 0
        while i < len(toks):
            ch = toks[i]
            if ch == ">":
                p = (p + 1) % num_qubits
            elif ch == "<":
                p = (p - 1) % num_qubits
            elif ch in _TOKEN_GATE:
                items.append(("gate", (_TOKEN_GATE[ch], p, frozenset())))
            elif ch == "^":
                q_next = (p + 1) % num_qubits
                if q_next == p:
                    raise ValueError("'^' (CNOT) requires a tape of at least 2 qubits")
                items.append(("gate", ("x", q_next, frozenset((p,)))))
            elif ch == ".":
                items.append(("measure", meas_counter[0], p))
                meas_counter[0] += 1
            elif ch == ",":
                items.append(("reset", p))
            elif ch == "[":
                close_idx = bm[i]
                body = toks[i + 1 : close_idx]
                if BraKetFuckVM.is_coherent_block(body, p, num_qubits):
                    items.append(("comment", f"Profile C: Coherent Controlled Unitary on q[{p}]"))
                    gates = _collect_block_gates(body, p, num_qubits, optimize)
                    items.extend(("gate", g) for g in _lower_best(gates, frozenset((p,)), optimize))
                else:
                    has_loop[0] = True
                    sub, p_end = build(body, match_brackets(body), p)
                    if p_end != p:
                        raise ValueError(
                            f"Profile D loop at q[{p}] has non-zero net pointer displacement; "
                            "the head position after the loop is data-dependent and cannot be "
                            "resolved statically"
                        )
                    items.append(("comment", f"Profile D: Dynamic Copenhagen Loop on q[{p}]"))
                    items.append(("loop", p, sub))
                i = close_idx
            i += 1
        return items, p

    items, _ = build(tokens, bmap, 0)
    return items, meas_counter[0], has_loop[0]


def transpile_to_qasm3(
    code: str,
    num_qubits: Optional[int] = None,
    n_qubits: Optional[int] = None,
    optimize: bool = True,
    lnn: bool = False,
    restore_layout: bool = False,
) -> str:
    """Syntax-directed transpiler from |BF> to OpenQASM 3.0.

    * Pointer shifts are resolved at compile time (zero emitted gates).
    * Every '.' token writes to its own transcript bit ``c[k]`` (k = static occurrence index), so
      repeated measurements of the same cell (e.g. semiclassical qubit recycling) never overwrite
      earlier results. A '.' inside a dynamic loop rewrites its bit on every iteration.
    * Profile C blocks are lowered to (multi-)controlled gates. With ``optimize=True`` (default)
      only the gates that are not undone inside the block receive the control (conjugation-aware
      lowering) and adjacent phase gates are merged; ``optimize=False`` controls every token.
    * Profile D loops use a per-cell guard register ``guard[p]``; since the head position after a
      dynamic loop must be known statically, Profile D bodies must have net displacement 0.
    * ``lnn=True`` targets an *open linear chain*: all gates are decomposed exactly into 1- and
      2-qubit gates and every 2-qubit gate is routed onto adjacent physical qubits with SWAPs.
      ``restore_layout=True`` additionally returns every logical qubit to its own physical qubit
      at the end of the program.
    """
    tokens = clean_code(code)
    if n_qubits is not None and num_qubits is None:
        num_qubits = n_qubits
    if num_qubits is None:
        num_qubits = infer_qubit_count(tokens)
    items, n_meas, has_loop = _build_ir(tokens, num_qubits, optimize)

    body: List[str] = []
    router = _LnnRouter(num_qubits) if lnn else None

    def emit(seq: List[tuple], indent: str) -> None:
        pending: List[tuple] = []   # straight-line operations awaiting routing (LNN mode)

        def flush() -> None:
            if pending:
                router.route_sequence(pending, body, indent)
                pending.clear()

        for it in seq:
            kind = it[0]
            if kind == "gate":
                if router is None:
                    body.append(indent + _format_gate(it[1]))
                else:
                    pending.extend(_decompose_gate(it[1]))
                continue
            if router is not None:
                flush()
            if kind == "comment":
                body.append(f"{indent}// {it[1]}")
            elif kind == "measure":
                q = router.l2p[it[2]] if router else it[2]
                body.append(f"{indent}c[{it[1]}] = measure q[{q}];")
            elif kind == "reset":
                q = router.l2p[it[1]] if router else it[1]
                body.append(f"{indent}reset q[{q}];")
            else:  # loop
                p = it[1]
                q = router.l2p[p] if router else p
                saved = list(router.l2p) if router else None
                body.append(f"{indent}guard[{p}] = measure q[{q}];")
                body.append(f"{indent}while (guard[{p}] == 1) {{")
                emit(it[2], indent + "    ")
                if router:
                    router.restore(saved, body, indent + "    ")
                body.append(f"{indent}    guard[{p}] = measure q[{q}];")
                body.append(f"{indent}}}")
        if router is not None:
            flush()

    emit(items, "")
    if router is not None:
        if restore_layout:
            router.restore(list(range(num_qubits)), body, "")
        layout = ", ".join(f"{l}->{router.l2p[l]}" for l in range(num_qubits))
        body.append(f"// final layout (logical->physical): {layout}")

    header = [
        "OPENQASM 3.0;",
        'include "stdgates.inc";',
        "",
        f"qubit[{num_qubits}] q;",
    ]
    if n_meas:
        header.append(f"bit[{n_meas}] c;  // measurement transcript, one bit per '.' token")
    if has_loop:
        header.append(f"bit[{num_qubits}] guard;  // dynamic-loop test bits")
    if lnn:
        header.append("// LNN-routed for an open linear chain: every 2-qubit gate acts on adjacent qubits")
    header.append("")
    return "\n".join(header + body)


_QASM_GATE_RE = re.compile(r"^(?:ctrl(?:\((\d+)\))? @ )?([a-z]+)(?:\(([^)]*)\))? (.*);")
_MNEMONIC_CTRL = {"cx": ("x", 1), "cz": ("z", 1), "ch": ("h", 1), "ccx": ("x", 2), "cp": ("p", 1)}


def resource_report(
    code: str,
    num_qubits: Optional[int] = None,
    optimize: bool = True,
    lnn: bool = False,
) -> Dict[str, object]:
    """Resource statistics of the OpenQASM 3.0 lowering of a |BF> program.

    Returns token/primitive counts, emitted gate counts per mnemonic, CNOT-equivalents
    (see `gate_cost`; a SWAP counts 3), multi-qubit gate count, the number of routing SWAPs, the
    maximum physical distance spanned by any multi-qubit gate (1 = nearest-neighbour) and an ASAP
    circuit depth (dynamic loop bodies are counted once; measurements and resets occupy their
    qubit for one layer).
    """
    tokens = clean_code(code)
    if num_qubits is None:
        num_qubits = infer_qubit_count(tokens)
    qasm = transpile_to_qasm3(code, num_qubits, optimize=optimize, lnn=lnn)
    counts: Dict[str, int] = {}
    cnot_eq = 0
    multi = 0
    max_dist = 0
    level = [0] * num_qubits
    loops = 0
    for raw in qasm.splitlines():
        line = raw.split("//")[0].strip()
        if not line or line.startswith(("OPENQASM", "include", "qubit", "bit", "}")):
            continue
        if line.startswith("while"):
            loops += 1
            continue
        qs = [int(x) for x in re.findall(r"q\[(\d+)\]", line)]
        if "measure" in line or line.startswith("reset"):
            key = "reset" if line.startswith("reset") else "measure"
        else:
            m = _QASM_GATE_RE.match(line)
            if not m:
                continue
            name = m.group(2)
            key = name if not line.startswith("ctrl") else line.split(" q[")[0]
            if name == "swap":
                cnot_eq += 3
                k = 1
            else:
                k_mod = int(m.group(1)) if m.group(1) else (1 if line.startswith("ctrl @") else 0)
                if name in _MNEMONIC_CTRL and k_mod == 0:
                    base, k = _MNEMONIC_CTRL[name]
                else:
                    base, k = name, k_mod
                cnot_eq += gate_cost(base, k)
            if len(qs) >= 2:
                multi += 1
                max_dist = max(max_dist, max(qs) - min(qs))
        counts[key] = counts.get(key, 0) + 1
        layer = max(level[q] for q in qs) + 1
        for q in qs:
            level[q] = layer
    gate_keys = {k: v for k, v in counts.items() if k not in ("measure", "reset")}
    return {
        "tokens": len(tokens),
        "qubits": num_qubits,
        "native_cnot_tokens": tokens.count("^"),
        "gate_counts": gate_keys,
        "measurements": counts.get("measure", 0),
        "resets": counts.get("reset", 0),
        "dynamic_loops": loops,
        "multi_qubit_gates": multi,
        "swaps": counts.get("swap", 0),
        "max_interaction_distance": max_dist,
        "cnot_equivalents": cnot_eq,
        "depth": max(level) if level else 0,
        "optimized": optimize,
        "lnn": lnn,
    }


def sample_shots(
    code: str,
    n_qubits: int = 6,
    shots: int = 256,
    profile: str = "D",
    seed: Optional[int] = None,
) -> Dict[str, int]:
    """Runs multiple Monte Carlo measurement shots and returns bitstring frequency counts.

    ``profile`` is accepted for API compatibility only: the loop profile is selected per block
    automatically (Profile C when admissible, otherwise Profile D).
    """
    vm = BraKetFuckVM(n_qubits, seed=seed)
    counts: Dict[str, int] = {}
    for _ in range(shots):
        out = vm.run(code)
        counts[out] = counts.get(out, 0) + 1
    return counts


def _factors_from_order(a: int, r: Optional[int], N: int) -> Optional[List[int]]:
    """Shor's classical post-processing for a *verified* order r of a modulo N."""
    if r is None or r % 2 != 0:
        return None
    x = pow(a, r // 2, N)
    if x == N - 1:
        return None
    factors = sorted({g for g in (math.gcd(x - 1, N), math.gcd(x + 1, N)) if 1 < g < N})
    return factors or None


def analyze_shor_15(
    bitstring_or_counts: object,
    is_recycled: bool = False,
    a: int = 7,
    N: int = 15,
    mode: Optional[str] = None,
) -> Dict[str, object]:
    """Extracts the phase, the period via continued fractions, and the prime factors of N.

    The candidate order r' (continued-fraction denominator of the measured phase) is only accepted
    as the order if a^r' = 1 (mod N). Otherwise small multiples k*r' are tested (standard
    post-processing when gcd(s, r) > 1), giving ``recovered_order``/``recovered_factors``.

    Accepts either a single bitstring or a shot-frequency dictionary {bitstring: count}.
    """
    if mode is not None:
        is_recycled = (mode == "recycled")

    if isinstance(bitstring_or_counts, dict):
        total_shots = 0
        factoring_shots = 0
        recovered_shots = 0
        found_factors = None
        for bstr, cnt in bitstring_or_counts.items():
            total_shots += cnt
            res = analyze_shor_15(bstr, is_recycled=is_recycled, a=a, N=N)
            if res.get("factors"):
                factoring_shots += cnt
                found_factors = tuple(res["factors"])
            if res.get("recovered_factors"):
                recovered_shots += cnt
                if found_factors is None:
                    found_factors = tuple(res["recovered_factors"])
        return {
            "total_shots": total_shots,
            "factoring_shots": factoring_shots,
            "recovered_shots": recovered_shots,
            "factors": found_factors,
        }

    bitstring = str(bitstring_or_counts)
    empty = {
        "bitstring": bitstring, "phase": 0.0, "fraction": "0/1", "candidate_order": None,
        "order_verified": False, "order": None, "recovered_order": None,
        "factors": None, "recovered_factors": None,
    }
    if len(bitstring) < 2 or any(ch not in "01" for ch in bitstring[:2]):
        return empty
    if is_recycled:
        # 5-qubit semiclassical (IPE) Shor: the first measured bit is the LSB phi_2,
        # the second measured bit is the MSB phi_1.
        phi2, phi1 = int(bitstring[0]), int(bitstring[1])
    else:
        # 6-qubit full-register Shor (no final SWAP in the inverse QFT): c0 = MSB phi_1, c1 = LSB phi_2.
        phi1, phi2 = int(bitstring[0]), int(bitstring[1])

    phase = phi1 * 0.5 + phi2 * 0.25
    result = dict(empty)
    result["phase_bits"] = f"0.{phi1}{phi2}"
    result["phase"] = phase
    if phase == 0.0:
        return result

    frac = Fraction(phase).limit_denominator(N - 1)
    r_cand = frac.denominator
    verified = pow(a, r_cand, N) == 1
    order = r_cand if verified else None
    recovered = order
    if not verified:
        k = 2
        while k * r_cand < N:  # the true order divides phi(N) < N
            if pow(a, k * r_cand, N) == 1:
                recovered = k * r_cand
                break
            k += 1
    result.update({
        "fraction": f"{frac.numerator}/{frac.denominator}",
        "candidate_order": r_cand,
        "order_verified": verified,
        "order": order,
        "recovered_order": recovered,
        "factors": _factors_from_order(a, order, N),
        "recovered_factors": _factors_from_order(a, recovered, N),
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="|BF> (Bra-Ket-Fuck) Quantum Tape Simulator & OpenQASM 3.0 Transpiler")
    parser.add_argument("source", help="Path to .bfk file or inline |BF> code string")
    parser.add_argument("-q", "--qubits", type=int, default=None, help="Number of tape qubits (auto-inferred if omitted)")
    parser.add_argument("-s", "--shots", type=int, default=1024, help="Number of Monte Carlo measurement shots")
    parser.add_argument("--qasm", action="store_true", help="Emit transpiled OpenQASM 3.0 circuit")
    parser.add_argument("--report", action="store_true", help="Print resource statistics of the OpenQASM lowering")
    parser.add_argument("--no-optimize", action="store_true", help="Control every token of Profile C blocks (no conjugation-aware lowering)")
    parser.add_argument("--lnn", action="store_true", help="Decompose to 1-/2-qubit gates and route onto an open linear chain (nearest-neighbour only)")
    parser.add_argument("--shor", action="store_true", help="Run Shor's algorithm N=15, a=7 post-processing")
    args = parser.parse_args()

    try:
        with open(args.source, "r", encoding="utf-8") as f:
            raw_code = f.read()
    except OSError:
        raw_code = args.source

    tokens = clean_code(raw_code)
    n_qubits = args.qubits or infer_qubit_count(tokens)

    if args.qasm:
        print(transpile_to_qasm3(raw_code, n_qubits, optimize=not args.no_optimize, lnn=args.lnn))
        return
    if args.report:
        import json
        print(json.dumps(resource_report(raw_code, n_qubits, optimize=not args.no_optimize, lnn=args.lnn), indent=2))
        return

    print(f"|BF> Dirac-Muller Quantum Tape VM | Register Width: N = {n_qubits} qubits | Tokens: {len(tokens)}")
    print("-" * 78)

    vm = BraKetFuckVM(n_qubits)
    counts: Dict[str, int] = {}
    for _ in range(args.shots):
        out = vm.run(raw_code)
        counts[out] = counts.get(out, 0) + 1

    print(f"Measurement Transcript Histogram ({args.shots} shots):")
    is_recycled = n_qubits == 5 and "," in tokens
    for bitstr, count in sorted(counts.items()):
        pct = 100.0 * count / args.shots
        bar = "#" * int(pct / 2.5)
        extra = ""
        if args.shor or len(tokens) in (132, 149, 169):
            info = analyze_shor_15(bitstr, is_recycled=is_recycled)
            if info["factors"]:
                extra = (f" -> phase={info['phase']:.2f} ({info['fraction']}), "
                         f"r={info['order']}, factors={info['factors']}")
            elif info["recovered_factors"]:
                extra = (f" -> phase={info['phase']:.2f} ({info['fraction']}), candidate "
                         f"r'={info['candidate_order']} fails a^r'=1; multiple "
                         f"r={info['recovered_order']} gives factors={info['recovered_factors']}")
            else:
                extra = " -> phase=0.00 (trivial branch, resample)"
        print(f"  '{bitstr}': {count:4d} ({pct:5.1f}%) [{bar:<40}]{extra}")


if __name__ == "__main__":
    main()
