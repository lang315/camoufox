/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

// The worst caller (content/PageAgent.js keyInterval) accepts 92% of its draws, so a hundred misses in
// a row is about 1e-111. A source that never lands inside its bounds is a bug: fail, do not loop on.
const MAX_ATTEMPTS = 100;

/**
 * A person's delay in ms: a normal draw around `mean` with standard deviation
 * `sd`, truncated to [`min`, `max`]. Every delay Juggler waits out
 * inside one command (a key's hold, a paste or auto-Shift modifier's lead and
 * trail, a refused paste's typing rate) is drawn here, each with the
 * figures its caller cites. The cited mean and spread are the untruncated
 * normal's: truncating moves the mean up when the minimum cuts the lower tail.
 *
 * A draw outside the bounds is drawn again: a clamp would put every draw
 * beyond a bound on the bound itself, 7.8% of keyInterval's draws (#467).
 *
 * `random` returns floats in [0, 1); the unit tests pass a seeded stream.
 */
export function normalDelay(mean, sd, min = 0, max = Infinity, random = Math.random) {
  for (let i = 0; i < MAX_ATTEMPTS; i++) {
    // Box-Muller; 1 - random() keeps the logarithm's argument above 0.
    const x = mean + sd * Math.sqrt(-2 * Math.log(1 - random())) * Math.cos(2 * Math.PI * random());
    if (x >= min && x <= max)
      return x;
  }
  throw new Error(`no draw within [${min}, ${max}] in ${MAX_ATTEMPTS} attempts`);
}
