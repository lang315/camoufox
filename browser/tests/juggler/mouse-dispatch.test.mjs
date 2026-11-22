// MouseDispatch's snap: points land on whole device pixels inside the browser,
// whatever the chrome's scale (#451).
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {load} from './gecko.mjs';

const {MouseDispatch} = await load('input/MouseDispatch.js');

/** The snapped bounds of a browser rect, in a chrome of `auPerDevPx` app units. */
function bounds(auPerDevPx, box) {
  const win = {windowUtils: {toTopLevelWidgetRect: () => ({width: 60 / auPerDevPx})}};
  const {_originX, _limitX, _originY, _limitY} = new MouseDispatch(win, box);
  // The device pixel jugglerSendMouseEvent sends a CSS point to (ToWidgetPoint).
  const device = css => Math.round(Math.round(css * 60) / auPerDevPx);
  return {origin: [_originX, _originY], limit: [_limitX, _limitY],
          device: [device(_originY), device(_limitY)]};
}

test('at 57 app units the first and last rows are the device rows inside the edges', () => {
  // Measured on a macOS host at text 105%: top 84.95 is device 89.42, bottom 815.1 is 858.0.
  const {device} = bounds(57, {left: 0, top: 84.95, width: 1440, height: 815.1 - 84.95});
  assert.deepEqual(device, [90, 857]);
});

test('at 60 app units the snap is whole CSS pixels inside the edges', () => {
  for (const [lo, hi] of [[84.95, 815.1], [85, 816], [51.4, 900.6], [56.5, 1384]]) {
    const {origin, limit} = bounds(60, {left: lo, top: lo, width: hi - lo, height: hi - lo});
    assert.deepEqual(origin, [Math.ceil(lo), Math.ceil(lo)]);
    assert.deepEqual(limit, [Math.ceil(hi) - 1, Math.ceil(hi) - 1]);
  }
});
