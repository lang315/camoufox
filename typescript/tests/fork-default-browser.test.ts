/**
 * Mirrors python/tests/test_fork_default_browser.py: the launchers install this
 * fork's browser, and only this fork's, by default (#266).
 *
 * INSTALL_DIR is computed at import, so every test gets a fresh cache
 * directory (cache-home.ts) and re-imports the modules: nothing here may touch
 * the real cache.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { freshCachePerTest } from "./cache-home.js";

const FORK = "lang315/camoufox";
const UPSTREAM = "daijro/camoufox";
const FORK_2 = "2".repeat(64);
const FORK_1 = "1".repeat(64);

function asset(name: string, sha: string) {
	return {
		name,
		browser_download_url: `https://example.invalid/${sha.slice(0, 8)}/${name}`,
		digest: `sha256:${sha}`,
		created_at: "2026-10-22T09:03:52Z",
	};
}

function forkRelease(tag: string, sha: string) {
	return {
		tag_name: tag,
		prerelease: false,
		assets: [
			asset("camoufox-158.0-beta.33-win.x86_64.zip", sha),
			asset("camoufox-158.0-beta.33-mac.arm64.zip", sha),
		],
	} as any;
}

// Newest first, as the GitHub API lists them.
const FORK_RELEASES = [
	forkRelease("v158.0-beta.33-fork.2", FORK_2),
	forkRelease("v158.0-beta.33-fork.1", FORK_1),
];
const UPSTREAM_RELEASES = [
	{
		tag_name: "v135.0-beta.25",
		prerelease: false,
		assets: ["lin.x86_64", "mac.arm64", "win.x86_64"].map((osArch) =>
			asset(`camoufox-135.0-beta.25-${osArch}.zip`, "9".repeat(64)),
		),
	},
] as any;

freshCachePerTest("fork");
let asked: string[];

beforeEach(() => {
	asked = [];
});

afterEach(() => {
	vi.restoreAllMocks();
});

async function fetcherFor(osName: string, arch: string) {
	const pkgman = await import("../src/pkgman.js");
	const pin = await import("../src/browser-pin.js");
	vi.spyOn(pin, "effectivePin").mockReturnValue(null);
	const fetcher: any = Object.create(pkgman.CamoufoxFetcher.prototype);
	fetcher.repoConfig = pkgman.RepoConfig.getDefault();
	fetcher.githubRepos = fetcher.repoConfig.repos;
	fetcher.githubRepo = fetcher.githubRepos[0];
	fetcher.isPrerelease = false;
	fetcher.arch = arch;
	fetcher.pattern = fetcher.repoConfig.buildPattern(osName, arch);
	fetcher.installedInterface = 1;
	fetcher.getReleases = async (repo: string) => {
		asked.push(repo);
		return repo === FORK ? FORK_RELEASES : UPSTREAM_RELEASES;
	};
	return fetcher;
}

describe("the default browser", () => {
	it("is this fork's releases alone", async () => {
		const { RepoConfig } = await import("../src/pkgman.js");
		const config = RepoConfig.getDefault();
		expect([config.name, config.repos]).toEqual(["lang315", [FORK]]);
	});

	it("leaves the other browser sources chosen by name", async () => {
		const { RepoConfig } = await import("../src/pkgman.js");
		expect(RepoConfig.findByName("Official")?.repos).toEqual([
			UPSTREAM,
			"camoufox/camoufox",
		]);
		expect(RepoConfig.findByName("lang315")?.repos).toEqual([FORK]);
	});
});

describe("fetching", () => {
	it.each([
		["mac", "arm64"],
		["win", "x86_64"],
	])("takes the newest fork release on %s", async (osName, arch) => {
		const fetcher = await fetcherFor(osName, arch);
		const [version, url] = await fetcher.getAsset();
		expect([version.version, version.build]).toEqual(["158.0", "beta.33"]);
		expect(url).toContain(FORK_2.slice(0, 8));
		expect(fetcher.installedSha256).toBe(FORK_2);
		expect(asked).toEqual([FORK]);
	});

	it("finds no fork package on Linux and never asks upstream", async () => {
		const fetcher = await fetcherFor("lin", "x86_64");
		const { MissingRelease } = await import("../src/exceptions.js");
		await expect(fetcher.getAsset()).rejects.toBeInstanceOf(MissingRelease);
		expect(asked).toEqual([FORK]);
	});
});

describe("deciding that a machine is up to date", () => {
	it("moves a machine from fork.1 to fork.2, which share a version and build", async () => {
		const { updateNeeded } = await import("../src/pkgman.js");
		expect(updateNeeded("158.0-beta.33", FORK_1, "158.0-beta.33", FORK_2)).toBe(
			true,
		);
	});

	it("leaves the same asset alone", async () => {
		const { updateNeeded } = await import("../src/pkgman.js");
		expect(updateNeeded("158.0-beta.33", FORK_2, "158.0-beta.33", FORK_2)).toBe(
			false,
		);
	});

	it.each([
		[undefined, FORK_2],
		[FORK_1, undefined],
		[undefined, undefined],
	])("leaves the version comparison alone when a digest is unknown (%s, %s)", async (current, selected) => {
		const { updateNeeded } = await import("../src/pkgman.js");
		expect(
			updateNeeded("158.0-beta.33", current, "158.0-beta.33", selected),
		).toBe(false);
	});

	it("updates on a new version whatever the digests are", async () => {
		const { updateNeeded } = await import("../src/pkgman.js");
		expect(
			updateNeeded("156.0.1-beta.32", FORK_2, "158.0-beta.33", FORK_2),
		).toBe(true);
		expect(updateNeeded(null, undefined, "158.0-beta.33", undefined)).toBe(
			true,
		);
	});
});

describe("the cache", () => {
	it("keeps a fork install and an upstream install of one version apart", async () => {
		const mv = await import("../src/multiversion.js");
		const add = (repo: string, folder: string, sha: string) => {
			const dir = path.join(mv.BROWSERS_DIR, repo, folder);
			fs.mkdirSync(dir, { recursive: true });
			fs.writeFileSync(
				path.join(dir, "version.json"),
				JSON.stringify({ version: "158.0", build: "beta.33", sha256: sha }),
			);
			return dir;
		};
		const official = add("official", "158.0-beta.33-99999999", "9".repeat(64));
		const fork = add("lang315", `158.0-beta.33-${FORK_2.slice(0, 8)}`, FORK_2);

		const installed = mv.listInstalled();
		expect(installed.map((v) => [v.repoName, v.path]).sort()).toEqual(
			[
				["lang315", fork],
				["official", official],
			].sort(),
		);
	});
});
