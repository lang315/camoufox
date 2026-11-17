/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

// The worst caller (PageHandler.js hoverDwell) accepts 83% of its draws, so a hundred misses in a row
// is about 1e-78. A source that never lands inside its bounds is a bug: fail, do not loop on.
const MAX_ATTEMPTS = 100;

function standardNormal(random) {
  // Box-Muller; 1 - random() keeps the logarithm's argument above 0.
  return Math.sqrt(-2 * Math.log(1 - random())) * Math.cos(2 * Math.PI * random());
}

// A draw outside [min, max] is drawn again, so the distribution is truncated at the bounds: a clamp
// would put every draw beyond a bound on the bound itself, a spike of up to 17% of the draws.
function withinBounds(draw, min, max) {
  for (let i = 0; i < MAX_ATTEMPTS; i++) {
    const x = draw();
    if (x >= min && x <= max)
      return x;
  }
  throw new Error(`no draw within [${min}, ${max}] in ${MAX_ATTEMPTS} attempts`);
}

/**
 * A person's delay in ms: a normal draw around `mean` with standard deviation
 * `sd`, truncated to [`min`, `max`]. Every delay Juggler waits out
 * between a person's input events (a click's hold, a key's hold, a modifier's
 * lead) is drawn here, each with the figures its caller cites. The cited mean
 * and spread are the untruncated normal's: truncating moves the mean up when
 * the minimum cuts the lower tail.
 *
 * `random` returns floats in [0, 1); the unit tests pass a seeded stream.
 */
export function normalDelay(mean, sd, min = 0, max = Infinity, random = Math.random) {
  return withinBounds(() => mean + sd * standardNormal(random), min, max);
}

/**
 * A person's dwell or hold time in ms, right-skewed as human timing is: a
 * log-normal draw whose median is `medianMs`, with `sigma` the standard
 * deviation of the logarithm, truncated to [`min`, `max`]. `random` is as for
 * normalDelay.
 */
export function logNormalDelay(medianMs, sigma, min = 0, max = Infinity, random = Math.random) {
  return withinBounds(() => medianMs * Math.exp(sigma * standardNormal(random)), min, max);
}
