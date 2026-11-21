/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/**
 * The one place in the parent process that dispatches synthesized mouse input.
 *
 * It exists because the alternative did not work. Between 2026-04 and 2026-09,
 * four separate deadlocks shipped -- exact-edge coordinates (#225), the
 * since-removed in-browser trajectory's points that bypassed the endpoint's guard (#677/#225), a
 * zero-displacement move, and the top-edge row (#751/#752) -- each fixed by
 * adding one more coordinate guard at one more call site. The guards were
 * correct; the arithmetic behind them was copied per call site, so every new
 * dispatch site was a fresh chance to get it wrong, and every mistake cost the
 * whole browser process.
 *
 * THE INVARIANT
 *   A synthesized input event whose ack we await must reach the content
 *   renderer -- and when it does not, we must stop waiting.
 *
 * Nothing else in juggler may call jugglerSendMouseEvent / sendWheelEvent or do
 * browser-relative coordinate arithmetic; scripts/check-input-dispatch.py fails
 * the build if it does. See docs/input-dispatch.md.
 */

/**
 * How long to wait for a juggler-mouse-event-hit-renderer ack before giving up.
 *
 * Measured on v152.0.4-beta.30, headless Linux, over 1000+ dispatches:
 *
 *   content main thread        p50     p99     max
 *   idle                       0ms     1ms     12ms
 *   busy (8ms burned/event)    8ms     9ms     12ms
 *   blocked (3s sync script)   0ms     1ms     2849ms
 *
 * Typical latency is three orders of magnitude below this. The deadline is not
 * sized by the typical case though: the ack is delivered FROM the content main
 * thread, so it inherits any block on it, and block length is page-controlled
 * and unbounded. Pages that block for seconds are the normal case on the
 * targets Camoufox exists to handle. Sizing this near the p99 would silently
 * drop real input on merely-slow pages -- a correctness bug wearing the exact
 * costume of the deadlock it replaces. Waiting too long costs a few seconds
 * once and then recovers; waiting too little costs input loss that nobody can
 * diagnose. So: well above the slowest legitimate ack, not near the typical one.
 */
export const kAckDeadlineMs = 5000;

// The events sendAcked dispatches, and per chrome window the one recorder of
// the node the parent dispatched the current one to (_sendRouted).
const kAckedTypes = ['mousemove', 'mousedown', 'mouseup', 'contextmenu'];
const routes = new WeakMap();

function warnUndelivered(eventType, x, y, box, deadlineMs) {
  dump(
    `[juggler] WARN ${eventType} at (${x}, ${y}) was not delivered to the ` +
    `renderer after ${deadlineMs}ms; dropping it (browser rect ` +
    `${box.width}x${box.height} at +${box.left}+${box.top})\n`
  );
}

export class MouseDispatch {
  /**
   * @param {Window} win chrome window owning the browser element.
   * @param {DOMRect} boundingBox the browser element's rect, already measured.
   * @param {object} eventArgs button / clickCount / modifiers / buttons.
   * @param {Element} [browser] the browser element, when the rect is to be
   *     measured again before each dispatch (forBrowser).
   */
  constructor(win, boundingBox, {button = 0, clickCount = 0, modifiers = 0, buttons = 0} = {}, browser = null) {
    this._win = win;
    this._args = {button, clickCount, modifiers, buttons};
    this._browser = browser;
    this._measured(boundingBox);
  }

  _measured(boundingBox) {
    this._box = boundingBox;
    // The chrome's app units per device pixel: 60 at a whole scale, 57 with
    // text at 105% (ui.textScaleFactor; LookAndFeel::SystemZoomSettings).
    this._auPerDevPx = Math.round(60 / this._win.windowUtils.toTopLevelWidgetRect(0, 0, 1, 1).width);

    // Snap onto whole device pixels fully inside the browser element. Its
    // origin and size can be fractional, and a point on the device row that
    // holds either boundary belongs to chrome rather than content, so no
    // renderer ack arrives (#751, #752, #451).
    [this._originX, this._limitX] = this._devicePixelsIn(boundingBox.left, boundingBox.left + boundingBox.width);
    [this._originY, this._limitY] = this._devicePixelsIn(boundingBox.top, boundingBox.top + boundingBox.height);
  }

  /**
   * The chrome CSS coordinates of the first and last whole device pixels in
   * [lo, hi) along one axis. jugglerSendMouseEvent rounds a point to app units
   * and then to a device pixel (nsContentUtils::ToWidgetPoint), and the widget
   * hit-tests that pixel, so whole CSS pixels are only safe at a whole scale:
   * at 57 app units, CSS 85 is device 89.47, row 89, above a top at 89.42.
   */
  _devicePixelsIn(lo, hi) {
    const au = this._auPerDevPx;
    const first = Math.ceil(Math.round(lo * 60) / au);
    const last = Math.ceil(Math.round(hi * 60) / au) - 1;
    return [first * au / 60, last * au / 60];
  }

  static forBrowser(win, linkedBrowser, eventArgs) {
    return new MouseDispatch(win, linkedBrowser.getBoundingClientRect(), eventArgs, linkedBrowser);
  }

  /**
   * Measure the browser rect again. Every dispatch does this synchronously
   * before converting its point (docs/input-dispatch.md, "A fresh rect"): one
   * MouseDispatch can serve a command for longer than a frame (a click's
   * press and release), and the browser can move in the window meanwhile.
   *
   * Measured 2026-10-31 (~1 in 4 runs): a window smaller
   * than the chrome plus the viewport, as a 1366x768 screen draw gives a
   * 1000x700 viewport, leaves Juggler's .browserStack scrolling the browser,
   * and while it was overflow: auto a wheel turn scrolled it by the overflow
   * over ~130ms (TargetRegistry.updateViewportSize). A move that started
   * meanwhile kept the rect from its start, so every later point, the
   * destination included, reached the page shifted by the scroll (13-84 px):
   * moves nothing asked for, a move that missed its target, and the
   * next click's mousedown away from the last mousemove, which a real mouse
   * never does. The chrome can still move the browser mid-move (a toolbar
   * changing height, the fullscreen toolbox sliding away).
   */
  _remeasure() {
    if (this._browser)
      this._measured(this._browser.getBoundingClientRect());
  }

  get boundingBox() {
    return this._box;
  }

  /**
   * Is this relative point inside the content viewport at all?
   *
   * The far edges are exclusive: a point at exactly x == width or y == height
   * lies on the opposite boundary row and fires as an exit event, so it must be
   * treated as out-of-viewport rather than dispatched (#225). The near edges are
   * inclusive -- 0 is a legitimate coordinate a caller may ask for, and the
   * constructor's snap is what makes it safe to dispatch.
   */
  isInViewport(x, y) {
    return x >= 0 && y >= 0 && x < this._box.width && y < this._box.height;
  }

  /**
   * The device pixels inside the CSS pixel holding relative (x, y), as
   * relative points: one at a display scale of 1, two or three at 2.5.
   */
  devicePointsIn(x, y) {
    const scale = this._win.devicePixelRatio;
    const axis = (v, origin) => {
      // The content area starts on the device pixel nearest its CSS origin.
      const start = Math.round(origin * scale);
      const points = [];
      for (let k = Math.ceil(Math.floor(v) * scale); k < (Math.floor(v) + 1) * scale; k++)
        points.push((start + k) / scale - origin);
      return points;
    };
    const xs = axis(x, this._box.left);
    return axis(y, this._box.top).flatMap(py => xs.map(px => ({x: px, y: py})));
  }

  /** Relative point -> absolute, snapped clear of both of the element's edges. */
  toAbsolute(x, y) {
    return {
      x: Math.min(Math.max(x + this._box.left, this._originX), this._limitX),
      y: Math.min(Math.max(y + this._box.top, this._originY), this._limitY),
    };
  }

  _sendAbsolute(eventType, absX, absY) {
    return this._win.windowUtils.jugglerSendMouseEvent(
      eventType,
      absX,
      absY,
      this._args.button,
      this._args.clickCount,
      this._args.modifiers,
      false /* aIgnoreRootScrollFrame */,
      0.0 /* pressure */,
      // MOZ_SOURCE_MOUSE: a real mouse reports PointerEvent.pointerType "mouse";
      // MOZ_SOURCE_UNKNOWN (0) surfaces as an empty pointerType, which no OS
      // input path ever produces (daijro/camoufox#776, microsoft/playwright#38376).
      this._win.MouseEvent.MOZ_SOURCE_MOUSE /* inputSource */,
      true /* isDOMEventSynthesized */,
      false /* isWidgetEventSynthesized */,
      this._args.buttons,
      this._win.windowUtils.DEFAULT_MOUSE_POINTER_ID /* pointerIdentifier */,
      false /* disablePointerEvent */
    );
  }

  /**
   * Dispatch one event and return its id and the node the parent dispatched
   * it to, read while it is dispatched: jugglerSendMouseEvent runs the
   * parent's DOM dispatch synchronously, and the parent forwards the event to
   * the renderer from there (EventStateManager::PostHandleEvent) only when
   * that node is a remote browser. Null when the parent dispatched no event.
   */
  _sendRouted(eventType, absX, absY) {
    let route = routes.get(this._win);
    if (!route) {
      route = {sending: false, target: null};
      const record = event => {
        if (route.sending)
          route.target ??= event.originalTarget;
      };
      for (const type of kAckedTypes)
        this._win.addEventListener(type, record, {capture: true, mozSystemGroup: true});
      routes.set(this._win, route);
    }
    route.sending = true;
    try {
      const jugglerEventId = this._sendAbsolute(eventType, absX, absY);
      return {jugglerEventId, target: route.target};
    } finally {
      route.sending = false;
      route.target = null;
    }
  }

  /**
   * Dispatch one event and wait for the renderer to ack it, under a deadline.
   *
   * Returns the ack event object, or null if none arrived in time -- in which
   * case the event is dropped and a warning is logged -- or {takenBy} at once
   * when the parent dispatched the event to something other than the browser.
   * That is an open popup over the point (the date picker, a permission
   * doorhanger), which the parent hands the event to as an OS click there
   * lands on it (PresShell::EventHandler::ComputeRootFrameToHandleEventWithPopup).
   * The renderer never sees such an event, so there is no ack to wait for;
   * waiting cost 5s per event, and a click under the picker took 15s and timed
   * out Playwright (2026-11-03, tests/playwright/patches/popup-covered-click.py).
   *
   * The node is read from the dispatch, not predicted from the popups' rects:
   * the parent hit-tests a popup's layout rect, and getOuterScreenRect reads
   * its widget's, which a just-opened date picker had not placed yet in 13 of
   * 99 headless launches (#480).
   *
   * An event the parent dispatched to nothing during the send is waited for
   * as one sent to the browser: while the chrome document suppresses event
   * handling, the parent drops a move and delays a press or a release until
   * handling resumes (PresShell::EventHandler::MaybeDiscardOrDelayMouseEvent),
   * and a delayed one can still reach the renderer. Never waits forever: input dispatch is
   * serialized on activateAndRun()'s process-global chain, so an unbounded
   * wait here wedges every later input event in the process, in every tab,
   * for the life of the browser.
   */
  async sendAcked(watcher, eventType, x, y, deadlineMs = kAckDeadlineMs) {
    this._remeasure();
    const {x: absX, y: absY} = this.toAbsolute(x, y);
    const {jugglerEventId, target} = this._sendRouted(eventType, absX, absY);
    if (target && target !== this._browser)
      return {jugglerEventId, takenBy: target};
    // A move reaches the page at the next refresh tick; the renderer acks it
    // on arrival as "mousequeued" (BrowserChild::RecvRealMouseMoveEvent).
    const arrival = eventType === 'mousemove' ? 'mousequeued' : eventType;
    const ack = await watcher.ensureEventWithin(
      arrival, deadlineMs, eventObject => eventObject.jugglerEventId === jugglerEventId);
    if (!ack)
      warnUndelivered(eventType, x, y, this._box, deadlineMs);
    return ack;
  }

  /**
   * Dispatch a move and wait until the renderer has queued it. The page gets
   * it at the next refresh tick, coalesced with the moves queued since the
   * last one; the returned handle's delivered() waits for that, under the
   * same deadline (deliveryWatcher must listen for 'mousemove' from before
   * the dispatch). Returns null when the move was not queued in time.
   */
  async sendQueuedMove(watcher, deliveryWatcher, x, y) {
    const queued = await this.sendAcked(watcher, 'mousemove', x, y);
    // A move a popup took never reaches the page either.
    if (!queued || queued.takenBy) {
      deliveryWatcher.dispose();
      return null;
    }
    return {
      // A newer move disposes this watcher: that move is then the one to wait for.
      delivered: async () => {
        const ack = await deliveryWatcher.ensureEventWithin(
          'mousemove', kAckDeadlineMs, eventObject => eventObject.jugglerEventId === queued.jugglerEventId)
          .catch(() => true);
        if (!ack)
          dump(`[juggler] WARN a queued mousemove at (${x}, ${y}) had not reached the page after ${kAckDeadlineMs}ms; going on\n`);
        return ack;
      },
      dispose: () => deliveryWatcher.dispose(),
    };
  }

  /**
   * Park the cursor off web content so hover effects clear.
   *
   * Deliberately dispatched at the chrome window's own origin rather than a
   * content coordinate, and deliberately unacked: it never enters the renderer,
   * so there is no ack to wait for.
   */
  parkOffContent() {
    this._sendAbsolute('mousemove', 0, 0);
  }

  /**
   * The pointer leaves the window, or comes back to it at a relative point, as
   * when a GTK drag session takes the pointer and gives it back. A widget exit
   * and enter, sent to the chrome window so the parent's hover state leaves as
   * well as the page's. Unacked: neither is a mouse event the renderer acks.
   */
  leaveWindow(x, y) {
    const {x: absX, y: absY} = this.toAbsolute(x, y);
    this._sendAbsolute('mousecancel', absX, absY);
  }

  enterWindow(x, y) {
    const {x: absX, y: absY} = this.toAbsolute(x, y);
    this._sendAbsolute('mouseover', absX, absY);
  }

  /** Wheel events take the same conversion; they are not acked. */
  sendWheel(x, y, {deltaX, deltaY, deltaZ, deltaMode, lineOrPageDeltaX, lineOrPageDeltaY, nativeNotches = false}) {
    const {x: absX, y: absY} = this.toAbsolute(x, y);
    const utils = this._win.windowUtils;
    // The widget reads pixel deltas as device pixels. Scale by the chrome
    // window's real ratio, not this._win.devicePixelRatio (MaskConfig spoofs it).
    const scale = deltaMode === 0 /* WheelEvent.DOM_DELTA_PIXEL */
        ? utils.toTopLevelWidgetRect(0, 0, 1, 1).width
        : 1;
    utils.sendWheelEvent(
      absX,
      absY,
      deltaX * scale,
      deltaY * scale,
      deltaZ * scale,
      deltaMode,
      this._args.modifiers,
      lineOrPageDeltaX,
      lineOrPageDeltaY,
      nativeNotches ? utils.WHEEL_EVENT_NATIVE_NOTCHES : 0);
  }
}
