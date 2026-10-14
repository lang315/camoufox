#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BINARY=""
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile-count|--secret|--save-cert)
            EXTRA_ARGS+=("$1" "$2")
            shift 2
            ;;
        --no-cert)
            EXTRA_ARGS+=("$1")
            shift
            ;;
        -h|--help)
            echo "Usage: $0 <binary_path> [--profile-count N] [--secret KEY] [--save-cert PATH] [--no-cert]"
            echo "  e.g. $0 ../../camoufox-<version>-<release>/obj-x86_64-pc-linux-gnu/dist/bin/camoufox-bin"
            exit 0
            ;;
        -*)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
        *)
            if [ -n "$BINARY" ]; then
                echo "Unexpected positional argument: $1 (binary already set to $BINARY)" >&2
                exit 1
            fi
            BINARY="$1"
            shift
            ;;
    esac
done

if [ -z "$BINARY" ]; then
    echo "ERROR: binary_path is required" >&2
    echo "Usage: $0 <binary_path> [options]" >&2
    exit 1
fi

if [ ! -d "node_modules" ]; then
    echo "==> Installing npm dependencies (esbuild)..."
    npm install --silent
fi

if [ ! -d ".venv" ]; then
    echo "==> Creating virtual environment..."
    python3 -m venv .venv
fi

PYTHON=".venv/bin/python"
PIP=".venv/bin/pip"

echo "==> Installing camoufox from local source + playwright..."
$PIP uninstall -y cloverlabs-camoufox >/dev/null 2>&1 || true
# Cap, do not pin, and keep it identical to requirements.txt -- this script and
# ci.run_build_tester must not answer differently about what is under test.
#
# This was `playwright==1.55.0`, because 1.58+ sent a Browser.setDefaultViewport
# this juggler's protocol schema rejected: every context creation failed and the
# suite reported 0/0 Grade F, which reads as a spoofing regression but was
# harness drift. That measurement was taken on camoufox-152.0.4-beta.25, which
# predates 2b662a8 ("Support Playwright 1.61+"); the schema now accepts the
# drifted shape, so the reason no longer describes the browser this installs
# against. Re-measured on 152.0.4-beta.31 (build 34936850063, macOS arm64), four
# runs, two per version: 1.55.0 scored 1062 and 1062 of 1070, 1.62.0 scored 1061
# and 1062, Grade A throughout, the same eight canvasPerturbation checks failing
# in both. The one-point gap is a cross-profile screen-uniqueness draw, not the
# version: the second run of each arm has it agreeing.
$PIP install -q -e ../../../python 'playwright<1.63'

echo "==> Running build tester..."
# scripts/runner.py launches headful, so the WebGL checks run against a real GL
# context (issues #75, #195). A Linux host with no display borrows one from xvfb;
# with neither, the run fails rather than testing less.
if [ -n "$DISPLAY" ] || [ "$(uname -s)" != "Linux" ]; then
    $PYTHON scripts/run_tests.py "$BINARY" "${EXTRA_ARGS[@]}"
elif command -v xvfb-run >/dev/null 2>&1; then
    echo "    (no DISPLAY -- running under xvfb)"
    LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}" \
        xvfb-run -a --server-args="-screen 0 1920x1080x24" \
        $PYTHON scripts/run_tests.py "$BINARY" "${EXTRA_ARGS[@]}"
else
    echo "ERROR: no DISPLAY and no xvfb-run. build-tester launches headful." >&2
    echo "    Install xvfb (apt install xvfb) or run with a display." >&2
    exit 1
fi
