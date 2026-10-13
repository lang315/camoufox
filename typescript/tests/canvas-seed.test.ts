/**
 * The fork's seeded canvas noise runs only where the RFP placeholder does not
 * cover the canvas: on another OS no `canvas:seed` and no `setCanvasSeed` may
 * reach the browser. Twin of
 * python/tests/test_canvas_seed_follows_rendering_plan.py.
 */
import * as fs from "node:fs";
import { afterAll, afterEach, beforeEach, describe, expect, it } from "vitest";
import {
	configOf,
	HOME,
	quietly,
	restoreDeps,
	SCRATCH,
	stubHost,
	utils,
} from "./launch-host.js";

const { NewBrowser, NewContext } = await import("../src/sync_api.js");
const { MODEL } = await import("./fpgen-setup.js");

const OS_NAMES = { win: "windows", mac: "macos", lin: "linux" } as const;
const HOST = OS_NAMES[utils.utilsDeps.hostOsKey()];
const OTHER = Object.values(OS_NAMES).find((name) => name !== HOST);
const SEED_CALL = /setCanvasSeed\((\d+)\)/g;

/** A Playwright BrowserType whose browsers keep their launch options and the
 * init scripts of their contexts. */
function fakePlaywright() {
	return {
		launch: async (options: Record<string, any>) => {
			const scripts: string[] = [];
			return {
				options,
				scripts,
				version: () => "156.0.1",
				newContext: async () => ({
					addInitScript: async (script: string) => {
						scripts.push(script);
					},
				}),
			};
		},
	} as any;
}

const launch = (os: string) =>
	quietly(() =>
		NewBrowser(fakePlaywright(), {
			os,
			headless: true,
			env: { HOME },
			i_know_what_im_doing: true,
		}),
	) as Promise<any>;

const contextSeeds = (browser: any) =>
	browser.scripts.map((script: string) =>
		[...script.matchAll(SEED_CALL)].map((m) => m[1]),
	);

beforeEach(() => stubHost());
afterEach(() => restoreDeps());
afterAll(() => fs.rmSync(SCRATCH, { recursive: true, force: true }));

describe.skipIf(!MODEL.ok)("the canvas seed follows the rendering plan", () => {
	it("an uncovered launch seeds the launch and every context", async () => {
		const browser = await launch(HOST);
		const seed = configOf(browser.options)["canvas:seed"];
		expect(seed).toBeGreaterThanOrEqual(1);
		expect(seed).toBeLessThanOrEqual(0xffffffff);
		await NewContext(browser);
		await NewContext(browser);
		const [[first], [second]] = contextSeeds(browser);
		expect(first).not.toBe(second);
	});

	it("a covered launch sends no launch seed", async () => {
		const browser = await launch(OTHER as string);
		expect("canvas:seed" in configOf(browser.options)).toBe(false);
	});

	it("a covered launch seeds no context", async () => {
		const browser = await launch(OTHER as string);
		await NewContext(browser);
		await NewContext(browser, { os: OTHER });
		expect(contextSeeds(browser)).toEqual([[], []]);
	});

	it("a browser launched without NewBrowser is seeded", async () => {
		// Playwright keeps no launch options, so a raw firefox.launch() or
		// connect() browser carries no covered record.
		const options = await quietly(() =>
			utils.launchOptions({
				os: OTHER,
				headless: true,
				env: { HOME },
				i_know_what_im_doing: true,
			}),
		);
		const browser = await fakePlaywright().launch(options);
		await NewContext(browser);
		const [[seed]] = contextSeeds(browser);
		expect(Number(seed)).toBeGreaterThanOrEqual(1);
	});

	it("another OS on an uncovered browser throws", async () => {
		await expect(NewContext(await launch(HOST), { os: OTHER })).rejects.toThrow(
			"canvas_noise: true",
		);
	});
});
