import { recordWarnings } from "../src/warnings.js";

/**
 * Run `fn` with warnings captured, and give back its result. recordWarnings
 * returns the error `fn` threw instead of throwing it, so a caller that reads
 * only `result` gets undefined and fails later on a TypeError of its own.
 */
export async function quietly<T>(fn: () => T | Promise<T>): Promise<T> {
	const outcome = await recordWarnings(fn);
	if ("error" in outcome) throw outcome.error;
	return outcome.result as T;
}
