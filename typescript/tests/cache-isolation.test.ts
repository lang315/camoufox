/**
 * The TypeScript tests never touch the developer's real camoufox cache (#267).
 *
 * INSTALL_DIR is computed once from the platform's cache directory, and only
 * Linux reads XDG_CACHE_HOME. A test that redirects that variable alone lands
 * in the real ~/Library/Caches/camoufox on macOS, where removeIncompatibleData
 * deletes the whole directory. These tests only compute and create paths under
 * their own directory.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, expect, it, vi } from "vitest";
import { freshCachePerTest, isolateCacheAt } from "./cache-home.js";

const cacheRoot = freshCachePerTest("iso");

afterEach(() => {
	vi.doUnmock("../src/paths.js");
});

it("INSTALL_DIR sits under the test's own directory on every OS", async () => {
	const { INSTALL_DIR } = await import("../src/paths.js");
	expect(
		INSTALL_DIR.startsWith(cacheRoot()),
		`INSTALL_DIR is ${INSTALL_DIR}`,
	).toBe(true);
});

it("leaves a file in the cache for the next test to look for", async () => {
	const { INSTALL_DIR } = await import("../src/paths.js");
	fs.mkdirSync(INSTALL_DIR, { recursive: true });
	fs.writeFileSync(path.join(INSTALL_DIR, "leftover"), "");
});

it("starts every test with an empty cache", async () => {
	const { INSTALL_DIR } = await import("../src/paths.js");
	expect(fs.existsSync(path.join(INSTALL_DIR, "leftover"))).toBe(false);
});

it("refuses a setup whose INSTALL_DIR is outside the test's directory", async () => {
	vi.doMock("../src/paths.js", () => ({ INSTALL_DIR: "/somewhere/else" }));
	await expect(isolateCacheAt(cacheRoot())).rejects.toThrow(
		/INSTALL_DIR is \/somewhere\/else, outside/,
	);
});
