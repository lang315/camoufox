// MouseDispatch.sendTrajectoryAcked: a curve leaves the page as soon as the
// move before the exit is dispatched, not when the renderer acks it (#472).
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {load, provide} from './gecko.mjs';

// Helper.js needs XPCOM; MouseDispatch uses it only to scroll a point into view.
provide('Helper.js', {Helper: class {}});
const {MouseDispatch} = await load('input/MouseDispatch.js');

const TOP = 85;

/** A chrome window whose dispatches are logged, and acks the test releases. */
function harness() {
  const log = [];
  let id = 0;
  const pending = [];
  const box = {left: 0, top: TOP, width: 800, height: 600};
  // The parent dispatches every event in the content to the browser.
  const browser = {getBoundingClientRect: () => box, closest: () => null};
  const listeners = [];
  const win = {
    innerWidth: 1000,
    innerHeight: 800,
    MouseEvent: {MOZ_SOURCE_MOUSE: 1},
    addEventListener: (type, listener) => listeners.push({type, listener}),
    windowUtils: {
      DEFAULT_MOUSE_POINTER_ID: 0,
      toTopLevelWidgetRect: () => ({width: 1}),
      jugglerSendMouseEvent: (type, x, y) => {
        log.push([type, x, y - TOP]);
        for (const l of listeners.filter(l => l.type === type))
          l.listener({type, originalTarget: browser});
        return ++id;
      },
    },
  };
  const watcher = {
    ensureEventWithin: () => new Promise(resolve => pending.push(() => resolve({}))),
  };
  const dispatch = new MouseDispatch(win, box, {}, browser);
  // Release every ack asked for so far, as the renderer would.
  const ack = () => pending.splice(0).forEach(release => release());
  return {log, watcher, dispatch, ack};
}

const inOrder = async (plan, dispatchStep) => {
  for (const [i, step] of plan.steps.entries()) {
    if (!await dispatchStep(step, i))
      return;
  }
};

const settle = () => new Promise(resolve => setTimeout(resolve, 10));

/** Whether a promise has settled, without waiting for it. */
const tracked = promise => {
  const state = {done: false};
  promise.then(() => { state.done = true; });
  return state;
};

test('a step on the edge leaves before its ack arrives', async () => {
  const {log, watcher, dispatch, ack} = harness();
  const plan = {steps: [{x: 100, y: 0, t: 16}, {x: 104, y: -1, t: 32}, {x: 300, y: 40, t: 600}]};
  const done = dispatch.sendTrajectoryAcked(watcher, 'mousemove', {x: 100, y: 50}, plan, inOrder,
                                            async (x, y) => log.push(['destination', x, y]));
  const move = tracked(done);
  await settle();
  // The step went out, then the exit, while the step's ack is still due.
  assert.deepEqual(log, [['mousemove', 100, 0], ['mousemove', 100, -3]]);
  // Nothing more is dispatched until that ack comes: a second move in flight
  // could replace it ([Compress] on RealMouseMoveEvent).
  assert.equal(move.done, false);
  ack();
  await done;
  assert.deepEqual(log.slice(2), [['destination', 300, 40]]);
});

test('the last move inside leaves before its ack arrives, after the step before it was acked', async () => {
  const {log, watcher, dispatch, ack} = harness();
  // Crosses the top a third of the way to the next step: one more move inside, then the exit.
  const plan = {steps: [{x: 100, y: 10, t: 16}, {x: 130, y: -20, t: 46}, {x: 300, y: 40, t: 600}]};
  const done = dispatch.sendTrajectoryAcked(watcher, 'mousemove', {x: 100, y: 50}, plan, inOrder,
                                            async (x, y) => log.push(['destination', x, y]));
  const move = tracked(done);
  await settle();
  // Two moves are never in flight at once: an unprocessed move is replaced by
  // the next one ([Compress] on RealMouseMoveEvent), and its ack never comes.
  assert.deepEqual(log, [['mousemove', 100, 10]]);
  ack();
  await settle();
  // A third of the way, at (110, 0), then the exit above it.
  assert.deepEqual(log, [['mousemove', 100, 10], ['mousemove', 110, 0], ['mousemove', 110, -3]]);
  assert.equal(move.done, false);
  ack();
  await done;
  assert.deepEqual(log.slice(3), [['destination', 300, 40]]);
});
