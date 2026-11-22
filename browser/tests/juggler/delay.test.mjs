// HumanDelay: the normal draw, its mean and spread, and its bounds.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {load} from './gecko.mjs';

const {normalDelay} = await load('input/HumanDelay.js');

// mulberry32: the draws stay the same from run to run.
function seeded(seed) {
  return () => {
    seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 2 ** 32;
  };
}

function draws(n, mean, sd, min = 0, max = Infinity) {
  const random = seeded(1234);
  return Array.from({length: n}, () => normalDelay(mean, sd, min, max, random));
}

test('draws centre on the mean with the given spread', () => {
  const xs = draws(20000, 110, 30, -Infinity, Infinity);
  const mean = xs.reduce((a, b) => a + b, 0) / xs.length;
  const sd = Math.sqrt(xs.reduce((a, b) => a + (b - mean) ** 2, 0) / xs.length);
  assert.ok(Math.abs(mean - 110) < 1, `mean ${mean}`);
  assert.ok(Math.abs(sd - 30) < 1, `sd ${sd}`);
});

test('a draw is inside its bounds and none lands on one', () => {
  const xs = draws(20000, 110, 30, 50, 180);
  assert.ok(Math.min(...xs) > 50 && Math.max(...xs) < 180);
  assert.equal(xs.filter(x => x === 50 || x === 180).length, 0);
});

test('without a maximum the upper tail is kept', () => {
  assert.ok(Math.max(...draws(20000, 110, 30, 50)) > 200);
});

test('the same stream gives the same delays', () => {
  assert.deepEqual(draws(5, 110, 30, 50), draws(5, 110, 30, 50));
});

// Every caller's figures (content/PageAgent.js). A clamp puts the mass beyond a bound on the bound
// itself: 7.8% of keyInterval's draws landed on 80 ms (#467).
const callers = [
  ['keyHold', [116.25, 23.88, 50]],
  ['keyInterval', [238.66, 111.6, 80]],
  ['modifierLead', [62.5, 16, 35]],
  ['modifierTrail', [42.5, 13, 20]],
];

for (const [name, [mean, sd, min]] of callers) {
  test(`${name}: no draw lands on its bound`, () => {
    const xs = draws(20000, mean, sd, min);
    const onBound = xs.filter(x => x === min).length;
    assert.equal(onBound, 0, `${onBound} of ${xs.length} draws on the bound`);
    assert.ok(xs.every(x => x >= min));
  });
}

test('a random source that never yields a draw inside the bounds fails loudly', () => {
  assert.throws(() => normalDelay(100, 10, 0, 50, () => 0.5), /no draw within/);
});
