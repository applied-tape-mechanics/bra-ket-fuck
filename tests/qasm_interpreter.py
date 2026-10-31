"""Exact reference interpreter for the OpenQASM 3.0 subset emitted by the |BF> transpiler.

Independent of the |BF> VM: it parses the emitted text and evolves a dense statevector, branching
exhaustively on every measurement / reset so that it returns the *exact* output distribution.
Supported: x z h t tdg s sdg, p(a) ry(a), cx cz ch ccx cp(a) swap, ``ctrl @ g``, ``ctrl(k) @ g``,
``c[k] = measure``, ``guard[p] = measure``, ``reset``, and ``while (guard[p] == 1) { ... }``.
Angles are expressions in ``pi`` (e.g. ``-3*pi/4``).
"""
import cmath
import math
import re

_S2 = 1 / math.sqrt(2)
GATES = {
    "x": ((0, 1), (1, 0)),
    "z": ((1, 0), (0, -1)),
    "h": ((_S2, _S2), (_S2, -_S2)),
    "t": ((1, 0), (0, cmath.exp(1j * math.pi / 4))),
    "tdg": ((1, 0), (0, cmath.exp(-1j * math.pi / 4))),
    "s": ((1, 0), (0, 1j)),
    "sdg": ((1, 0), (0, -1j)),
}
_NATIVE = {"cx": ("x", 1), "cz": ("z", 1), "ch": ("h", 1), "ccx": ("x", 2)}
EPS = 1e-12


def _bit(i, q, n):
    return (i >> (n - 1 - q)) & 1


def _angle(expr):
    if not re.fullmatch(r"[-+0-9*/ pi.]+", expr):
        raise ValueError(f"bad angle {expr!r}")
    return eval(expr, {"__builtins__": {}}, {"pi": math.pi})


def _matrix(name, angle=None):
    if name == "p":
        return ((1, 0), (0, cmath.exp(1j * angle)))
    if name == "ry":
        c, s_ = math.cos(angle / 2), math.sin(angle / 2)
        return ((c, -s_), (s_, c))
    return GATES[name]


def apply_swap(state, n, a, b):
    out = [0j] * len(state)
    for i, amp in enumerate(state):
        j = i
        if _bit(i, a, n) != _bit(i, b, n):
            j = i ^ (1 << (n - 1 - a)) ^ (1 << (n - 1 - b))
        out[j] += amp
    return out


def apply_gate(state, n, name, target, controls=(), angle=None):
    m = _matrix(name, angle)
    mask = 1 << (n - 1 - target)
    out = [0j] * len(state)
    for i, a in enumerate(state):
        if a == 0:
            continue
        if not all(_bit(i, c, n) for c in controls):
            out[i] += a
            continue
        b = _bit(i, target, n)
        out[i & ~mask] += m[0][b] * a
        out[i | mask] += m[1][b] * a
    return out


def _parse(body_lines):
    def parse(i):
        out = []
        while i < len(body_lines):
            line = body_lines[i]
            if line == "}":
                return out, i + 1
            mw = re.match(r"while \(guard\[(\d+)\] == 1\) \{", line)
            if mw:
                sub, i = parse(i + 1)
                out.append(("while", int(mw.group(1)), sub))
                continue
            out.append(("stmt", line))
            i += 1
        return out, i
    return parse(0)[0]


def _decode_gate(line):
    """Returns (name, target, controls, angle); name 'swap' uses (a, b) as (target, controls)."""
    qs = [int(x) for x in re.findall(r"q\[(\d+)\]", line)]
    m = re.match(r"ctrl(?:\((\d+)\))? @ (\w+) ", line)
    if m:
        k = int(m.group(1) or 1)
        return m.group(2), qs[k], tuple(qs[:k]), None
    mp = re.match(r"(\w+)\(([^)]*)\) ", line)
    if mp:
        name, angle = mp.group(1), _angle(mp.group(2))
        if name == "cp":
            return "p", qs[1], (qs[0],), angle
        if name in ("p", "ry"):
            return name, qs[0], (), angle
        raise ValueError(f"unsupported QASM line: {line}")
    name = line.split()[0]
    if name == "swap":
        return "swap", qs[0], (qs[1],), None
    if name in _NATIVE:
        base, k = _NATIVE[name]
        return base, qs[k], tuple(qs[:k]), None
    if name in GATES:
        return name, qs[0], (), None
    raise ValueError(f"unsupported QASM line: {line}")


def run_exact(qasm, max_loop_iterations=64):
    """Returns (n_qubits, n_transcript_bits, list of (probability, state, cbits))."""
    lines = [l.split("//")[0].strip() for l in qasm.splitlines()]
    lines = [l for l in lines if l]
    n = int(re.search(r"qubit\[(\d+)\] q;", qasm).group(1))
    mc = re.search(r"bit\[(\d+)\] c;", qasm)
    nbits = int(mc.group(1)) if mc else 0
    body = [l for l in lines if not l.startswith(("OPENQASM", "include", "qubit", "bit"))]
    prog = _parse(body)

    def measure(st, q):
        res = []
        for v in (0, 1):
            p = sum(abs(a) ** 2 for i, a in enumerate(st) if _bit(i, q, n) == v)
            if p < EPS:
                continue
            norm = math.sqrt(p)
            res.append((v, p, [a / norm if _bit(i, q, n) == v else 0j for i, a in enumerate(st)]))
        return res

    def run(stmts, k, st, cbits, guard, prob, iters):
        if k == len(stmts):
            return [(st, cbits, guard, prob)]
        kind = stmts[k][0]
        if kind == "while":
            _, g, sub = stmts[k]
            if guard.get(g, 0) == 1:
                if iters > max_loop_iterations:
                    raise RuntimeError("loop iteration limit exceeded")
                outs = []
                for s2, c2, g2, p2 in run(sub, 0, st, cbits, guard, prob, 0):
                    outs += run(stmts, k, s2, c2, g2, p2, iters + 1)
                return outs
            return run(stmts, k + 1, st, cbits, guard, prob, 0)
        line = stmts[k][1]
        mm = re.match(r"(c|guard)\[(\d+)\] = measure q\[(\d+)\];", line)
        if mm:
            outs = []
            for v, p, ns in measure(st, int(mm.group(3))):
                c2, g2 = dict(cbits), dict(guard)
                (c2 if mm.group(1) == "c" else g2)[int(mm.group(2))] = v
                outs += run(stmts, k + 1, ns, c2, g2, prob * p, iters)
            return outs
        mr = re.match(r"reset q\[(\d+)\];", line)
        if mr:
            q = int(mr.group(1))
            outs = []
            for v, p, ns in measure(st, q):
                if v:
                    ns = apply_gate(ns, n, "x", q)
                outs += run(stmts, k + 1, ns, cbits, guard, prob * p, iters)
            return outs
        name, target, controls, angle = _decode_gate(line)
        if name == "swap":
            ns = apply_swap(st, n, target, controls[0])
        else:
            ns = apply_gate(st, n, name, target, controls, angle)
        return run(stmts, k + 1, ns, cbits, guard, prob, iters)

    init = [0j] * (1 << n)
    init[0] = 1.0 + 0j
    leaves = run(prog, 0, init, {}, {}, 1.0, 0)
    return n, nbits, [(p, st, cb) for st, cb, _, p in leaves]


def exact_distribution(qasm):
    """Exact distribution over transcript bitstrings c[0]c[1]..."""
    _, nbits, leaves = run_exact(qasm)
    dist = {}
    for p, _, cb in leaves:
        key = "".join(str(cb.get(i, 0)) for i in range(nbits))
        dist[key] = dist.get(key, 0.0) + p
    return dist


def final_state(qasm):
    """Final statevector of a measurement-free program."""
    _, _, leaves = run_exact(qasm)
    if len(leaves) != 1:
        raise ValueError("program is not measurement-free")
    return leaves[0][1]
