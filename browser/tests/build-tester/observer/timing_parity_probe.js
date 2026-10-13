/**
 * Timing-parity probe: anti-detection integrity test for the observer ring buffer.
 *
 * PURPOSE:
 * Run this probe against the SAME binary twice:
 *   1. With CAMOU_OBSERVE=1 (armed: instrumentation emit is active)
 *   2. Unset (unarmed: instrumentation emit is inactive)
 *
 * The armed run's median/p95/variance for canvas.toDataURL() and gl.getParameter()
 * MUST stay within the unarmed build's own run-to-run noise band.
 * If armed is measurably slower or higher-variance, the ring-buffer hot path
 * is doing too much — the emit must be push-only (Task 1/2 issue).
 *
 * MEASUREMENT:
 * - Times a tight loop of N (e.g., 2000) iterations of each instrumented op
 * - Runs M (e.g., 10) trials and collects per-trial op duration
 * - Computes median, p95 percentile, and variance across trials
 * - Outputs JSON: { toDataURL: {median, p95, variance, n}, getParameter: {...} }
 *
 * OUTPUT:
 * - console.log(JSON) at end of script
 * - window.__timingResult__ = { toDataURL: {...}, getParameter: {...} }
 *
 * DEFENSIVE:
 * - Skips canvas/webgl metrics if unavailable (guard with try-catch)
 * - Never throws; reports null or skips missing metrics
 */

(function() {
  'use strict';

  /**
   * Compute percentile from sorted array of numbers.
   * @param {number[]} sorted - Array of values, sorted in ascending order.
   * @param {number} p - Percentile (0-100).
   * @returns {number}
   */
  function percentile(sorted, p) {
    if (sorted.length === 0) return NaN;
    const idx = (p / 100) * (sorted.length - 1);
    const lower = Math.floor(idx);
    const upper = Math.ceil(idx);
    if (lower === upper) return sorted[lower];
    const weight = idx - lower;
    return sorted[lower] * (1 - weight) + sorted[upper] * weight;
  }

  /**
   * Compute sample variance of array.
   * @param {number[]} arr - Array of numbers.
   * @returns {number}
   */
  function variance(arr) {
    if (arr.length < 2) return 0;
    const m = arr.reduce((a, b) => a + b, 0) / arr.length;
    const sumSq = arr.reduce((a, b) => a + (b - m) ** 2, 0);
    return sumSq / (arr.length - 1);
  }

  /**
   * Time a tight loop of `op`, `iterations` calls per trial, over `trials` trials.
   * Sorts the per-trial durations once and derives median + p95 from it.
   * @param {() => void} op - The operation to time (called `iterations`× per trial).
   * @param {number} iterations
   * @param {number} trials
   * @returns {{median: number, p95: number, variance: number, n: number}}
   */
  function timeTrials(op, iterations, trials) {
    const trialTimes = [];
    for (let trial = 0; trial < trials; trial++) {
      const start = performance.now();
      for (let i = 0; i < iterations; i++) op();
      trialTimes.push(performance.now() - start);
    }
    const sorted = trialTimes.slice().sort((a, b) => a - b);
    return {
      median: percentile(sorted, 50),
      p95: percentile(sorted, 95),
      variance: variance(trialTimes),
      n: trials,
    };
  }

  /**
   * Time canvas.toDataURL() — the 2D canvas readback emit site.
   * @returns {{median, p95, variance, n} | null}
   */
  function timeCanvasToDataURL(iterations, trials) {
    try {
      const canvas = document.createElement('canvas');
      canvas.width = 256;
      canvas.height = 256;
      const ctx = canvas.getContext('2d');
      if (!ctx) return null;
      // Fill canvas with some data so toDataURL() isn't a no-op.
      ctx.fillStyle = 'rgba(100, 150, 200, 0.8)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      return timeTrials(() => canvas.toDataURL('image/png'), iterations, trials);
    } catch (e) {
      return null;
    }
  }

  /**
   * Time gl.getParameter(gl.VENDOR) — a non-instrumented control op.
   * @returns {{median, p95, variance, n} | null}
   */
  function timeWebGLGetParameter(iterations, trials) {
    try {
      const canvas = document.createElement('canvas');
      const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
      if (!gl) return null;
      return timeTrials(() => gl.getParameter(gl.VENDOR), iterations, trials);
    } catch (e) {
      return null;
    }
  }

  // Configuration: adjust for test environment needs.
  const CANVAS_ITERATIONS = 2000;
  const WEBGL_ITERATIONS = 2000;
  const TRIALS = 10;

  // Run measurements.
  const result = {
    toDataURL: timeCanvasToDataURL(CANVAS_ITERATIONS, TRIALS),
    getParameter: timeWebGLGetParameter(WEBGL_ITERATIONS, TRIALS)
  };

  // Output to console.
  console.log(JSON.stringify(result, null, 2));

  // Attach to window for harness inspection.
  window.__timingResult__ = result;
})();
