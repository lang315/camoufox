/**
 * #164 / #190: NewContext's geometry must fit the launch window, which is
 * process-wide. Twin of python/tests/test_context_geometry.py.
 */
import { describe, expect, it } from "vitest";
import {
	generateContextFingerprint,
	getRandomPreset,
	type LaunchWindow,
} from "../src/fingerprints.js";
import { attachLaunchWindow } from "../src/utils.js";
import { MODEL } from "./fpgen-setup.js";

const { NewContext } = await import("../src/sync_api.js");

const LW: LaunchWindow = {
	outer: [1366, 728],
	inner: [1366, 643],
	screen: [1366, 768],
};
const NO_INNER: LaunchWindow = { ...LW, inner: [null, null] };

/** A browser whose newContext() keeps the options it was given. */
function fakeBrowser(launchWindow?: unknown) {
	const b: Record<string, any> = {
		version: () => "156.0",
		_camoufoxLaunchWindow: launchWindow,
		newContext: async (opts: Record<string, any>) => {
			b.opts = opts;
			return { addInitScript: async () => {} };
		},
	};
	return b;
}

describe.skipIf(!MODEL.ok)("NewContext fits the launch window", () => {
	it("the viewport is the launch inner and the screen holds the window", () => {
		for (let i = 0; i < 200; i++) {
			const fp = generateContextFingerprint({
				os: "windows",
				launch_window: LW,
			});
			expect(fp.context_options.viewport).toEqual({ width: 1366, height: 643 });
			const sw = fp.config["screen.width"];
			const sh = fp.config["screen.height"];
			expect(sw >= LW.outer[0] && sh >= LW.outer[1]).toBe(true);
			expect(fp.init_script).toContain(`w.setScreenDimensions(${sw}, ${sh})`);
		}
	});

	it.each([
		"windows",
		"macos",
		"linux",
	])("%s: no launch inner keeps the preset viewport inside the outer window and its scale factor", (os) => {
		const [ow, oh] = NO_INNER.outer;
		let clamped = 0;
		for (let i = 0; i < 200; i++) {
			const preset = getRandomPreset(os) as Record<string, any>;
			const opts = generateContextFingerprint({
				preset,
				launch_window: NO_INNER,
			}).context_options;
			const vp = opts.viewport;
			expect(vp.width <= ow && vp.height <= oh).toBe(true);
			expect(opts.deviceScaleFactor).toBe(
				preset.screen.devicePixelRatio ?? undefined,
			);
			if (
				vp.width !== preset.screen.width ||
				vp.height !== Math.max(preset.screen.height - 28, 600)
			)
				clamped++;
		}
		expect(clamped, "no draw exercised the clamp").toBeGreaterThan(0);
	});

	it("NewContext passes the launch window, and an explicit viewport wins", async () => {
		const b = fakeBrowser(NO_INNER);
		await NewContext(b as any, { os: "windows" });
		expect(b.opts.viewport.width).toBeLessThanOrEqual(NO_INNER.outer[0]);
		expect(b.opts.viewport.height).toBeLessThanOrEqual(NO_INNER.outer[1]);
		await NewContext(b as any, {
			os: "windows",
			viewport: { width: 800, height: 600 },
		});
		expect(b.opts.viewport).toEqual({ width: 800, height: 600 });
	});

	it("a malformed launch window behaves as none", () => {
		const shape = (lw: unknown) => {
			const o = generateContextFingerprint({
				os: "windows",
				launch_window: lw as LaunchWindow,
			}).context_options;
			return ["viewport", "deviceScaleFactor"].map((k) => o[k] !== undefined);
		};
		const base = shape(null);
		for (const bad of [
			{ outer: [1, 2] },
			{ outer: 1, inner: 2, screen: 3 },
			"x",
		])
			expect(shape(bad)).toEqual(base);
	});

	it("an explicit no-viewport drops the generated viewport and scale factor", async () => {
		const preset = (() => {
			for (;;) {
				const p = getRandomPreset("macos") as Record<string, any>;
				if (p.screen.devicePixelRatio === 2) return p;
			}
		})();
		const b = fakeBrowser(NO_INNER);
		await NewContext(b as any, { preset });
		expect(b.opts.deviceScaleFactor).toBe(2);
		for (const off of [{ noViewport: true }, { viewport: null }]) {
			await NewContext(b as any, { preset, ...off });
			expect(b.opts.viewport).toBeNull();
			expect("deviceScaleFactor" in b.opts).toBe(false);
			expect("noViewport" in b.opts).toBe(false);
		}
	});
});

describe("attachLaunchWindow", () => {
	it("reads the launch config and defaults the outer window", () => {
		const cfg = {
			"window.innerWidth": 1000,
			"window.innerHeight": 600,
			"screen.width": 1920,
			"screen.height": 1080,
		};
		const b: Record<string, any> = {};
		attachLaunchWindow(b, { env: { CAMOU_CONFIG_1: JSON.stringify(cfg) } });
		expect(b._camoufoxLaunchWindow).toEqual({
			outer: [1280, 1040],
			inner: [1000, 600],
			screen: [1920, 1080],
		});
	});
});
