// PageHandler._clickPacing: a press waits its dwell from when the page got the move.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {load} from './gecko.mjs';

await load('input/HumanDelay.js');

// The virtual clock is the parent's: sleeping advances it, nothing else does.
let now = 5000;
const realImport = ChromeUtils.importESModule;
const stub = new Proxy({}, {get: () => class {}});
ChromeUtils.now = () => now;
ChromeUtils.importESModule = url => {
  if (url.endsWith('Timer.sys.mjs'))
    return {setTimeout: (fn, ms) => { now += ms; fn(); }};
  try {
    return realImport(url);
  } catch {
    return stub;
  }
};
const {PageHandler} = await import('../../additions/juggler/protocol/PageHandler.js');

// random() of 0.5 then 0.25 is a standard normal of 0, so a dwell is its median.
const medianDraws = [0.5, 0.25];
let draw = 0;
Math.random = () => medianDraws[draw++ % 2];

async function pressAfterMove(state) {
  now = 5000;
  const self = {_mouseDispatched: Promise.resolve(), _arrival: Promise.resolve(), ...state};
  await PageHandler.prototype._clickPacing.call(self, 'mousedown', 1);
  return now - 5000;
}

test('the dwell counts from the move reaching the page, not from the queue ack', async () => {
  // The ack came 10 ms before the page had the move; the page has it now.
  const waited = await pressAfterMove({_movedAt: 4990, _arrivedAt: 5000});
  assert.equal(Math.round(waited), 125);
});

test('with no arrival the queue ack stamp stands', async () => {
  const waited = await pressAfterMove({_movedAt: 4990, _arrivedAt: undefined});
  assert.equal(Math.round(waited), 115);
});

test('a press with no move before it waits for nothing', async () => {
  assert.equal(await pressAfterMove({}), 0);
});
