/**
 * |BF> (Bra-Ket-Fuck) Quantum Virtual Machine & OpenQASM 3.0 Transpiler
 * Dirac-Muller Abstract Machine (DMM) Reference Engine
 * Zero external dependencies. Runs identically in Browser and Node.js.
 */

(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.BraKetFuck = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const VALID_SET = new Set(['>', '<', '+', 'Z', 'H', 'T', '-', '^', '.', ',', '[', ']']);
  const INV_SQRT2 = Math.SQRT1_2;
  const COS_PI_4 = Math.SQRT1_2;
  const SIN_PI_4 = Math.SQRT1_2;

  function cleanCode(raw) {
    if (!raw) return '';
    const noComments = String(raw).replace(/(#|\/\/).*$/gm, '');
    let out = '';
    for (let i = 0; i < noComments.length; i++) {
      const ch = noComments[i];
      if (VALID_SET.has(ch)) out += ch;
    }
    return out;
  }

  function inferQubitCount(raw, minQubits = 2) {
    const tokens = cleanCode(raw);
    let p = 0;
    let maxP = 0;
    for (let i = 0; i < tokens.length; i++) {
      const ch = tokens[i];
      if (ch === '>') {
        p++;
        if (p > maxP) maxP = p;
      } else if (ch === '<') {
        if (p > 0) p--;
      } else if (ch === '^') {
        if (p + 1 > maxP) maxP = p + 1;
      }
    }
    return Math.max(minQubits, maxP + 1);
  }

  function matchBrackets(tokens) {
    const map = new Map();
    const stack = [];
    for (let i = 0; i < tokens.length; i++) {
      const ch = tokens[i];
      if (ch === '[') {
        stack.push(i);
      } else if (ch === ']') {
        if (stack.length === 0) {
          throw new SyntaxError(`Unmatched ']' at instruction index ${i}`);
        }
        const openIdx = stack.pop();
        map.set(openIdx, i);
        map.set(i, openIdx);
      }
    }
    if (stack.length > 0) {
      throw new SyntaxError(`Unmatched '[' at instruction index ${stack[stack.length - 1]}`);
    }
    return map;
  }

  /**
   * Profile C admissibility of a bracketed body `[ body ]` entered at cell startP:
   *  1. no measurement (.) or reset (,) anywhere inside the body;
   *  2. net pointer displacement 0;
   *  3. no gate acts on the control cell (nor on any enclosing control cell);
   *  4. every nested block is itself Profile C admissible (a nested Profile D loop would measure
   *     inside a coherently controlled branch, which is not a unitary operation).
   */
  function isCoherentBlock(body, startP, numQubits) {
    return coherentCheck(body, startP, numQubits, new Set([startP]));
  }

  function coherentCheck(body, startP, numQubits, protectedCells) {
    if (body.indexOf('.') !== -1 || body.indexOf(',') !== -1) {
      return false;
    }
    let bmap;
    try {
      bmap = matchBrackets(body);
    } catch (e) {
      return false;
    }
    let p = startP;
    for (let i = 0; i < body.length; i++) {
      const ch = body[i];
      if (ch === '>') {
        p = (p + 1) % numQubits;
      } else if (ch === '<') {
        p = (p - 1 + numQubits) % numQubits;
      } else if (ch === '+' || ch === 'Z' || ch === 'H' || ch === 'T' || ch === '-') {
        if (protectedCells.has(p)) return false;
      } else if (ch === '^') {
        const qNext = (p + 1) % numQubits;
        if (protectedCells.has(p) || protectedCells.has(qNext)) return false;
      } else if (ch === '[') {
        const closeIdx = bmap.get(i);
        const inner = body.slice(i + 1, closeIdx);
        // The nested control qubit is only read, so it may coincide with an enclosing control.
        const nested = new Set(protectedCells);
        nested.add(p);
        if (!coherentCheck(inner, p, numQubits, nested)) return false;
        i = closeIdx; // nested block has zero net displacement
      }
    }
    return p === startP;
  }

  /** Small seedable PRNG (mulberry32) for reproducible sampling. */
  function makeRng(seed) {
    if (seed === null || seed === undefined) return Math.random;
    let t = seed >>> 0;
    return function () {
      t = (t + 0x6D2B79F5) >>> 0;
      let x = t;
      x = Math.imul(x ^ (x >>> 15), x | 1);
      x ^= x + Math.imul(x ^ (x >>> 7), x | 61);
      return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
    };
  }

  function getInstructionStats(raw) {
    const tokens = cleanCode(raw);
    const counts = {
      '>': 0, '<': 0, '+': 0, 'Z': 0, 'H': 0,
      'T': 0, '-': 0, '^': 0, '.': 0, ',': 0, '[': 0, ']': 0
    };
    for (let i = 0; i < tokens.length; i++) {
      counts[tokens[i]] = (counts[tokens[i]] || 0) + 1;
    }
    return {
      total: tokens.length,
      length: tokens.length,
      counts,
      shifts: counts['>'] + counts['<'],
      singleQubitGates: counts['+'] + counts['Z'] + counts['H'] + counts['T'] + counts['-'],
      cnotGates: counts['^'],
      measurements: counts['.'],
      resets: counts[','],
      loops: counts['[']
    };
  }

  class BraKetFuckVM {
    constructor(numQubits = 6, options = null) {
      if (numQubits < 1 || numQubits > 16) {
        throw new RangeError('numQubits must be between 1 and 16');
      }
      this.numQubits = numQubits;
      this.nQubits = numQubits;
      this.dim = 1 << numQubits;
      this.re = new Float64Array(this.dim);
      this.im = new Float64Array(this.dim);
      // `options` may be { seed } or { rng }; any other value (e.g. a legacy profile string) is ignored.
      const opts = (options && typeof options === 'object') ? options : {};
      this.rng = typeof opts.rng === 'function' ? opts.rng : makeRng(opts.seed);
      this.reset();
    }

    get head() {
      return this.pointer;
    }

    reset() {
      this.re.fill(0);
      this.im.fill(0);
      this.re[0] = 1.0; // Vacuum state |00...0>
      this.pointer = 0;
      this.transcript = [];
      this.measurementRecords = [];
      this.preMeasureRe = null;
      this.preMeasureIm = null;
    }

    applyX(p = this.pointer) {
      const mask = 1 << (this.numQubits - 1 - p);
      for (let i = 0; i < this.dim; i++) {
        if ((i & mask) === 0) {
          const j = i | mask;
          const tr = this.re[i];
          const ti = this.im[i];
          this.re[i] = this.re[j];
          this.im[i] = this.im[j];
          this.re[j] = tr;
          this.im[j] = ti;
        }
      }
    }

    applyZ(p = this.pointer) {
      const mask = 1 << (this.numQubits - 1 - p);
      for (let i = 0; i < this.dim; i++) {
        if (i & mask) {
          this.re[i] = -this.re[i];
          this.im[i] = -this.im[i];
        }
      }
    }

    applyH(p = this.pointer) {
      const mask = 1 << (this.numQubits - 1 - p);
      for (let i = 0; i < this.dim; i++) {
        if ((i & mask) === 0) {
          const j = i | mask;
          const r0 = this.re[i], i0 = this.im[i];
          const r1 = this.re[j], i1 = this.im[j];
          this.re[i] = (r0 + r1) * INV_SQRT2;
          this.im[i] = (i0 + i1) * INV_SQRT2;
          this.re[j] = (r0 - r1) * INV_SQRT2;
          this.im[j] = (i0 - i1) * INV_SQRT2;
        }
      }
    }

    applyT(p = this.pointer, adjoint = false) {
      const mask = 1 << (this.numQubits - 1 - p);
      const s = adjoint ? -SIN_PI_4 : SIN_PI_4;
      for (let i = 0; i < this.dim; i++) {
        if (i & mask) {
          const r = this.re[i];
          const im = this.im[i];
          this.re[i] = r * COS_PI_4 - im * s;
          this.im[i] = r * s + im * COS_PI_4;
        }
      }
    }

    applyCNOT(p = this.pointer) {
      if (this.numQubits < 2) {
        throw new RangeError("'^' (CNOT) requires a tape of at least 2 qubits");
      }
      const qNext = (p + 1) % this.numQubits; // Ring topology: cell N-1 couples to cell 0
      const ctrlMask = 1 << (this.numQubits - 1 - p);
      const tgtMask = 1 << (this.numQubits - 1 - qNext);
      for (let i = 0; i < this.dim; i++) {
        if ((i & ctrlMask) !== 0 && (i & tgtMask) === 0) {
          const j = i | tgtMask;
          const tr = this.re[i];
          const ti = this.im[i];
          this.re[i] = this.re[j];
          this.im[i] = this.im[j];
          this.re[j] = tr;
          this.im[j] = ti;
        }
      }
    }

    measureCell(p = this.pointer, forcedOutcome = null) {
      const mask = 1 << (this.numQubits - 1 - p);
      let prob0 = 0;
      let prob1 = 0;
      for (let i = 0; i < this.dim; i++) {
        const magSq = this.re[i] * this.re[i] + this.im[i] * this.im[i];
        if (i & mask) prob1 += magSq;
        else prob0 += magSq;
      }
      let m = forcedOutcome !== null ? forcedOutcome : (this.rng() < prob1 ? 1 : 0);
      let chosenProb = m === 1 ? prob1 : prob0;
      if (chosenProb < 1e-12) {
        m = 1 - m;
        chosenProb = m === 1 ? prob1 : prob0;
      }
      const norm = 1.0 / Math.sqrt(Math.max(chosenProb, 1e-15));
      for (let i = 0; i < this.dim; i++) {
        const bit = (i & mask) ? 1 : 0;
        if (bit === m) {
          this.re[i] *= norm;
          this.im[i] *= norm;
        } else {
          this.re[i] = 0;
          this.im[i] = 0;
        }
      }
      return { outcome: m, probability: chosenProb, prob0, prob1 };
    }

    resetCell(p = this.pointer) {
      const res = this.measureCell(p);
      if (res.outcome === 1) {
        this.applyX(p);
      }
    }

    _executeTokens(tokens, bmap, start, end, forcedOutcomes, forcedIdxRef) {
      let i = start;
      while (i < end) {
        const ch = tokens[i];
        if (ch === '>') {
          this.pointer = (this.pointer + 1) % this.numQubits;
        } else if (ch === '<') {
          this.pointer = (this.pointer - 1 + this.numQubits) % this.numQubits;
        } else if (ch === '+') {
          this.applyX();
        } else if (ch === 'Z') {
          this.applyZ();
        } else if (ch === 'H') {
          this.applyH();
        } else if (ch === 'T') {
          this.applyT(this.pointer, false);
        } else if (ch === '-') {
          this.applyT(this.pointer, true);
        } else if (ch === '^') {
          this.applyCNOT();
        } else if (ch === ',') {
          this.resetCell();
        } else if (ch === '.') {
          if (!this.preMeasureRe) {
            this.preMeasureRe = new Float64Array(this.re);
            this.preMeasureIm = new Float64Array(this.im);
          }
          let fm = null;
          if (forcedOutcomes && forcedIdxRef.idx < forcedOutcomes.length) {
            fm = forcedOutcomes[forcedIdxRef.idx++];
          }
          const res = this.measureCell(this.pointer, fm);
          this.transcript.push(res.outcome);
          this.measurementRecords.push({
            cell: this.pointer,
            outcome: res.outcome,
            probability: res.probability
          });
        } else if (ch === '[') {
          const closeIdx = bmap.get(i);
          const body = tokens.slice(i + 1, closeIdx);
          const ctrl = this.pointer;
          if (isCoherentBlock(body, ctrl, this.numQubits)) {
            const ctrlMask = 1 << (this.numQubits - 1 - ctrl);
            const subVM = new BraKetFuckVM(this.numQubits);
            for (let k = 0; k < this.dim; k++) {
              if (k & ctrlMask) {
                subVM.re[k] = this.re[k];
                subVM.im[k] = this.im[k];
              } else {
                subVM.re[k] = 0;
                subVM.im[k] = 0;
              }
            }
            subVM.pointer = ctrl;
            const subBmap = matchBrackets(body);
            subVM._executeTokens(body, subBmap, 0, body.length, null, { idx: 0 });
            for (let k = 0; k < this.dim; k++) {
              if (k & ctrlMask) {
                this.re[k] = subVM.re[k];
                this.im[k] = subVM.im[k];
              }
            }
          } else {
            // Profile D (Brainfuck semantics): '[' measures the cell under the head; on m=1 the
            // body runs and ']' jumps back to '[', which re-measures the cell under the
            // (possibly moved) head.
            const subBmap = matchBrackets(body);
            let steps = 0;
            while (true) {
              const res = this.measureCell(this.pointer);
              if (res.outcome === 0) break;
              steps++;
              if (steps > 1024) {
                throw new Error('Dynamic Copenhagen loop exceeded 1024 iterations');
              }
              this._executeTokens(body, subBmap, 0, body.length, forcedOutcomes, forcedIdxRef);
            }
          }
          i = closeIdx;
        }
        i++;
      }
    }

    run(rawCode, forcedOutcomes = null) {
      this.reset();
      const tokens = cleanCode(rawCode);
      const bmap = matchBrackets(tokens);
      this._executeTokens(tokens, bmap, 0, tokens.length, forcedOutcomes, { idx: 0 });
      if (!this.preMeasureRe) {
        this.preMeasureRe = new Float64Array(this.re);
        this.preMeasureIm = new Float64Array(this.im);
      }
      return this.transcript.join('');
    }

    getStateDistribution(usePreMeasurement = true) {
      const reArr = (usePreMeasurement && this.preMeasureRe) ? this.preMeasureRe : this.re;
      const imArr = (usePreMeasurement && this.preMeasureIm) ? this.preMeasureIm : this.im;
      const items = [];
      for (let i = 0; i < this.dim; i++) {
        const r = reArr[i];
        const im = imArr[i];
        const prob = r * r + im * im;
        if (prob > 1e-6) {
          const ket = i.toString(2).padStart(this.numQubits, '0');
          const phaseRad = Math.atan2(im, r);
          const phaseDeg = (phaseRad * 180) / Math.PI;
          items.push({ index: i, ket, bitstring: ket, prob, probability: prob, re: r, im, phaseDeg });
        }
      }
      return items;
    }

    getQubitMarginals(usePreMeasurement = false) {
      const reArr = (usePreMeasurement && this.preMeasureRe) ? this.preMeasureRe : this.re;
      const imArr = (usePreMeasurement && this.preMeasureIm) ? this.preMeasureIm : this.im;
      const marginals = [];
      for (let q = 0; q < this.numQubits; q++) {
        const mask = 1 << (this.numQubits - 1 - q);
        let p1 = 0;
        for (let i = 0; i < this.dim; i++) {
          if (i & mask) {
            p1 += reArr[i] * reArr[i] + imArr[i] * imArr[i];
          }
        }
        const prob0 = Math.max(0, 1 - p1);
        const prob1 = Math.min(1, p1);
        marginals.push({
          qubit: q,
          prob0,
          prob1,
          p0: prob0,
          p1: prob1,
          isPointer: q === this.pointer,
          isHead: q === this.pointer
        });
      }
      return marginals;
    }
  }

  function getStateDistribution(vm, usePreMeasurement = true) {
    return vm.getStateDistribution(usePreMeasurement);
  }

  function getQubitMarginals(vm, usePreMeasurement = false) {
    return vm.getQubitMarginals(usePreMeasurement);
  }

  function gcd(a, b) {
    a = Math.abs(a);
    b = Math.abs(b);
    while (b !== 0) {
      const t = b;
      b = a % b;
      a = t;
    }
    return a;
  }

  function modPow(base, exp, mod) {
    let result = 1;
    let b = base % mod;
    let e = exp;
    while (e > 0) {
      if (e & 1) result = (result * b) % mod;
      b = (b * b) % mod;
      e >>= 1;
    }
    return result;
  }

  /** Shor's classical post-processing for a *verified* order r of a modulo N. */
  function factorsFromOrder(a, r, N) {
    if (r === null || r === undefined || r % 2 !== 0) return null;
    const x = modPow(a, r / 2, N);
    if (x === N - 1) return null;
    const out = [];
    for (const g of [gcd(x - 1, N), gcd(x + 1, N)]) {
      if (g > 1 && g < N && !out.includes(g)) out.push(g);
    }
    out.sort((p, q) => p - q);
    return out.length ? out : null;
  }

  /**
   * Phase, period and factor extraction for Shor N = 15 (2 phase bits).
   * The candidate order r' (continued-fraction denominator) is accepted only if a^r' = 1 (mod N);
   * otherwise small multiples k*r' are tried (standard post-processing when gcd(s, r) > 1),
   * reported as recoveredOrder / recoveredFactors.
   */
  function analyzeShor15(bitstringOrCounts, isRecycledOrMode = false, a = 7, N = 15) {
    const isRecycled = isRecycledOrMode === true || isRecycledOrMode === 'recycled';

    if (bitstringOrCounts && typeof bitstringOrCounts === 'object') {
      let totalShots = 0;
      let factoringShots = 0;
      let recoveredShots = 0;
      let foundFactors = null;
      for (const [bstr, cnt] of Object.entries(bitstringOrCounts)) {
        totalShots += cnt;
        const res = analyzeShor15(bstr, isRecycled, a, N);
        if (res.factors) {
          factoringShots += cnt;
          foundFactors = res.factors;
        }
        if (res.recoveredFactors) {
          recoveredShots += cnt;
          if (!foundFactors) foundFactors = res.recoveredFactors;
        }
      }
      return { totalShots, factoringShots, recoveredShots, factors: foundFactors };
    }

    const bitstring = String(bitstringOrCounts || '');
    const result = {
      bitstring,
      phaseBits: '0.00',
      phase: 0,
      fraction: '0/1',
      candidateOrder: null,
      orderVerified: false,
      order: null,
      recoveredOrder: null,
      factors: null,
      recoveredFactors: null
    };
    if (bitstring.length < 2 || !/^[01]{2}/.test(bitstring)) {
      return result;
    }
    const b0 = parseInt(bitstring[0], 10);
    const b1 = parseInt(bitstring[1], 10);
    // Full register (no final SWAP in QFT^dagger): c0 = MSB phi1, c1 = LSB phi2.
    // Semiclassical recycling: the first measured bit is the LSB phi2, the second the MSB phi1.
    const phi1 = isRecycled ? b1 : b0;
    const phi2 = isRecycled ? b0 : b1;
    const s = phi1 * 2 + phi2;
    result.phaseBits = `0.${phi1}${phi2}`;
    result.phase = s / 4.0;
    if (s === 0) return result;

    const g = gcd(s, 4);
    const num = s / g;
    const rCand = 4 / g;
    const verified = modPow(a, rCand, N) === 1;
    const order = verified ? rCand : null;
    let recovered = order;
    if (!verified) {
      for (let k = 2; k * rCand < N; k++) { // the true order divides phi(N) < N
        if (modPow(a, k * rCand, N) === 1) {
          recovered = k * rCand;
          break;
        }
      }
    }
    result.fraction = `${num}/${rCand}`;
    result.candidateOrder = rCand;
    result.orderVerified = verified;
    result.order = order;
    result.recoveredOrder = recovered;
    result.factors = factorsFromOrder(a, order, N);
    result.recoveredFactors = factorsFromOrder(a, recovered, N);
    return result;
  }

  // -------------------------------------------------------------------------------------------
  // OpenQASM 3.0 lowering. Gates are normalised to {name, target, controls:Set}; '^' at p is
  // x on p+1 controlled by p. Profile C blocks use conjugation-aware lowering based on
  //     C(V U V^-1) = V C(U) V^-1,
  // so gates undone inside the block never receive the extra control.
  // -------------------------------------------------------------------------------------------
  const TOKEN_GATE = { '+': 'x', 'Z': 'z', 'H': 'h', 'T': 't', '-': 'tdg' };
  const INVERSE = { x: 'x', z: 'z', h: 'h', t: 'tdg', tdg: 't', s: 'sdg', sdg: 's' };
  const PHASE_EIGHTHS = { t: 1, s: 2, z: 4, sdg: 6, tdg: 7 };
  const EIGHTHS_TO_GATES = [[], ['t'], ['s'], ['z', 'tdg'], ['z'], ['z', 't'], ['sdg'], ['tdg']];
  const MAX_DP_GATES = 120;

  function mcxCost(k) {
    if (k <= 0) return 0;
    if (k === 1) return 1;
    if (k === 2) return 6;
    return 12 * (k - 2) + 6;
  }

  /** CNOT-equivalents of gate `name` with k controls (CX/CZ/CH = 1, controlled phase = 2, Toffoli = 6). */
  function gateCost(name, k) {
    if (k === 0) return 0;
    if (name === 'x' || name === 'z' || name === 'h') return mcxCost(k);
    return 2 * mcxCost(k);
  }

  function mkGate(name, target, controls) {
    return { name, target, controls: [...controls].sort((a, b) => a - b) };
  }
  function sameGate(a, b) {
    return a.name === b.name && a.target === b.target &&
      a.controls.length === b.controls.length && a.controls.every((c, i) => c === b.controls[i]);
  }
  function sameControls(a, b) {
    return a.length === b.length && a.every((c, i) => c === b[i]);
  }
  function withControl(g, ctrl) {
    const s = new Set(g.controls);
    s.add(ctrl);
    return mkGate(g.name, g.target, s);
  }

  function formatGate(g) {
    const k = g.controls.length;
    const tq = `q[${g.target}]`;
    if (k === 0) return `${g.name} ${tq};`;
    const cl = g.controls.map((c) => `q[${c}]`).join(', ');
    if (k === 1) {
      const native = { x: 'cx', z: 'cz', h: 'ch' };
      if (native[g.name]) return `${native[g.name]} ${cl}, ${tq};`;
      return `ctrl @ ${g.name} ${cl}, ${tq};`;
    }
    if (k === 2 && g.name === 'x') return `ccx ${cl}, ${tq};`;
    return `ctrl(${k}) @ ${g.name} ${cl}, ${tq};`;
  }

  function fusePhases(gates) {
    const out = [];
    let i = 0;
    while (i < gates.length) {
      const g = gates[i];
      if (PHASE_EIGHTHS[g.name] !== undefined) {
        let total = 0;
        let j = i;
        while (j < gates.length && PHASE_EIGHTHS[gates[j].name] !== undefined &&
               gates[j].target === g.target && sameControls(gates[j].controls, g.controls)) {
          total += PHASE_EIGHTHS[gates[j].name];
          j++;
        }
        for (const nm of EIGHTHS_TO_GATES[total % 8]) out.push(mkGate(nm, g.target, g.controls));
        i = j;
      } else {
        out.push(g);
        i++;
      }
    }
    return out;
  }

  function lessCost(a, b) {
    return a[0] < b[0] || (a[0] === b[0] && a[1] < b[1]);
  }

  function lowerControlled(gates, ctrl, optimize = true) {
    const n = gates.length;
    if (!optimize || n === 0 || n > MAX_DP_GATES) return gates.map((g) => withControl(g, ctrl));
    const inv = gates.map((g) => mkGate(INVERSE[g.name], g.target, g.controls));
    const ucost = gates.map((g) => gateCost(g.name, g.controls.length));
    const best = new Map();
    const key = (i, j) => i * (n + 1) + j;
    for (let length = 1; length <= n; length++) {
      for (let i = 0; i + length <= n; i++) {
        const j = i + length;
        if (length === 1) {
          const g = gates[i];
          const k = g.controls.includes(ctrl) ? g.controls.length : g.controls.length + 1;
          best.set(key(i, j), { cost: [gateCost(g.name, k), 1], choice: ['leaf'] });
          continue;
        }
        let candCost = null;
        let candChoice = null;
        for (let k = i + 1; k < j; k++) {
          const a = best.get(key(i, k)).cost;
          const b = best.get(key(k, j)).cost;
          const c = [a[0] + b[0], a[1] + b[1]];
          if (candCost === null || lessCost(c, candCost)) {
            candCost = c;
            candChoice = ['split', k];
          }
        }
        let uc = 0;
        for (let L = 1; 2 * L <= length && sameGate(inv[i + L - 1], gates[j - L]); L++) {
          uc += ucost[i + L - 1] + ucost[j - L];
          let c;
          if (2 * L === length) {
            c = [0, 0];
          } else {
            const inner = best.get(key(i + L, j - L)).cost;
            c = [uc + inner[0], 2 * L + inner[1]];
          }
          if (lessCost(c, candCost)) {
            candCost = c;
            candChoice = ['conj', L];
          }
        }
        best.set(key(i, j), { cost: candCost, choice: candChoice });
      }
    }
    const out = [];
    const build = (i, j) => {
      const ch = best.get(key(i, j)).choice;
      if (ch[0] === 'leaf') {
        out.push(withControl(gates[i], ctrl));
      } else if (ch[0] === 'split') {
        build(i, ch[1]);
        build(ch[1], j);
      } else {
        const L = ch[1];
        if (2 * L === j - i) return;
        for (let t = i; t < i + L; t++) out.push(gates[t]);
        build(i + L, j - L);
        for (let t = j - L; t < j; t++) out.push(gates[t]);
      }
    };
    build(0, n);
    return out;
  }

  /** Lowers C_ctrl(gates) with and without phase fusion and keeps the cheaper result. */
  function lowerBest(gates, ctrl, optimize = true) {
    if (!optimize) return lowerControlled(gates, ctrl, false);
    const cost = (gs) => [gs.reduce((acc, g) => acc + gateCost(g.name, g.controls.length), 0), gs.length];
    const fused = lowerControlled(fusePhases(gates), ctrl, true);
    const plain = lowerControlled(gates, ctrl, true);
    const cf = cost(fused);
    const cp = cost(plain);
    return (cf[0] < cp[0] || (cf[0] === cp[0] && cf[1] <= cp[1])) ? fused : plain;
  }

  function collectBlockGates(toks, startP, nQubits, optimize) {
    const bm = matchBrackets(toks);
    let p = startP;
    const out = [];
    for (let i = 0; i < toks.length; i++) {
      const ch = toks[i];
      if (ch === '>') p = (p + 1) % nQubits;
      else if (ch === '<') p = (p - 1 + nQubits) % nQubits;
      else if (TOKEN_GATE[ch]) out.push(mkGate(TOKEN_GATE[ch], p, []));
      else if (ch === '^') {
        const qNext = (p + 1) % nQubits;
        if (qNext === p) throw new RangeError("'^' (CNOT) requires a tape of at least 2 qubits");
        out.push(mkGate('x', qNext, [p]));
      } else if (ch === '[') {
        const closeIdx = bm.get(i);
        let inner = collectBlockGates(toks.slice(i + 1, closeIdx), p, nQubits, optimize);
        for (const g of lowerBest(inner, p, optimize)) out.push(g);
        i = closeIdx;
      }
    }
    return out;
  }

  // -------------------------------------------------------------------------------------------
  // Linear-nearest-neighbour (LNN) backend: exact decomposition of every 3+-qubit gate into
  // 1-/2-qubit gates, then SWAP routing on an open chain with a tracked logical->physical layout
  // (dynamic loop bodies restore their entry layout). Angles are exact multiples of pi {n, d}.
  // -------------------------------------------------------------------------------------------
  function frac(n, d) {
    const g = gcd(n, d) || 1;
    return { n: n / g, d: d / g };
  }
  const halfA = (a) => frac(a.n, a.d * 2);
  const negA = (a) => ({ n: -a.n, d: a.d });
  const PHASE_ANGLE = { t: frac(1, 4), tdg: frac(-1, 4), s: frac(1, 2), sdg: frac(-1, 2), z: frac(1, 1) };
  const CTRL_2Q = { x: 'cx', z: 'cz', h: 'ch' };

  function fmtAngle(a) {
    if (a.n === 0) return '0';
    const sign = a.n < 0 ? '-' : '';
    const num = Math.abs(a.n);
    const core = num === 1 ? 'pi' : `${num}*pi`;
    return a.d === 1 ? `${sign}${core}` : `${sign}${core}/${a.d}`;
  }

  const op1 = (name, q, ang = null) => ({ k: 1, name, a: q, ang });
  const op2 = (name, a, b, ang = null) => ({ k: 2, name, a, b, ang });

  function mcphase(controls, t, ang) {
    if (controls.length === 0) return [op1('p', t, ang)];
    if (controls.length === 1) return [op2('cp', controls[0], t, ang)];
    const ck = controls[controls.length - 1];
    const rest = controls.slice(0, -1);
    return [op2('cp', ck, t, halfA(ang))].concat(mcx(rest, ck), [op2('cp', ck, t, negA(halfA(ang)))],
      mcx(rest, ck), mcphase(rest, t, halfA(ang)));
  }

  function mcx(controls, t) {
    const k = controls.length;
    if (k === 0) return [op1('x', t)];
    if (k === 1) return [op2('cx', controls[0], t)];
    if (k === 2) {
      const [a, b] = controls;
      return [
        op1('h', t), op2('cx', b, t), op1('tdg', t), op2('cx', a, t),
        op1('t', t), op2('cx', b, t), op1('tdg', t), op2('cx', a, t),
        op1('t', b), op1('t', t), op1('h', t), op2('cx', a, b),
        op1('t', a), op1('tdg', b), op2('cx', a, b)
      ];
    }
    return [op1('h', t)].concat(mcphase(controls, t, frac(1, 1)), [op1('h', t)]);
  }

  function decomposeGate(g) {
    const cs = g.controls;
    const k = cs.length;
    const t = g.target;
    if (k === 0) return [op1(g.name, t)];
    if (k === 1) return [op2(CTRL_2Q[g.name] || `ctrl @ ${g.name}`, cs[0], t)];
    if (g.name === 'x') return mcx(cs, t);
    if (g.name === 'z') return [op1('h', t)].concat(mcx(cs, t), [op1('h', t)]);
    if (g.name === 'h') {
      // H = Ry(pi/4) Z Ry(-pi/4) -> time order: ry(-pi/4), C^k Z, ry(pi/4)
      return [op1('ry', t, frac(-1, 4)), op1('h', t)].concat(mcx(cs, t), [op1('h', t), op1('ry', t, frac(1, 4))]);
    }
    return mcphase(cs, t, PHASE_ANGLE[g.name]);
  }

  function formatOp(op, phys) {
    const head = op.ang === null ? op.name : `${op.name}(${fmtAngle(op.ang)})`;
    if (op.k === 1) return `${head} q[${phys[op.a]}];`;
    return `${head} q[${phys[op.a]}], q[${phys[op.b]}];`;
  }

  class LnnRouter {
    constructor(n) {
      this.n = n;
      this.l2p = Array.from({ length: n }, (_, i) => i);
      this.p2l = Array.from({ length: n }, (_, i) => i);
      this.swaps = 0;
    }
    swapPhys(i, j, out, indent) {
      out.push(`${indent}swap q[${i}], q[${j}];`);
      const li = this.p2l[i];
      const lj = this.p2l[j];
      this.p2l[i] = lj;
      this.p2l[j] = li;
      this.l2p[li] = j;
      this.l2p[lj] = i;
      this.swaps++;
    }
    lookaheadCost(l2p, upcoming) {
      let cost = 0;
      upcoming.forEach((op, w) => {
        cost += (Math.abs(l2p[op.a] - l2p[op.b]) - 1) * (upcoming.length - w);
      });
      return cost;
    }
    route(op, out, indent, upcoming = []) {
      if (op.k === 2) {
        const a = op.a;
        const b = op.b;
        while (Math.abs(this.l2p[a] - this.l2p[b]) > 1) {
          const pa = this.l2p[a];
          const pb = this.l2p[b];
          const step = pb > pa ? 1 : -1;
          const cands = [[pa, pa + step], [pb, pb - step]];
          let best = cands[0];
          let bestCost = null;
          for (const [i, j] of cands) {
            const trial = this.l2p.slice();
            const li = this.p2l[i];
            const lj = this.p2l[j];
            trial[li] = j;
            trial[lj] = i;
            const c = this.lookaheadCost(trial, upcoming);
            if (bestCost === null || c < bestCost) {
              best = [i, j];
              bestCost = c;
            }
          }
          this.swapPhys(Math.min(best[0], best[1]), Math.max(best[0], best[1]), out, indent);
        }
      }
      out.push(indent + formatOp(op, this.l2p));
    }
    routeSequence(ops, out, indent, windowSize = 8) {
      const twoQ = [];
      ops.forEach((op, k) => { if (op.k === 2) twoQ.push(k); });
      let pos = 0;
      ops.forEach((op, k) => {
        while (pos < twoQ.length && twoQ[pos] <= k) pos++;
        const upcoming = twoQ.slice(pos, pos + windowSize).map((t) => ops[t]);
        this.route(op, out, indent, upcoming);
      });
    }
    restore(target, out, indent) {
      for (let pos = 0; pos < this.n; pos++) {
        const want = target.indexOf(pos);
        let cur = this.l2p[want];
        while (cur > pos) {
          this.swapPhys(cur - 1, cur, out, indent);
          cur--;
        }
      }
    }
  }

  // Program IR: {kind:'comment',text} | {kind:'gate',g} | {kind:'measure',k,q} | {kind:'reset',q}
  //             | {kind:'loop',p,body}
  function buildIR(tokens, nQubits, optimize) {
    let measIdx = 0;
    let hasLoop = false;
    function build(toks, bm, startP) {
      const items = [];
      let p = startP;
      for (let i = 0; i < toks.length; i++) {
        const ch = toks[i];
        if (ch === '>') p = (p + 1) % nQubits;
        else if (ch === '<') p = (p - 1 + nQubits) % nQubits;
        else if (TOKEN_GATE[ch]) items.push({ kind: 'gate', g: mkGate(TOKEN_GATE[ch], p, []) });
        else if (ch === '^') {
          const qNext = (p + 1) % nQubits;
          if (qNext === p) throw new RangeError("'^' (CNOT) requires a tape of at least 2 qubits");
          items.push({ kind: 'gate', g: mkGate('x', qNext, [p]) });
        } else if (ch === '.') {
          items.push({ kind: 'measure', k: measIdx++, q: p });
        } else if (ch === ',') {
          items.push({ kind: 'reset', q: p });
        } else if (ch === '[') {
          const closeIdx = bm.get(i);
          const inner = toks.slice(i + 1, closeIdx);
          if (isCoherentBlock(inner, p, nQubits)) {
            items.push({ kind: 'comment', text: `Profile C: Coherent Controlled Unitary on q[${p}]` });
            const gates = collectBlockGates(inner, p, nQubits, optimize);
            for (const g of lowerBest(gates, p, optimize)) items.push({ kind: 'gate', g });
          } else {
            hasLoop = true;
            const sub = build(inner, matchBrackets(inner), p);
            if (sub.p !== p) {
              throw new Error(
                `Profile D loop at q[${p}] has non-zero net pointer displacement; the head position ` +
                'after the loop is data-dependent and cannot be resolved statically'
              );
            }
            items.push({ kind: 'comment', text: `Profile D: Dynamic Copenhagen Loop on q[${p}]` });
            items.push({ kind: 'loop', p, body: sub.items });
          }
          i = closeIdx;
        }
      }
      return { items, p };
    }
    const res = build(tokens, matchBrackets(tokens), 0);
    return { items: res.items, nMeas: measIdx, hasLoop };
  }

  /**
   * Syntax-directed |BF> -> OpenQASM 3.0 transpiler.
   *  - Pointer shifts are resolved at compile time (zero emitted gates).
   *  - Each '.' token writes its own transcript bit c[k] (k = static occurrence index), so repeated
   *    measurements of one cell (semiclassical recycling) never overwrite earlier results.
   *  - Profile C bodies are lowered to (multi-)controlled gates; with optimize=true (default) only
   *    gates not undone inside the block are controlled and adjacent phase gates are merged.
   *  - Profile D loops use guard[p]; their bodies must have zero net displacement, because the
   *    head position after a dynamic loop must be known statically.
   *  - options.lnn=true targets an open linear chain: exact decomposition into 1-/2-qubit gates and
   *    SWAP routing so every 2-qubit gate acts on adjacent qubits (options.restoreLayout returns
   *    each logical qubit to its own physical qubit at the end).
   */
  function transpileToQASM3(rawCode, numQubits = null, options = null) {
    const opts = options || {};
    const optimize = opts.optimize !== false;
    const lnn = opts.lnn === true;
    const tokens = cleanCode(rawCode);
    const nQubits = numQubits || inferQubitCount(tokens);
    const { items, nMeas, hasLoop } = buildIR(tokens, nQubits, optimize);
    const body = [];
    const router = lnn ? new LnnRouter(nQubits) : null;

    function emit(seq, indent) {
      const pending = [];
      const flush = () => {
        if (pending.length) {
          router.routeSequence(pending, body, indent);
          pending.length = 0;
        }
      };
      for (const it of seq) {
        if (it.kind === 'gate') {
          if (!router) body.push(indent + formatGate(it.g));
          else for (const op of decomposeGate(it.g)) pending.push(op);
          continue;
        }
        if (router) flush();
        if (it.kind === 'comment') {
          body.push(`${indent}// ${it.text}`);
        } else if (it.kind === 'measure') {
          body.push(`${indent}c[${it.k}] = measure q[${router ? router.l2p[it.q] : it.q}];`);
        } else if (it.kind === 'reset') {
          body.push(`${indent}reset q[${router ? router.l2p[it.q] : it.q}];`);
        } else {
          const p = it.p;
          const q = router ? router.l2p[p] : p;
          const saved = router ? router.l2p.slice() : null;
          body.push(`${indent}guard[${p}] = measure q[${q}];`);
          body.push(`${indent}while (guard[${p}] == 1) {`);
          emit(it.body, indent + '    ');
          if (router) router.restore(saved, body, indent + '    ');
          body.push(`${indent}    guard[${p}] = measure q[${q}];`);
          body.push(`${indent}}`);
        }
      }
      if (router) flush();
    }

    emit(items, '');
    if (router) {
      if (opts.restoreLayout) router.restore(Array.from({ length: nQubits }, (_, i) => i), body, '');
      const layout = router.l2p.map((p, l) => `${l}->${p}`).join(', ');
      body.push(`// final layout (logical->physical): ${layout}`);
    }

    const header = ['OPENQASM 3.0;', 'include "stdgates.inc";', '', `qubit[${nQubits}] q;`];
    if (nMeas) header.push(`bit[${nMeas}] c;  // measurement transcript, one bit per '.' token`);
    if (hasLoop) header.push(`bit[${nQubits}] guard;  // dynamic-loop test bits`);
    if (lnn) header.push('// LNN-routed for an open linear chain: every 2-qubit gate acts on adjacent qubits');
    header.push('');
    return header.concat(body).join('\n');
  }

  /**
   * Resource statistics of the OpenQASM lowering: emitted gate counts, CNOT-equivalents (SWAP = 3),
   * multi-qubit gate count, routing SWAPs, maximum physical interaction distance (1 = nearest
   * neighbour) and ASAP depth (dynamic loop bodies counted once).
   */
  function resourceReport(rawCode, numQubits = null, options = null) {
    const opts = options || {};
    const optimize = opts.optimize !== false;
    const lnn = opts.lnn === true;
    const tokens = cleanCode(rawCode);
    const nQubits = numQubits || inferQubitCount(tokens);
    const qasm = transpileToQASM3(rawCode, nQubits, { optimize, lnn });
    const mnemonic = { cx: ['x', 1], cz: ['z', 1], ch: ['h', 1], ccx: ['x', 2], cp: ['p', 1] };
    const counts = {};
    let cnotEq = 0;
    let multi = 0;
    let maxDist = 0;
    let loops = 0;
    const level = new Array(nQubits).fill(0);
    for (const raw of qasm.split('\n')) {
      const line = raw.split('//')[0].trim();
      if (!line || /^(OPENQASM|include|qubit|bit|\})/.test(line)) continue;
      if (line.startsWith('while')) { loops++; continue; }
      const qs = [...line.matchAll(/q\[(\d+)\]/g)].map((m) => parseInt(m[1], 10));
      let key;
      if (line.includes('measure')) key = 'measure';
      else if (line.startsWith('reset')) key = 'reset';
      else {
        const m = line.match(/^(?:ctrl(?:\((\d+)\))? @ )?([a-z]+)(?:\(([^)]*)\))? (.*);/);
        if (!m) continue;
        const name = m[2];
        key = line.startsWith('ctrl') ? line.split(' q[')[0] : name;
        if (name === 'swap') {
          cnotEq += 3;
        } else {
          const kMod = m[1] ? parseInt(m[1], 10) : (line.startsWith('ctrl @') ? 1 : 0);
          let base = name;
          let k = kMod;
          if (mnemonic[name] && kMod === 0) [base, k] = mnemonic[name];
          cnotEq += gateCost(base, k);
        }
        if (qs.length >= 2) {
          multi++;
          maxDist = Math.max(maxDist, Math.max(...qs) - Math.min(...qs));
        }
      }
      counts[key] = (counts[key] || 0) + 1;
      const layer = Math.max(...qs.map((q) => level[q])) + 1;
      for (const q of qs) level[q] = layer;
    }
    const gateCounts = {};
    for (const [k, v] of Object.entries(counts)) if (k !== 'measure' && k !== 'reset') gateCounts[k] = v;
    return {
      tokens: tokens.length,
      qubits: nQubits,
      nativeCnotTokens: tokens.split('').filter((t) => t === '^').length,
      gateCounts,
      measurements: counts.measure || 0,
      resets: counts.reset || 0,
      dynamicLoops: loops,
      multiQubitGates: multi,
      swaps: counts.swap || 0,
      maxInteractionDistance: maxDist,
      cnotEquivalents: cnotEq,
      depth: level.length ? Math.max(...level) : 0,
      optimized: optimize,
      lnn
    };
  }

  /**
   * Monte Carlo sampling. `profile` is accepted for API compatibility only (the loop profile is
   * chosen per block automatically). Pass a numeric `seed` for reproducible results.
   */
  function sampleShots(rawCode, numQubits = null, shots = 512, profile = null, seed = null) {
    const tokens = cleanCode(rawCode);
    const nQubits = numQubits || inferQubitCount(tokens);
    const vm = new BraKetFuckVM(nQubits, { seed });
    const counts = {};
    const history = [];
    for (let s = 0; s < shots; s++) {
      const out = vm.run(tokens);
      const key = out || '(no readout)';
      counts[key] = (counts[key] || 0) + 1;
      history.push(key);
    }
    Object.defineProperty(counts, 'history', {
      value: history,
      writable: true,
      enumerable: false,
      configurable: true
    });
    return counts;
  }

  return {
    BraKetFuckVM,
    cleanCode,
    inferQubitCount,
    matchBrackets,
    isCoherentBlock,
    getInstructionStats,
    getStateDistribution,
    getQubitMarginals,
    analyzeShor15,
    transpileToQASM3,
    resourceReport,
    gateCost,
    sampleShots
  };
});
