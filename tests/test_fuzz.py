#!/usr/bin/env python3
"""Differential fuzzing of the |BF> toolchain (zero dependencies).

For a few hundred random, well-formed |BF> programs (coherent Profile C blocks, nested blocks,
terminating Profile D loops, resets and measurements) it checks that

  1. the exact output distribution of the Python VM (exhaustive branching over all measurements)
  2. the exact distribution of the optimized OpenQASM lowering (independent interpreter)
  3. the exact distribution of the per-token (unoptimized) OpenQASM lowering
  4. the exact distribution of the LNN-routed OpenQASM lowering (open chain)

all coincide; that measurement-free programs give identical final statevectors; and that the
Python and JavaScript transpilers emit byte-identical OpenQASM.
"""
import json
import os
import random
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, HERE)

import braketfuck as bf  # noqa: E402
from qasm_interpreter import exact_distribution, final_state  # noqa: E402

SEED = 20261030
N_PROGRAMS = 400
SWAP_MACRO = "^H>H<^>H<H^"


class _Dead(Exception):
    pass


class ScriptedVM(bf.BraKetFuckVM):
    """VM whose measurement outcomes follow a script; used to enumerate all branches exactly."""

    def __init__(self, n, script):
        super().__init__(n)
        self.script = list(script)
        self.idx = 0
        self.prob = 1.0
        self.pending = []

    def measure_cell(self, p, forced_outcome=None):
        mask = 1 << (self.num_qubits - 1 - p)
        p1 = sum(abs(a) ** 2 for i, a in enumerate(self.state) if i & mask)
        p0 = 1.0 - p1
        if self.idx < len(self.script):
            m = self.script[self.idx]
        else:
            m = 0 if p0 > 1e-10 else 1
            if p0 > 1e-10 and p1 > 1e-10:
                self.pending.append(self.script[: self.idx] + [1])
            self.script.append(m)
        pm = p1 if m else p0
        if pm < 1e-10:
            raise _Dead()
        self.idx += 1
        self.prob *= pm
        return super().measure_cell(p, forced_outcome=m)


def vm_exact_distribution(code, n):
    dist = {}
    stack = [[]]
    while stack:
        script = stack.pop()
        vm = ScriptedVM(n, script)
        try:
            out = vm.run(code)
        except _Dead:
            continue
        stack.extend(vm.pending)
        dist[out] = dist.get(out, 0.0) + vm.prob
    return dist


# ------------------------------------------------------------------ random program generator
class Gen:
    def __init__(self, rng, n):
        self.rng = rng
        self.n = n

    def nav(self, src, dst):
        d = (dst - src) % self.n
        return ">" * d if d <= self.n - d else "<" * (self.n - d)

    def coherent(self, start, protected, depth):
        """Random Profile C body entered at `start`; never acts on `protected` cells."""
        rng, n = self.rng, self.n
        p, out = start, []
        for _ in range(rng.randint(1, 7)):
            r = rng.random()
            if r < 0.3:
                step = rng.choice("><")
                p = (p + (1 if step == ">" else -1)) % n
                out.append(step)
            elif r < 0.6 and p not in protected:
                out.append(rng.choice("+ZHT-"))
            elif r < 0.75 and p not in protected and (p + 1) % n not in protected and n > 1:
                out.append(rng.choice(["^", SWAP_MACRO, "H^H", "T^-"]))
            elif r < 0.85 and p not in protected:
                g = rng.choice("HT+")
                inv = {"H": "H", "T": "-", "+": "+"}[g]
                out.append(g + rng.choice("ZH+T-") + inv)  # V U V^-1 pattern
            elif depth < 2:
                inner = self.coherent(p, protected | {p}, depth + 1)
                if inner:
                    out.append("[" + inner + "]")
        out.append(self.nav(p, start))
        body = "".join(out)
        return body if bf.BraKetFuckVM.is_coherent_block(body, start, n) else ""

    def seq(self, p, depth, allow_meas):
        """Random statement sequence starting at p; returns (code, end_p)."""
        rng, n = self.rng, self.n
        out = []
        for _ in range(rng.randint(2, 8)):
            r = rng.random()
            if r < 0.25:
                step = rng.choice("><")
                p = (p + (1 if step == ">" else -1)) % n
                out.append(step)
            elif r < 0.55:
                out.append(rng.choice("+ZHT-H"))
            elif r < 0.65 and n > 1:
                out.append("^")
            elif r < 0.8 and depth < 2:
                body = self.coherent(p, {p}, depth + 1)
                if body:
                    out.append("[" + body + "]")
            elif r < 0.88 and depth < 2:
                body, end = self.seq(p, depth + 1, False)
                out.append("[" + body + self.nav(end, p) + ",]")  # terminating Profile D loop
            elif r < 0.94 and allow_meas:
                out.append(".")
            else:
                out.append(",")
        return "".join(out), p

    def program(self, unitary_only=False):
        code, _ = self.seq(0, 0 if not unitary_only else 2, not unitary_only)
        if unitary_only:
            code = code.replace(",", "")
            body = self.coherent(0, {0}, 1)
            code = "H" + code + ("[" + body + "]" if body else "")
        return code


def _dist_close(a, b, tol=1e-9):
    keys = set(a) | set(b)
    return all(abs(a.get(k, 0.0) - b.get(k, 0.0)) < tol for k in keys)


class TestDifferentialFuzz(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        rng = random.Random(SEED)
        cls.cases = []
        for i in range(N_PROGRAMS):
            n = rng.randint(2, 4)
            code = Gen(rng, n).program(unitary_only=(i % 5 == 0))
            cls.cases.append((code, n))

    def test_vm_vs_qasm_distributions(self):
        for code, n in self.cases:
            with self.subTest(code=code, n=n):
                q_opt = bf.transpile_to_qasm3(code, n)
                q_raw = bf.transpile_to_qasm3(code, n, optimize=False)
                d_vm = vm_exact_distribution(code, n)
                d_opt = exact_distribution(q_opt)
                d_raw = exact_distribution(q_raw)
                d_lnn = exact_distribution(bf.transpile_to_qasm3(code, n, lnn=True))
                self.assertTrue(_dist_close(d_vm, d_opt), (d_vm, d_opt))
                self.assertTrue(_dist_close(d_opt, d_raw), (d_opt, d_raw))
                self.assertTrue(_dist_close(d_opt, d_lnn), (d_opt, d_lnn))

    def test_unitary_statevectors(self):
        checked = 0
        for code, n in self.cases:
            if any(t in code for t in ".,"):
                continue
            with self.subTest(code=code, n=n):
                vm = bf.BraKetFuckVM(n)
                vm.run(code)
                for opt in (True, False):
                    for lnn in (False, True):
                        st = final_state(bf.transpile_to_qasm3(code, n, optimize=opt, lnn=lnn, restore_layout=True))
                        self.assertLess(max(abs(a - b) for a, b in zip(vm.state, st)), 1e-9)
                checked += 1
        self.assertGreater(checked, 20)

    def test_lnn_output_is_nearest_neighbour(self):
        for code, n in self.cases:
            with self.subTest(code=code, n=n):
                rep = bf.resource_report(code, n, lnn=True)
                self.assertLessEqual(rep["max_interaction_distance"], 1)
                qasm = bf.transpile_to_qasm3(code, n, lnn=True)
                self.assertNotIn("ccx", qasm)
                self.assertNotIn("ctrl(", qasm)

    def test_optimizer_never_increases_cost(self):
        for code, n in self.cases:
            with self.subTest(code=code, n=n):
                opt = bf.resource_report(code, n, optimize=True)["cnot_equivalents"]
                raw = bf.resource_report(code, n, optimize=False)["cnot_equivalents"]
                self.assertLessEqual(opt, raw)

    @unittest.skipIf(shutil.which("node") is None, "Node.js not available")
    def test_python_and_js_transpilers_identical(self):
        payload = json.dumps([[c, n] for c, n in self.cases])
        script = (
            "const B=require(process.argv[1]);let d='';process.stdin.on('data',c=>d+=c);"
            "process.stdin.on('end',()=>{const cs=JSON.parse(d);process.stdout.write(JSON.stringify("
            "cs.map(([c,n])=>[B.transpileToQASM3(c,n),B.transpileToQASM3(c,n,{optimize:false}),"
            "B.resourceReport(c,n).cnotEquivalents,B.transpileToQASM3(c,n,{lnn:true,restoreLayout:true}),"
            "B.resourceReport(c,n,{lnn:true}).cnotEquivalents])));});"
        )
        res = subprocess.run(
            ["node", "-e", script, os.path.join(ROOT, "src", "braketfuck.js")],
            input=payload, capture_output=True, text=True, check=True,
        )
        js = json.loads(res.stdout)
        for (code, n), (q_opt, q_raw, cnot, q_lnn, cnot_lnn) in zip(self.cases, js):
            with self.subTest(code=code, n=n):
                self.assertEqual(q_opt, bf.transpile_to_qasm3(code, n))
                self.assertEqual(q_raw, bf.transpile_to_qasm3(code, n, optimize=False))
                self.assertEqual(cnot, bf.resource_report(code, n)["cnot_equivalents"])
                self.assertEqual(q_lnn, bf.transpile_to_qasm3(code, n, lnn=True, restore_layout=True))
                self.assertEqual(cnot_lnn, bf.resource_report(code, n, lnn=True)["cnot_equivalents"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
