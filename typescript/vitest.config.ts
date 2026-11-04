import { defineConfig } from "vitest/config";

// Vitest finds this file only in the package root, so a bare `vitest run <file>`
// gets the cache isolation too (#410).
export default defineConfig({
	test: {
		include: ["tests/**/*.test.ts"],
		globalSetup: ["tests/golden-setup.ts"],
		setupFiles: ["tests/isolate-cache.ts"],
		testTimeout: 30_000,
		hookTimeout: 30_000,
	},
});
