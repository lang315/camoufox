/**
 * An Intel Mac identity draws a screen and core count some Intel Mac has
 * (#463). fpgen drew the macOS screen without regard to the CPU, and on an
 * Apple-silicon panel no Intel Mac GPU fits, so launchOptions({ os: "macos",
 * cpu: { arch: "x86" } }) failed about half the time. Twin of
 * python/tests/test_intel_mac_draw.py.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
	configOf,
	fingerprints,
	HOME,
	quietly,
	restoreDeps,
	stubHost,
	utils,
} from "./launch-host.js";

const coherence = await import("../src/coherence.js");
const { MODEL } = await import("./fpgen-setup.js");

const DRAWS = 30;

const fitsAnIntelMac = (config: Record<string, any>) =>
	coherence.gpuFitsMachine(
		config["webGl:renderer"],
		"mac",
		config["navigator.hardwareConcurrency"],
		config["screen.width"],
		config["screen.height"],
	);

beforeEach(() => stubHost());
afterEach(() => restoreDeps());

async function intelMacLaunch(cpu: Record<string, string>, headless: boolean) {
	return configOf(
		await quietly(() =>
			utils.launchOptions({
				os: "macos",
				cpu,
				canvas_noise: true,
				headless,
				env: { HOME },
				i_know_what_im_doing: true,
			}),
		),
	);
}

describe.skipIf(!MODEL.ok)("an Intel Mac launch", () => {
	it.each([
		[{ arch: "x86" }],
		[{ manufacturer: "intel" }],
	])("always draws an Intel Mac for cpu %j", async (cpu) => {
		for (let i = 0; i < DRAWS; i++) {
			const config = await intelMacLaunch(cpu, true);
			expect([config["cpu:arch"], config["cpu:manufacturer"]]).toEqual([
				"x86",
				"intel",
			]);
			expect(fitsAnIntelMac(config)).toBe(true);
		}
	});

	it("draws an Intel Mac on an Apple-silicon display", async () => {
		// The display bound and the Intel Mac screen predicate are both
		// conditions on fpgen's screen node; fpgen ignored the predicate beside
		// the bound.
		utils.utilsDeps.hasDisplay = () => true;
		utils.utilsDeps.getScreenCons = () =>
			new fingerprints.Screen({ maxWidth: 1512, maxHeight: 982 });
		for (let i = 0; i < DRAWS; i++) {
			const config = await intelMacLaunch({ arch: "x86" }, false);
			expect(fitsAnIntelMac(config)).toBe(true);
		}
	});
});

it("the conditions admit only what some Intel Mac has", () => {
	const conditions = coherence.intelMacConditions();
	const screen = conditions.screen;
	const cores = conditions["navigator.hardwareConcurrency"];
	expect(screen({ width: 1512, height: 982 })).toBe(false); // MacBook Pro 14", Apple Silicon only
	expect(screen({ width: 1440, height: 900 })).toBe(true);
	expect(cores(11)).toBe(false);
	expect(cores(8) && cores(28)).toBe(true);
});
