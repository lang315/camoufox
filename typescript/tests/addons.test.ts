/**
 * Mirrors python/tests/test_addons.py: regression guard for #308, where a
 * failed first download left an empty addon directory that was trusted
 * forever afterwards.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { beforeEach, expect, it, vi } from "vitest";
import { freshCachePerTest } from "./cache-home.js";

type Addons = typeof import("../src/addons.js");

const cacheRoot = freshCachePerTest("addons");
let tmp: string;
let addons: Addons;
let ubo: string;

beforeEach(async () => {
	tmp = cacheRoot();
	addons = await import("../src/addons.js");
	ubo = addons.getAddonPath("UBO");
	expect(ubo.startsWith(tmp)).toBe(true);
});

function writeManifest(extractPath: string) {
	fs.mkdirSync(extractPath, { recursive: true });
	fs.writeFileSync(path.join(extractPath, "manifest.json"), "{}");
}

it("re-downloads a partial (manifest-less) directory", async () => {
	fs.mkdirSync(ubo, { recursive: true });
	const calls: string[] = [];
	addons.addonsDeps.downloadAndExtract = async (_url, extractPath, name) => {
		calls.push(name);
		writeManifest(extractPath);
	};

	const out: string[] = [];
	await addons.maybeDownloadAddons({ ...addons.DefaultAddons }, out);

	expect(calls).toEqual(["UBO"]);
	expect(fs.existsSync(path.join(ubo, "manifest.json"))).toBe(true);
	expect(out).toEqual([ubo]);
});

it("does not re-download an extracted addon", async () => {
	writeManifest(ubo);
	addons.addonsDeps.downloadAndExtract = async () => {
		throw new Error("must not re-download an already-extracted addon");
	};

	const out: string[] = [];
	await addons.maybeDownloadAddons({ ...addons.DefaultAddons }, out);
	expect(out).toEqual([ubo]);
});

it("removes the partial directory when a download fails", async () => {
	addons.addonsDeps.downloadAndExtract = async (_url, extractPath) => {
		fs.mkdirSync(extractPath, { recursive: true }); // partial write, then die
		throw new Error("network died mid-download");
	};
	const log = vi.spyOn(console, "log").mockImplementation(() => {});

	const out: string[] = [];
	await addons.maybeDownloadAddons({ ...addons.DefaultAddons }, out);

	expect(fs.existsSync(ubo)).toBe(false);
	expect(out).toEqual([]);
	expect(log).toHaveBeenCalledWith(
		"Failed to download and extract UBO: Error: network died mid-download",
	);
	log.mockRestore();
});
