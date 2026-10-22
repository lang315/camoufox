/**
 * One way for every test to get a camoufox cache of its own (#267).
 *
 * INSTALL_DIR is computed once, at import, from the platform's cache
 * directory: XDG_CACHE_HOME on Linux, LOCALAPPDATA on Windows, and the home
 * directory on macOS. Redirecting a single variable therefore protects one OS
 * only, and a test that forgets the others reads and writes the developer's
 * real cache (removeIncompatibleData deletes the whole directory).
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, vi } from "vitest";

const VARS = ["HOME", "USERPROFILE", "LOCALAPPDATA", "XDG_CACHE_HOME"] as const;

/**
 * Point the cache lookup of all three platforms at `root`, re-import paths.ts
 * and return its INSTALL_DIR. Throws unless that directory sits under `root`,
 * so a wrong setup fails here instead of reaching the real cache.
 */
export async function isolateCacheAt(root: string): Promise<string> {
	process.env.HOME = root;
	process.env.USERPROFILE = root;
	process.env.LOCALAPPDATA = path.join(root, "AppData", "Local");
	process.env.XDG_CACHE_HOME = path.join(root, ".cache");
	vi.resetModules();
	const { INSTALL_DIR } = await import("../src/paths.js");
	const rel = path.relative(root, INSTALL_DIR);
	if (!rel || rel.startsWith("..") || path.isAbsolute(rel)) {
		throw new Error(
			`INSTALL_DIR is ${INSTALL_DIR}, outside the test's directory ${root}`,
		);
	}
	return INSTALL_DIR;
}

/**
 * Every test of the calling file gets an empty cache of its own, with the
 * modules reset so the next import computes INSTALL_DIR inside it. Returns the
 * directory that holds the cache, valid inside a test or hook.
 */
export function freshCachePerTest(prefix: string): () => string {
	let root = "";
	let saved: Record<string, string | undefined> = {};
	beforeEach(async () => {
		saved = Object.fromEntries(VARS.map((v) => [v, process.env[v]]));
		root = fs.mkdtempSync(path.join(os.tmpdir(), `camoufox-${prefix}-`));
		await isolateCacheAt(root);
	});
	afterEach(() => {
		for (const [v, value] of Object.entries(saved)) {
			if (value === undefined) delete process.env[v];
			else process.env[v] = value;
		}
		fs.rmSync(root, { recursive: true, force: true });
	});
	return () => root;
}
