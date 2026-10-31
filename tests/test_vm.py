#!/usr/bin/env python3
"""
|BF> (Bra-Ket-Fuck) Automated Verification Suite (Python 3, Zero Dependencies)
Tests all canonical quantum benchmarks, Shor's algorithm variants, and OpenQASM 3.0 transpilation.
"""

import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT_DIR, 'src'))

from braketfuck import (
    BraKetFuckVM,
    clean_code,
    transpile_to_qasm3,
    sample_shots,
    analyze_shor_15,
    resource_report,
)


def read_example(filename: str) -> str:
    path = os.path.join(ROOT_DIR, 'examples', filename)
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


class TestBraKetFuckVM(unittest.TestCase):

    def test_example_token_counts(self):
        expected = {
            'bell_pair.bfk': 5,
            'ghz_3.bfk': 10,
            'teleportation.bfk': 28,
            'grover_2q.bfk': 33,
            'shor_15_full.bfk': 149,
            'shor_15_full_opt.bfk': 112,
            'shor_15_recycled.bfk': 169,
            'shor_15_recycled_opt.bfk': 132,
        }
        for name, count in expected.items():
            code = read_example(name)
            self.assertEqual(len(clean_code(code)), count, f"Token count mismatch for {name}")

    def test_bell_pair(self):
        code = read_example('bell_pair.bfk')
        counts = sample_shots(code, n_qubits=2, shots=200, profile='C', seed=42)
        for bitstring in counts:
            self.assertIn(bitstring, ('00', '11'))

    def test_ghz_3(self):
        code = read_example('ghz_3.bfk')
        counts = sample_shots(code, n_qubits=3, shots=200, profile='C', seed=42)
        for bitstring in counts:
            self.assertIn(bitstring, ('000', '111'))

    def test_teleportation(self):
        code = read_example('teleportation.bfk')
        counts = sample_shots(code, n_qubits=3, shots=100, profile='D', seed=42)
        for bitstring in counts:
            # 3rd measured bit is the teleported state on q2, which must be '1' with 100% fidelity
            self.assertEqual(bitstring[-1], '1', f"Teleportation failed on shot {bitstring}")

    def test_grover_2q(self):
        code = read_example('grover_2q.bfk')
        counts = sample_shots(code, n_qubits=2, shots=100, profile='C', seed=42)
        self.assertEqual(counts, {'11': 100})

    def test_shor_15_full_6q(self):
        code = read_example('shor_15_full.bfk')
        counts = sample_shots(code, n_qubits=6, shots=400, profile='C', seed=1337)
        report = analyze_shor_15(counts, mode='full6q')
        self.assertEqual(report['factors'], (3, 5))
        # Theoretical probability of x in {1, 3} is 0.50
        ratio = report['factoring_shots'] / report['total_shots']
        self.assertGreater(ratio, 0.40)
        self.assertLess(ratio, 0.60)

    def test_shor_15_recycled_5q(self):
        for fname in ('shor_15_recycled.bfk', 'shor_15_recycled_opt.bfk'):
            code = read_example(fname)
            counts = sample_shots(code, n_qubits=5, shots=400, profile='D', seed=1337)
            report = analyze_shor_15(counts, mode='recycled')
            self.assertEqual(report['factors'], (3, 5))
            ratio = report['factoring_shots'] / report['total_shots']
            self.assertGreater(ratio, 0.40)
            self.assertLess(ratio, 0.60)

    def test_openqasm3_transpiler(self):
        code = read_example('shor_15_recycled_opt.bfk')
        qasm = transpile_to_qasm3(code, n_qubits=5)
        self.assertIn('OPENQASM 3.0;', qasm)
        self.assertIn('qubit[5] q;', qasm)
        self.assertIn('reset q[0];', qasm)
        # OpenQASM 3 has no anonymous 'ctrl @ { ... }' blocks
        self.assertNotIn('ctrl @ {', qasm)
        # Semiclassical recycling measures q[0] twice: both phase bits must survive in the transcript
        self.assertIn('bit[2] c;', qasm)
        self.assertIn('c[0] = measure q[0];', qasm)
        self.assertIn('c[1] = measure q[0];', qasm)
        self.assertIn('while (guard[0] == 1) {', qasm)

    def test_transpiler_rejects_dynamic_loop_with_displacement(self):
        with self.assertRaises(ValueError):
            transpile_to_qasm3('+>+<[>].', 3)

    def test_profile_d_brainfuck_semantics(self):
        # '[' re-tests the cell under the *current* head: after one '>' the head sits on q1 (=1),
        # after the second on q2 (=0), so the loop exits with the head on q2.
        vm = BraKetFuckVM(3, seed=0)
        out = vm.run('+>+<[>].')
        self.assertEqual(out, '0')
        self.assertEqual(vm.pointer, 2)

    def test_nested_profile_c(self):
        # [>[>+<]<] is a doubly-controlled X (Toffoli)
        for idx in range(8):
            vm = BraKetFuckVM(3)
            vm.state = [0j] * 8
            vm.state[idx] = 1.0 + 0j
            toks = clean_code('[>[>+<]<]')
            from braketfuck import match_brackets
            vm._execute_tokens(toks, match_brackets(toks), 0, len(toks))
            expected = idx ^ 1 if (idx & 0b110) == 0b110 else idx
            self.assertAlmostEqual(abs(vm.state[expected]), 1.0)
        # A nested Profile D loop (which measures) disqualifies the enclosing block from Profile C
        self.assertFalse(BraKetFuckVM.is_coherent_block('>[+]<', 0, 3))

    def test_seeded_sampling_is_reproducible(self):
        code = read_example('shor_15_full.bfk')
        self.assertEqual(
            sample_shots(code, n_qubits=6, shots=100, seed=7),
            sample_shots(code, n_qubits=6, shots=100, seed=7),
        )

    def test_shor_exact_distributions(self):
        import itertools
        for fname, n in (('shor_15_full.bfk', 6), ('shor_15_recycled.bfk', 5), ('shor_15_recycled_opt.bfk', 5)):
            code = read_example(fname)
            dist = {}
            for forced in itertools.product((0, 1), repeat=2):
                vm = BraKetFuckVM(n)
                out = vm.run(code, forced_outcomes=list(forced))
                if out != ''.join(map(str, forced)):
                    continue
                p = 1.0
                for _, _, prob in vm.measurement_records:
                    p *= prob
                dist[out] = dist.get(out, 0.0) + p
            self.assertEqual(len(dist), 4, fname)
            for v in dist.values():
                self.assertAlmostEqual(v, 0.25, places=9)

    def test_shor_post_processing(self):
        # Full register: c0 = MSB, c1 = LSB. Recycled: first bit = LSB, second = MSB.
        self.assertEqual(analyze_shor_15('01', mode='full6q')['phase'], 0.25)
        self.assertEqual(analyze_shor_15('10', mode='recycled')['phase'], 0.25)
        s2 = analyze_shor_15('10', mode='full6q')  # phase 1/2 -> candidate r' = 2
        self.assertEqual(s2['candidate_order'], 2)
        self.assertFalse(s2['order_verified'])  # 7^2 = 4 (mod 15)
        self.assertIsNone(s2['factors'])
        self.assertEqual(s2['recovered_order'], 4)
        self.assertEqual(s2['recovered_factors'], [3, 5])
        for bits in ('01', '11'):
            info = analyze_shor_15(bits, mode='full6q')
            self.assertEqual(info['order'], 4)
            self.assertEqual(info['factors'], [3, 5])
        self.assertIsNone(analyze_shor_15('00', mode='full6q')['factors'])
        report = analyze_shor_15({'00': 25, '01': 25, '10': 25, '11': 25}, mode='full6q')
        self.assertEqual(report['factoring_shots'], 50)
        self.assertEqual(report['recovered_shots'], 75)

    def test_cnot_requires_two_qubits(self):
        with self.assertRaises(ValueError):
            BraKetFuckVM(1).run('^')

    def test_shor_full_opt_equivalent(self):
        code = read_example('shor_15_full_opt.bfk')
        self.assertEqual(len(clean_code(code)), 112)
        ref, opt = BraKetFuckVM(6), BraKetFuckVM(6)
        ref.run(read_example('shor_15_full.bfk'), forced_outcomes=[0, 0])
        opt.run(code, forced_outcomes=[0, 0])
        for a, b in zip(ref.pre_measurement_state, opt.pre_measurement_state):
            self.assertAlmostEqual(abs(a - b), 0.0, places=12)
        report = analyze_shor_15(sample_shots(code, n_qubits=6, shots=400, seed=3), mode='full6q')
        self.assertEqual(report['factors'], (3, 5))

    def test_conjugation_aware_lowering(self):
        # Controlled SWAP macro -> CNOT, H, H, Toffoli, H, H, CNOT (8 CNOT-equivalents instead of 22)
        qasm = transpile_to_qasm3('[>^H>H<^>H<H^<]', 3)
        self.assertEqual(qasm.count('ccx'), 1)
        self.assertNotIn('ch ', qasm)
        self.assertEqual(resource_report('[>^H>H<^>H<H^<]', 3)['cnot_equivalents'], 8)
        self.assertEqual(resource_report('[>^H>H<^>H<H^<]', 3, optimize=False)['cnot_equivalents'], 22)
        expected = {
            ('shor_15_full.bfk', 6): (206, 58),
            ('shor_15_full_opt.bfk', 6): (140, 44),
            ('shor_15_recycled.bfk', 5): (202, 56),
            ('shor_15_recycled_opt.bfk', 5): (136, 42),
        }
        for (fname, n), (raw, opt) in expected.items():
            code = read_example(fname)
            self.assertEqual(resource_report(code, n, optimize=False)['cnot_equivalents'], raw, fname)
            self.assertEqual(resource_report(code, n)['cnot_equivalents'], opt, fname)

    def test_lnn_decompositions_exact(self):
        # Every gate kind with 1, 2 and 3 coherent controls, on a superposed, phased input state,
        # compiled for an open chain: the routed circuit must reproduce the VM statevector exactly.
        sys.path.insert(0, os.path.join(ROOT_DIR, 'tests'))
        from qasm_interpreter import final_state
        prep = 'H>H>H>H<<<T>-<'
        for body in ('+', 'Z', 'H', 'T', '-', 'TT', '--', 'ZT', '^'):
            for depth in (1, 2, 3):
                # nested controls on cells 0..depth-1, body applied at cell `depth`
                # ('^' adds one more control, so depth 3 exercises a 4-controlled X)
                code = prep + '[>' * depth + body + '<]' * depth
                self.assertTrue(BraKetFuckVM.is_coherent_block(code[len(prep) + 1:-1], 0, 5))
                with self.subTest(body=body, depth=depth):
                    vm = BraKetFuckVM(5)
                    vm.run(code)
                    qasm = transpile_to_qasm3(code, 5, lnn=True, restore_layout=True)
                    st = final_state(qasm)
                    self.assertLess(max(abs(a - b) for a, b in zip(vm.state, st)), 1e-9)
                    self.assertLessEqual(resource_report(code, 5, lnn=True)['max_interaction_distance'], 1)

    def test_lnn_shor_programs(self):
        sys.path.insert(0, os.path.join(ROOT_DIR, 'tests'))
        from qasm_interpreter import exact_distribution
        for fname, n in (('shor_15_full.bfk', 6), ('shor_15_full_opt.bfk', 6),
                         ('shor_15_recycled.bfk', 5), ('shor_15_recycled_opt.bfk', 5)):
            code = read_example(fname)
            rep = resource_report(code, n, lnn=True)
            self.assertEqual(rep['max_interaction_distance'], 1, fname)
            self.assertGreater(rep['swaps'], 0, fname)
            dist = exact_distribution(transpile_to_qasm3(code, n, lnn=True))
            self.assertEqual(len(dist), 4, fname)
            for v in dist.values():
                self.assertAlmostEqual(v, 0.25, places=9)

    def test_paper_tables_up_to_date(self):
        import subprocess
        res = subprocess.run([sys.executable, os.path.join(ROOT_DIR, 'tools', 'gen_paper_tables.py'), '--check'],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
