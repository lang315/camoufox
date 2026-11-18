/**
 * An AMD iGPU is never paired with a core count only Intel CPUs report (#446).
 *
 * fpgen records Radeon HD 3200 machines at 2, 6, 8, 12 and 16 cores on Windows
 * and 2, 8, 12 and 16 on Linux, never at 10, 14, 18, 22 or 28. Every test pins
 * the cores it needs: none reads the machine running it. Twin of
 * python/tests/test_amd_igpu_cores.py, less its context-draw test, which
 * would have to replace fpgen's draw inside an ES module.
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
const cpuAffinity = await import("../src/cpu_affinity.js");
const { sampleWebglForScreen } = await import("../src/webgl.js");
const { MODEL } = await import("./fpgen-setup.js");

const AMD_IGPU: Record<string, string> = {
	win: "ANGLE (AMD, Radeon HD 3200 Graphics Direct3D11 vs_5_0 ps_5_0), or similar",
	lin: "Radeon HD 3200 Graphics, or similar",
};
const INTEL_ONLY = [10, 14, 18, 22, 28];
const SEEDS = Array.from({ length: 300 }, (_, i) => i);
const OS_KEY: Record<string, string> = { windows: "win", linux: "lin" };

beforeEach(() => stubHost());
afterEach(() => restoreDeps());

const vendorOf = (renderer: string, os: string) =>
	coherence.gpuCpuVendor(renderer, os);

const drawnVendors = (os: string, cores: number) =>
	SEEDS.map((seed) =>
		vendorOf(
			sampleWebglForScreen(os, 1920, 1080, seed, cores)["webGl:renderer"],
			os,
		),
	);

const launchConfig = async (extra: Record<string, any>) =>
	configOf(
		await quietly(() =>
			utils.launchOptions({
				headless: true,
				env: { HOME },
				i_know_what_im_doing: true,
				...extra,
			}),
		),
	);

const hostWith = (cpuCount: number) => {
	utils.utilsDeps.fixHardwareConcurrency = (config, canPin) =>
		fingerprints.fixHardwareConcurrency(config, canPin, { cpuCount });
};

describe.skipIf(!MODEL.ok)("the GPU draw", () => {
	it.each([
		"win",
		"lin",
	])("never pairs an AMD iGPU with an Intel-only count on %s", (os) => {
		for (const cores of INTEL_ONLY) {
			expect(drawnVendors(os, cores), `${os} ${cores}`).not.toContain("amd");
		}
	});

	it.each([
		"win",
		"lin",
	])("still offers an AMD iGPU at a count both vendors ship on %s", (os) => {
		const vendors = drawnVendors(os, 12);
		expect(vendors).toContain("amd");
		expect(vendors).toContain("intel");
	});
});

describe("the machine check", () => {
	it.each(["win", "lin"])("names the pair on %s", (os) => {
		expect(coherence.gpuFitsMachine(AMD_IGPU[os], os, 10)).toBe(false);
		expect(coherence.gpuFitsMachine(AMD_IGPU[os], os, 12)).toBe(true);
		expect(
			coherence.gpuFitsMachine("Intel(R) HD Graphics, or similar", os, 10),
		).toBe(true);
		expect(coherence.gpuFitsMachine("NVIDIA GeForce GTX 980", os, 10)).toBe(
			true,
		);
	});

	it.each([
		"win",
		"lin",
	])("validate reports the pair before a CPU is chosen on %s", (os) => {
		// The shipped-data cleaner validates a preset as converted, which has no cpu:* keys.
		const config = {
			"webGl:renderer": AMD_IGPU[os],
			"navigator.hardwareConcurrency": 14,
		};
		expect(coherence.validate(config, os).map((v) => v.rule)).toEqual([
			"cpu-matches-hardware",
		]);
	});
});

describe.skipIf(!MODEL.ok)("a launch on an Intel-only host", () => {
	it.each([
		"windows",
		"linux",
	])("redraws a %s preset's AMD iGPU", async (os) => {
		// The launch replaces the preset's cores with the host's; the presets
		// carry 2 to 16 cores, so only the host can make the pair.
		hostWith(10);
		const key = OS_KEY[os];
		const amd = (fingerprints.loadPresets("150")?.presets[os] ?? []).filter(
			(p: any) => vendorOf(p.webgl.unmaskedRenderer, key) === "amd",
		);
		expect(amd.length).toBeGreaterThan(0);
		for (const preset of amd) {
			const config = await launchConfig({ os, fingerprint_preset: preset });
			expect(config["navigator.hardwareConcurrency"]).toBe(10);
			expect(vendorOf(config["webGl:renderer"], key)).not.toBe("amd");
			expect(coherence.validate(config, key)).toEqual([]);
		}
	});

	it.each(["windows", "linux"])("draws a coherent %s identity", async (os) => {
		hostWith(14);
		for (let i = 0; i < 40; i++) {
			const config = await launchConfig({ os, canvas_noise: true });
			expect(config["navigator.hardwareConcurrency"]).toBe(14);
			expect(coherence.validate(config, OS_KEY[os])).toEqual([]);
		}
	});
});

describe.skipIf(!MODEL.ok)("a refused AMD cpu on a 10-core host", () => {
	const refusal = async (extra: Record<string, any> = {}) => {
		hostWith(10);
		return String(
			await launchConfig({
				os: "linux",
				canvas_noise: true,
				cpu: { manufacturer: "amd" },
				...extra,
			}).then(
				() => "",
				(error: Error) => error.message,
			),
		);
	};

	it("names the count as the host's and what to change", async () => {
		const message = await refusal();

		expect(message).toContain("hardwareConcurrency 10");
		expect(message).toContain("this host's logical core count");
		expect(message).toContain(
			cpuAffinity.supported() ? "pin_cpu_cores=True" : "cannot pin the browser",
		);
	});

	it("says so when the caller set the count", async () => {
		const message = await refusal({
			config: { "navigator.hardwareConcurrency": 10 },
		});

		expect(message).toContain("You set that count");
		expect(message).not.toContain("host's");
	});
});

describe("coreCountNote", () => {
	it("tells a host that cannot pin from one with pinning off", () => {
		const cannot = fingerprints.coreCountNote(false, false, false);
		const off = fingerprints.coreCountNote(false, false, true);

		expect(cannot).toContain("cannot pin");
		expect(cannot).not.toContain("pin_cpu_cores");
		expect(off).toContain("pin_cpu_cores=True");
	});

	it("says a pinned launch kept its drawn count", () => {
		expect(fingerprints.coreCountNote(false, true, true)).toContain(
			"kept the count this identity drew",
		);
	});
});
