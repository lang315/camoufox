/** Twin of python/tests/test_display.py TestVisibleHeight (#514). */
import { beforeEach, describe, expect, it, vi } from "vitest";

const osascript = vi.hoisted(() => vi.fn());
const host = vi.hoisted(() => ({ os: "mac" }));

vi.mock("node:child_process", () => ({ execFileSync: osascript }));
vi.mock("../src/paths.js", async (importOriginal) => ({
	...(await importOriginal<typeof import("../src/paths.js")>()),
	get OS_NAME() {
		return host.os;
	},
}));

const { visibleHeight } = await import("../src/display.js");

describe("visibleHeight", () => {
	beforeEach(() => {
		host.os = "mac";
		osascript.mockReset();
	});

	it("is null off macOS", () => {
		host.os = "lin";
		expect(visibleHeight()).toBeNull();
		expect(osascript).not.toHaveBeenCalled();
	});

	it("is the largest screen's visible height", () => {
		osascript.mockReturnValue(
			JSON.stringify([
				[1024, 768, 674],
				[2560, 1440, 1337.5],
			]),
		);
		expect(visibleHeight()).toBe(1337);
	});

	it("takes the first of equally large screens", () => {
		osascript.mockReturnValue(
			JSON.stringify([
				[1920, 1080, 1000],
				[1920, 1080, 900],
			]),
		);
		expect(visibleHeight()).toBe(1000);
	});

	it("is null when osascript fails or prints nothing usable", () => {
		osascript.mockImplementation(() => {
			throw new Error("osascript failed");
		});
		expect(visibleHeight()).toBeNull();
		osascript.mockReset();
		osascript.mockReturnValue("[]");
		expect(visibleHeight()).toBeNull();
	});
});
