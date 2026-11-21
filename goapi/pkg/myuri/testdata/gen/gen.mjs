// Records what @jwriter20/myuri's Actions ask of a host, for fixed seeds and
// inputs, into ../{mouse,scroll,typing,key}.json. The Go port replays the same
// scenarios and must issue the same calls (myuri_test.go).
//
//   npm ci && node gen.mjs
//
// Regenerate the goldens whenever the pinned myuri version (package.json) changes,
// and run `node tables.mjs` too: the Go tables are copied from that version.
//
// The host is a fake with a virtual clock: sleep(ms) and a click's hold advance
// it by exactly ms, so a run is deterministic and takes no real time. Each page
// target is a scripted sequence of scroll plans and hit-test answers, so a
// scenario needs no browser. `go test` reads the goldens; it never runs this.
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Actions, HIT_TEST_JS, SCROLL_PLAN_JS, makeRng } from '@jwriter20/myuri';

const here = dirname(fileURLToPath(import.meta.url));
// Recorded in each golden, so a stale one is visible. The packages export no package.json.
const lock = JSON.parse(readFileSync(join(here, 'package-lock.json'), 'utf8')).packages;
const versions = {
    myuri: lock['node_modules/@jwriter20/myuri'].version,
    'cursory-js': lock['node_modules/cursory-js'].version,
};

const VIEWPORT = [1280, 720];
const CLOCK_START = 1000;

async function record(scenario) {
    const calls = [];
    let now = CLOCK_START;
    const cursors = {};
    const next = (list, key) => {
        const i = cursors[key] ?? 0;
        cursors[key] = i + 1;
        return list[Math.min(i, list.length - 1)];
    };
    const host = {
        async move(x, y) { calls.push(['move', x, y]); },
        async click(button, count, hold) { calls.push(['click', button, count, hold]); now += hold; },
        async down(button) { calls.push(['down', button]); },
        async up(button) { calls.push(['up', button]); },
        async wheel(dx, dy) { calls.push(['wheel', dx, dy]); },
        async keyDown(key) { calls.push(['keyDown', key]); },
        async keyUp(key) { calls.push(['keyUp', key]); },
        async insertText(text) { calls.push(['insertText', text]); },
        async viewport() { calls.push(['viewport']); return VIEWPORT; },
        now: () => now,
        async sleep(ms) { calls.push(['sleep', ms]); now += ms; },
        async offset(target) {
            calls.push(['offset', target.name]);
            return scenario.targets[target.name].offset;
        },
        async evaluate(target, fn, arg) {
            const spec = scenario.targets[target.name];
            if (fn === SCROLL_PLAN_JS) {
                calls.push(['plan', target.name, arg.fromX, arg.fromY, arg.finishPosition, arg.pad, arg.edge]);
                return structuredClone(next(spec.plans, `${target.name}:plan`));
            }
            if (fn === HIT_TEST_JS) {
                calls.push(['hit', target.name, arg.x, arg.y, arg.pressing]);
                return next(spec.hits, `${target.name}:hit`);
            }
            throw new Error('unexpected page function');
        },
    };
    const actions = new Actions(host, makeRng(scenario.seed), { os: scenario.os, device: 'mouse', wpm: scenario.wpm });
    for (const op of scenario.ops) {
        try {
            if (op.op === 'move') await actions.move(op.x, op.y);
            else if (op.op === 'clickAt') await actions.clickAt(op.x, op.y, op.button, op.count);
            else if (op.op === 'press') await actions.press(op.button, op.count, op.modifiers);
            else if (op.op === 'wheel') await actions.wheel(op.dx, op.dy);
            else if (op.op === 'intoView') await actions.intoView({ name: op.target });
            else if (op.op === 'type') await actions.type(op.text);
            else if (op.op === 'key') await actions.key(op.key);
            else if (op.op === 'click') await actions.click({ name: op.target }, op.opts);
            else throw new Error(`unknown op ${op.op}`);
        } catch (e) {
            calls.push(['error', `${e.name}: ${e.message}`]);
        }
    }
    return { ...scenario, calls };
}

const rect = (x, y, width, height) => ({ x, y, width, height });
const plan = (over) => ({
    inView: true, deltaY: 0, hoverX: 640, hoverY: 360, isPage: true,
    region: rect(200, 300, 120, 40), box: rect(200, 300, 120, 40), borders: [1, 1],
    ...over,
});

// seed -> the OS its person is on, so every wheel style and move cadence is covered.
const SEEDS = [[1, 'macos'], [7, 'windows'], [42, 'linux'], [12345, 'macos'], [4294967295, 'windows']];

const mouseTargets = {
    // The first press misses (another element covers it); the retry reaches.
    covered: { offset: [0, 0], plans: [plan({})], hits: ['<div> intercepts pointer events', null] },
    ok: { offset: [0, 0], plans: [plan({ region: rect(600, 100, 200, 60), box: rect(590, 90, 220, 80) })], hits: [null] },
    // In a same-origin iframe: plans are in the frame's coordinates.
    framed: { offset: [30, 50], plans: [plan({ region: rect(40, 40, 90, 30), box: rect(30, 30, 110, 50) })], hits: [null] },
    gone: { offset: null, plans: [null], hits: [null] },
    offscreen: { offset: [0, 0], plans: [plan({ inView: false, region: null })], hits: [null] },
};

const mouseOps = [
    { op: 'move', x: 640, y: 360 },
    { op: 'move', x: 700, y: 400 },
    { op: 'move', x: 100, y: 650 },
    { op: 'move', x: 100, y: 650 },
    { op: 'move', x: 1200, y: 700 },
    { op: 'move', x: 1210, y: 705 },
    { op: 'clickAt', x: 300, y: 300, button: 'left', count: 1 },
    { op: 'clickAt', x: 302, y: 301, button: 'left', count: 2 },
    { op: 'press', button: 'left', count: 3 },
    { op: 'press', button: 'right', count: 1, modifiers: ['Shift', 'Control'] },
    { op: 'click', target: 'covered', opts: {} },
    { op: 'click', target: 'ok', opts: { button: 'middle', clickCount: 2 } },
    { op: 'click', target: 'ok', opts: { press: false } },
    { op: 'click', target: 'ok', opts: { position: { x: 12, y: 7 }, modifiers: ['Alt'] } },
    { op: 'click', target: 'framed', opts: {} },
    { op: 'click', target: 'covered', opts: { force: true } },
    { op: 'click', target: 'gone', opts: { attempts: 1 } },
    { op: 'click', target: 'offscreen', opts: { attempts: 2 } },
    { op: 'click', target: 'offscreen', opts: { timeout: 50 } },
];

// A target below the fold: not in view, the wheel runs, the element settles over
// two reads, and the next pass finds it in view.
const scrollTargets = {
    far: {
        offset: [0, 0],
        plans: [
            plan({ inView: false, deltaY: 900, region: null, box: rect(100, 1200, 300, 50) }),
            plan({ inView: false, deltaY: 0, box: rect(100, 640, 300, 50) }),
            plan({ inView: false, deltaY: 0, box: rect(100, 310, 300, 50) }),
            plan({ inView: false, deltaY: 0, box: rect(100, 310, 300, 50) }),
            plan({ inView: true, box: rect(100, 310, 300, 50), region: rect(100, 310, 300, 50) }),
        ],
        hits: [null],
    },
    // Scrolled up, inside an iframe, then clicked.
    back: {
        offset: [10, 20],
        plans: [
            plan({ inView: false, deltaY: -400, hoverX: 500, hoverY: 300, isPage: false, region: null, box: rect(50, -300, 200, 40) }),
            plan({ inView: false, deltaY: 0, box: rect(50, 100, 200, 40) }),
            plan({ inView: false, deltaY: 0, box: rect(50, 100, 200, 40) }),
            plan({ inView: true, box: rect(50, 200, 200, 40), region: rect(50, 200, 200, 40) }),
        ],
        hits: [null],
    },
    // A page that never stops moving: the landing wait gives up after its limit.
    drifting: {
        offset: [0, 0],
        plans: Array.from({ length: 80 }, (_, i) => plan({ inView: false, deltaY: i === 0 ? 300 : 0, region: null, box: rect(100, 900 - i * 7, 300, 50) })),
        hits: [null],
    },
    visible: { offset: [0, 0], plans: [plan({})], hits: [null] },
    gone: { offset: null, plans: [null], hits: [null] },
};

const scrollOps = [
    { op: 'wheel', dx: 0, dy: 700 },
    { op: 'wheel', dx: 0, dy: -250 },
    { op: 'wheel', dx: 0, dy: 60 },
    { op: 'wheel', dx: 0, dy: 3 },
    { op: 'wheel', dx: 300, dy: 0 },
    { op: 'wheel', dx: -200, dy: 400 },
    { op: 'wheel', dx: 0, dy: 0 },
    { op: 'wheel', dx: 0, dy: 2400 },
    { op: 'intoView', target: 'visible' },
    { op: 'intoView', target: 'gone' },
    { op: 'intoView', target: 'far' },
    { op: 'click', target: 'back', opts: {} },
    { op: 'intoView', target: 'drifting' },
];

async function write(file, targets, ops, seeds = SEEDS) {
    const cases = [];
    for (const [seed, os, wpm] of seeds) {
        cases.push(await record({ name: `${file}-${seed}-${os}`, seed, os, wpm, targets, ops }));
    }
    writeFileSync(join(here, '..', `${file}.json`), `${JSON.stringify({ versions, viewport: VIEWPORT, clockStart: CLOCK_START, cases })}\n`);
}

await write('mouse', mouseTargets, mouseOps);
await write('scroll', scrollTargets, scrollOps);

// Typing and keys: a capital and punctuation, non-ASCII (accents the typer may
// mistype, CJK and an emoji it types literally), and a long text with a newline
// and digits. One stream per case, so each text starts where the last left off.
// The third value is the typist's wpm (undefined: myuri's 80).
const KEY_SEEDS = [[1, 'macos', undefined], [42, 'linux', 55], [4294967295, 'windows', 120]];
const typingOps = [
    { op: 'type', text: 'Hello, World.' },
    { op: 'type', text: 'café naïve ÉCOLE 日本語 😀' },
    { op: 'type', text: 'The quick brown fox jumps over 13 lazy dogs;\nthey zigzag, quickly!' },
];
const keyOps = ['Enter', 'Tab', 'Control+a', 'Meta+Shift+z', 'A', '?', 'Control++', '+', 'Backspace'].map((key) => ({ op: 'key', key }));

await write('typing', {}, typingOps, KEY_SEEDS);
await write('key', {}, keyOps, KEY_SEEDS);
