// MouseDispatch.sendAcked waits for a renderer ack only for an event the
// parent dispatched to the browser: one it gave a popup gets none, whatever
// the popup's widget rect reads (#480).
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {load} from './gecko.mjs';

const {MouseDispatch} = await load('input/MouseDispatch.js');

const box = {left: 0, top: 85, width: 800, height: 600};

/**
 * A chrome window whose parent dispatches each event to `route(type)`: the
 * browser, a node of a popup, or nothing (null). The date picker is open with
 * the rect measured in 13 of 99 headless launches: its widget not yet placed.
 */
function harness(route) {
  const listeners = [];
  const browser = {getBoundingClientRect: () => box, closest: () => null};
  const panel = {state: 'open', getOuterScreenRect: () => ({left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0})};
  let id = 0;
  const win = {
    innerWidth: 1000,
    innerHeight: 800,
    MouseEvent: {MOZ_SOURCE_MOUSE: 1},
    document: {querySelectorAll: () => [panel]},
    getComputedStyle: () => ({pointerEvents: 'auto'}),
    addEventListener: (type, listener, options) => listeners.push({type, listener, options}),
    windowUtils: {
      DEFAULT_MOUSE_POINTER_ID: 0,
      toTopLevelWidgetRect: () => ({width: 1}),
      toScreenRectInCSSUnits: (x, y) => ({x, y}),
      flushLayoutWithoutThrottledAnimations: () => {},
      jugglerSendMouseEvent: type => {
        const target = route(type, browser);
        if (target instanceof Error)
          throw target;
        if (target) {
          for (const l of listeners.filter(l => l.type === type))
            l.listener({type, originalTarget: target});
        }
        return ++id;
      },
    },
  };
  const asked = [];
  const watcher = {
    ensureEventWithin: async (type, deadlineMs, predicate) => {
      asked.push(type);
      return type === 'mousequeued' || type === 'mousedown' ? {type, jugglerEventId: id} : null;
    },
  };
  return {win, browser, listeners, asked, watcher, dispatch: () => MouseDispatch.forBrowser(win, browser, {})};
}

const th = {localName: 'th'};

test('a move the parent gave the open picker returns at once, though its widget rect is still empty', async () => {
  const {watcher, asked, dispatch} = harness(() => th);
  const result = await dispatch().sendAcked(watcher, 'mousemove', 150, 90, 50);
  assert.deepEqual(result, {jugglerEventId: 1, takenBy: th});
  assert.deepEqual(asked, [], 'no renderer ack was waited for');
});

test('a move the parent gave the browser waits for the renderer to queue it', async () => {
  const {watcher, asked, dispatch} = harness((type, browser) => browser);
  const result = await dispatch().sendAcked(watcher, 'mousemove', 150, 90, 50);
  assert.deepEqual(result, {type: 'mousequeued', jugglerEventId: 1});
  assert.deepEqual(asked, ['mousequeued']);
});

test('an event the parent did not dispatch during the send is waited for under the deadline, not covered', async () => {
  // A press the parent delays while the chrome document suppresses event handling.
  const {watcher, asked, dispatch} = harness(() => null);
  const result = await dispatch().sendAcked(watcher, 'mousedown', 150, 90, 50);
  assert.deepEqual(result, {type: 'mousedown', jugglerEventId: 1});
  assert.deepEqual(asked, ['mousedown']);
});

test('a dispatch that throws leaves no target behind for the next one', async () => {
  let fail = true;
  const {watcher, asked, dispatch} = harness((type, browser) => {
    if (fail) {
      fail = false;
      return new Error('boom');
    }
    return browser;
  });
  await assert.rejects(dispatch().sendAcked(watcher, 'mousedown', 150, 90, 50), /boom/);
  const result = await dispatch().sendAcked(watcher, 'mousedown', 150, 90, 50);
  assert.deepEqual(result, {type: 'mousedown', jugglerEventId: 1});
  assert.deepEqual(asked, ['mousedown']);
});

test('a target read during one dispatch is not carried into the next', async () => {
  let target = th;
  const {watcher, asked, listeners, dispatch} = harness(() => target);
  await dispatch().sendAcked(watcher, 'mousemove', 150, 90, 50);
  // An event the parent dispatches outside a send (a real move) is not a send's.
  for (const l of listeners.filter(l => l.type === 'mousemove'))
    l.listener({type: 'mousemove', originalTarget: th});
  target = null;
  const result = await dispatch().sendAcked(watcher, 'mousemove', 151, 90, 50);
  assert.deepEqual(result, {type: 'mousequeued', jugglerEventId: 2}, 'not taken by the picker');
  assert.deepEqual(asked, ['mousequeued']);
});

test('one recorder per chrome window, however many dispatches use it', async () => {
  const {win, watcher, listeners, dispatch} = harness((type, browser) => browser);
  await dispatch().sendAcked(watcher, 'mousedown', 150, 90, 50);
  await dispatch().sendAcked(watcher, 'mousemove', 160, 90, 50);
  const types = listeners.map(l => l.type);
  assert.equal(new Set(types).size, types.length, 'each type is listened for once');
  assert.equal(new Set(listeners.map(l => l.listener)).size, 1, 'by one listener');
  assert.ok(listeners.every(l => l.options.capture && l.options.mozSystemGroup));
  assert.ok(win);
});
