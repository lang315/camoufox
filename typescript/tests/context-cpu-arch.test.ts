/**
 * A context claims the CPU architecture its browser computes as (#458).
 * general.cpu_identity is a launch pref, so every context of a browser renders
 * canvas, audio, Opus, wasm and NaNs as the launch's CPU. Twin of
 * python/tests/test_context_cpu_arch.py.
 */
import { describe, expect, it } from "vitest";
import { utils } from "./launch-host.js";

const { NewContext } = await import("../src/sync_api.js");
const { generateContextFingerprint } = await import("../src/fingerprints.js");
const { gpuCpu } = await import("../src/coherence.js");
const { MODEL } = await import("./fpgen-setup.js");

const ARM = 3;
const INTEL = 1; // general.cpu_identity: utils.cpuIdentityPref
const APPLE_GPU: [string, string] = ["Apple", "Apple M1, or similar"];
const DRAWS = 20;

function launchedWith(cpuIdentity: number) {
	const calls: { script?: string } = {};
	const browser: any = {
		version: () => "159.0",
		newContext: async () => ({
			addInitScript: async (script: string) => {
				calls.script = script;
			},
		}),
	};
	utils.attachCpuIdentity(browser, {
		firefoxUserPrefs: { "general.cpu_identity": cpuIdentity },
	});
	return { browser, calls };
}

const archOf = (script: string | undefined, targetOs: string) =>
	gpuCpu(
		/setWebGLRenderer\("([^"]+)"\)/.exec(script ?? "")?.[1],
		targetOs,
	)[0] ?? "x86";

describe.skipIf(!MODEL.ok)("a context of a browser", () => {
	it.each([
		"windows",
		"linux",
	])("an arm browser refuses a %s context: no recorded arm machine runs it", async (os) => {
		const { browser } = launchedWith(ARM);
		await expect(NewContext(browser, { os })).rejects.toThrow(
			"computes as an arm CPU",
		);
	});

	it("an arm browser gives a macOS context an Apple GPU", async () => {
		for (let i = 0; i < DRAWS; i++) {
			const { browser, calls } = launchedWith(ARM);
			await NewContext(browser, { os: "macos" });
			expect(archOf(calls.script, "mac")).toBe("arm");
		}
	});

	it("an x86 browser never gives a macOS context an Apple GPU", async () => {
		// fpgen draws the screen before the GPU, and an Apple-silicon panel fits
		// no Intel Mac GPU (#463), so the draw either claims an Intel Mac or refuses.
		for (let i = 0; i < DRAWS; i++) {
			const { browser, calls } = launchedWith(INTEL);
			try {
				await NewContext(browser, { os: "macos" });
			} catch (e: any) {
				expect(e.message).toContain("computes as an x86 CPU");
				expect(e.message).toContain("no mac GPU fpgen recorded");
				continue;
			}
			expect(archOf(calls.script, "mac")).toBe("x86");
		}
	});

	it("a preset claiming another CPU throws", async () => {
		const { browser } = launchedWith(INTEL);
		const preset = {
			navigator: { platform: "MacIntel" },
			webgl: { unmaskedVendor: APPLE_GPU[0], unmaskedRenderer: APPLE_GPU[1] },
		};
		await expect(NewContext(browser, { preset })).rejects.toThrow(
			"computes as an x86 CPU",
		);
	});

	it("a webgl_config claiming another CPU throws", () => {
		expect(() =>
			generateContextFingerprint({
				os: "macos",
				webgl_config: APPLE_GPU,
				cpu_arch: "x86",
			}),
		).toThrow("computes as an x86 CPU");
	});

	it("a browser the launcher did not start is not constrained", async () => {
		const browser: any = {
			version: () => "159.0",
			newContext: async () => ({ addInitScript: async () => undefined }),
		};
		expect(utils.launchCpuArch(browser)).toBeNull();
		await NewContext(browser, { os: "windows" });
	});
});

describe("the launch's CPU architecture", () => {
	it.each([
		[{ "general.cpu_identity": 3 }, "arm"],
		[{ "general.cpu_identity": 1 }, "x86"],
		[{ "general.cpu_identity": 2 }, "x86"],
		[{ "general.cpu_identity": 0 }, null],
		[{}, null],
	])("is read from its cpu_identity pref %j", (prefs, arch) => {
		const browser: any = {};
		utils.attachCpuIdentity(browser, { firefoxUserPrefs: prefs });
		expect(utils.launchCpuArch(browser)).toBe(arch);
	});
});
