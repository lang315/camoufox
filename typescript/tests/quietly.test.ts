/**
 * quietly() gives a failing launch its own error. recordWarnings() returns the
 * error instead of throwing it, and the e2e test read only `result`, so a
 * launchOptions that threw surfaced as "Cannot read properties of undefined
 * (reading 'env')" and the cause never reached the log (#478).
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { restoreDeps, stubHost, utils } from "./launch-host.js";

const { quietly } = await import("./quietly.js");

beforeEach(() => stubHost());
afterEach(() => restoreDeps());

describe("quietly", () => {
	it("returns what the function returns", async () => {
		expect(await quietly(async () => 7)).toBe(7);
	});

	it("throws the error the function threw", async () => {
		const boom = new Error("boom");
		await expect(
			quietly(() => {
				throw boom;
			}),
		).rejects.toBe(boom);
	});

	it("surfaces launchOptions' own error", async () => {
		await expect(
			quietly(() => utils.launchOptions({ os: "beos" as any })),
		).rejects.toThrow(/beos/);
	});
});
