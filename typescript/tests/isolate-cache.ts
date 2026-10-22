/**
 * vitest setup file: runs before every test file, so none of them can reach the
 * developer's real camoufox cache whatever its own setup does or forgets (#267).
 * A file that needs a different or fresher cache asks for one through
 * cache-home.ts.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterAll } from "vitest";
import { isolateCacheAt } from "./cache-home.js";

const root = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-file-"));
await isolateCacheAt(root);

afterAll(() => {
	fs.rmSync(root, { recursive: true, force: true });
});
