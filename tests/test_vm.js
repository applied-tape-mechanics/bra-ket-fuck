/**
 * |BF> (Bra-Ket-Fuck) Automated Verification Suite (Node.js, Zero Dependencies)
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const BraKetFuck = require('../src/braketfuck.js');

const EXAMPLES_DIR = path.join(__dirname, '..', 'examples');

function readExample(filename) {
  return fs.readFileSync(path.join(EXAMPLES_DIR, filename), 'utf8');
}

function runTests() {
  console.log('=== Running |BF> JavaScript VM Verification Suite ===');

  // 1. Verify exact token counts
  const expectedCounts = {
    'bell_pair.bfk': 5,
    'ghz_3.bfk': 10,
    'teleportation.bfk': 28,
    'grover_2q.bfk': 33,
    'shor_15_full.bfk': 149,
    'shor_15_full_opt.bfk': 112,
    'shor_15_recycled.bfk': 169,
    'shor_15_recycled_opt.bfk': 132,
  };

  for (const [file, expected] of Object.entries(expectedCounts)) {
    const cleaned = BraKetFuck.cleanCode(readExample(file));
    assert.strictEqual(
      cleaned.length,
      expected,
      `Token count mismatch for ${file}: expected ${expected}, got ${cleaned.length}`
    );
  }
  console.log('✓ Token count verification passed (8/8 examples)');

  // 2. Bell Pair
  const bellCounts = BraKetFuck.sampleShots(readExample('bell_pair.bfk'), 2, 200, 'C');
  for (const k of Object.keys(bellCounts)) {
    assert(k === '00' || k === '11', `Unexpected Bell state outcome: ${k}`);
  }
  console.log('✓ Bell Pair (|Phi+>) verification passed');

  // 3. GHZ_3
  const ghzCounts = BraKetFuck.sampleShots(readExample('ghz_3.bfk'), 3, 200, 'C');
  for (const k of Object.keys(ghzCounts)) {
    assert(k === '000' || k === '111', `Unexpected GHZ_3 outcome: ${k}`);
  }
  console.log('✓ GHZ_3 State verification passed');

  // 4. Quantum Teleportation
  const teleCounts = BraKetFuck.sampleShots(readExample('teleportation.bfk'), 3, 100, 'D');
  for (const k of Object.keys(teleCounts)) {
    assert.strictEqual(k[2], '1', `Teleported qubit q[2] must be 1, got ${k}`);
  }
  console.log('✓ Quantum Teleportation verification passed (100% fidelity)');

  // 5. 2-Qubit Grover Search
  const groverCounts = BraKetFuck.sampleShots(readExample('grover_2q.bfk'), 2, 100, 'C');
  assert.strictEqual(groverCounts['11'], 100, 'Grover 2Q must yield |11> with 100% probability');
  console.log('✓ 2-Qubit Grover Search verification passed (100% |11>)');

  // 6. Shor N=15 Full 6-Qubit
  const shor6Counts = BraKetFuck.sampleShots(readExample('shor_15_full.bfk'), 6, 400, 'C');
  const shor6Report = BraKetFuck.analyzeShor15(shor6Counts, 'full6q');
  assert.deepStrictEqual(shor6Report.factors, [3, 5]);
  assert(shor6Report.factoringShots > 150 && shor6Report.factoringShots < 250);
  console.log(`✓ Shor N=15 (6Q Full, 149 tokens) verified -> Factors: ${shor6Report.factors.join(' × ')}`);

  // 7. Shor N=15 Recycled 5-Qubit (169 tokens & 132 tokens)
  for (const file of ['shor_15_recycled.bfk', 'shor_15_recycled_opt.bfk']) {
    const counts = BraKetFuck.sampleShots(readExample(file), 5, 400, 'D');
    const report = BraKetFuck.analyzeShor15(counts, 'recycled');
    assert.deepStrictEqual(report.factors, [3, 5]);
    assert(report.factoringShots > 150 && report.factoringShots < 250);
    console.log(`✓ Shor N=15 (${file}) verified -> Factors: ${report.factors.join(' × ')}`);
  }

  // 8. OpenQASM 3.0 Transpilation
  const qasm = BraKetFuck.transpileToQASM3(readExample('shor_15_recycled_opt.bfk'), 5);
  assert(qasm.includes('OPENQASM 3.0;'));
  assert(qasm.includes('qubit[5] q;'));
  assert(qasm.includes('reset q[0];'));
  assert(!qasm.includes('ctrl @ {'), 'OpenQASM 3 has no anonymous ctrl blocks');
  assert(qasm.includes('c[0] = measure q[0];') && qasm.includes('c[1] = measure q[0];'),
    'both recycled phase bits must be kept in separate transcript bits');
  assert.strictEqual(qasm, BraKetFuck.transpileToQASM3(readExample('shor_15_recycled_opt.bfk'), 5));
  assert.throws(() => BraKetFuck.transpileToQASM3('+>+<[>].', 3), /displacement/);
  console.log('✓ OpenQASM 3.0 compiler verification passed');

  // 9. Profile D Brainfuck semantics: '[' re-tests the cell under the current head
  const vmD = new BraKetFuck.BraKetFuckVM(3, { seed: 1 });
  assert.strictEqual(vmD.run('+>+<[>].'), '0');
  assert.strictEqual(vmD.pointer, 2);
  // Nested Profile D disqualifies Profile C; nested Profile C is accepted
  assert.strictEqual(BraKetFuck.isCoherentBlock('>[+]<', 0, 3), false);
  assert.strictEqual(BraKetFuck.isCoherentBlock('>[>+<]<', 0, 3), true);
  const toff = new BraKetFuck.BraKetFuckVM(3);
  assert.strictEqual(toff.run('+>+<[>[>+<]<]>>.'), '1', 'nested Profile C must act as a Toffoli');
  console.log('✓ Loop-profile semantics verification passed');

  // 10. Seeded reproducibility and Shor post-processing
  const sA = BraKetFuck.sampleShots(readExample('shor_15_full.bfk'), 6, 100, null, 42);
  const sB = BraKetFuck.sampleShots(readExample('shor_15_full.bfk'), 6, 100, null, 42);
  assert.deepStrictEqual(sA, sB);
  const s2 = BraKetFuck.analyzeShor15('10', 'full6q');
  assert.strictEqual(s2.candidateOrder, 2);
  assert.strictEqual(s2.orderVerified, false);
  assert.strictEqual(s2.factors, null);
  assert.strictEqual(s2.recoveredOrder, 4);
  assert.deepStrictEqual(s2.recoveredFactors, [3, 5]);
  assert.strictEqual(BraKetFuck.analyzeShor15('10', 'recycled').phase, 0.25);
  const agg = BraKetFuck.analyzeShor15({ '00': 25, '01': 25, '10': 25, '11': 25 }, 'full6q');
  assert.strictEqual(agg.factoringShots, 50);
  assert.strictEqual(agg.recoveredShots, 75);
  console.log('✓ Shor post-processing verification passed');

  // 11. Conjugation-aware Profile C lowering and resource report (must match the Python numbers)
  assert.strictEqual(BraKetFuck.resourceReport('[>^H>H<^>H<H^<]', 3).cnotEquivalents, 8);
  assert.strictEqual(BraKetFuck.resourceReport('[>^H>H<^>H<H^<]', 3, { optimize: false }).cnotEquivalents, 22);
  const expectedCost = [
    ['shor_15_full.bfk', 6, 206, 58],
    ['shor_15_full_opt.bfk', 6, 140, 44],
    ['shor_15_recycled.bfk', 5, 202, 56],
    ['shor_15_recycled_opt.bfk', 5, 136, 42]
  ];
  for (const [file, n, raw, opt] of expectedCost) {
    const code = readExample(file);
    assert.strictEqual(BraKetFuck.resourceReport(code, n, { optimize: false }).cnotEquivalents, raw, file);
    assert.strictEqual(BraKetFuck.resourceReport(code, n).cnotEquivalents, opt, file);
  }
  const optCounts = BraKetFuck.sampleShots(readExample('shor_15_full_opt.bfk'), 6, 400, null, 9);
  assert.deepStrictEqual(BraKetFuck.analyzeShor15(optCounts, 'full6q').factors, [3, 5]);
  console.log('✓ Conjugation-aware lowering & resource report verification passed');

  // 12. LNN routing for an open chain (numbers must match the Python reference)
  const expectedLnn = [
    ['shor_15_full.bfk', 6, 124, 22],
    ['shor_15_full_opt.bfk', 6, 104, 20],
    ['shor_15_recycled.bfk', 5, 119, 21],
    ['shor_15_recycled_opt.bfk', 5, 93, 17]
  ];
  for (const [file, n, cnot, swaps] of expectedLnn) {
    const rep = BraKetFuck.resourceReport(readExample(file), n, { lnn: true });
    assert.strictEqual(rep.maxInteractionDistance, 1, `${file} must be nearest-neighbour after routing`);
    assert.strictEqual(rep.cnotEquivalents, cnot, file);
    assert.strictEqual(rep.swaps, swaps, file);
    const q = BraKetFuck.transpileToQASM3(readExample(file), n, { lnn: true });
    assert(!q.includes('ccx') && !q.includes('ctrl('), 'no 3+-qubit gates may remain');
  }
  console.log('✓ LNN routing verification passed');

  console.log('=== ALL |BF> JAVASCRIPT VM TESTS PASSED ===');
}

runTests();
