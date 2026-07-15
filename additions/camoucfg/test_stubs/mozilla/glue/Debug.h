// Test-only stub of mozilla/glue/Debug.h — NOT part of the Gecko build.
//
// MouseTrajectories.hpp includes MaskConfig.hpp, which includes the real
// "mozilla/glue/Debug.h" (for printf_stderr) that only exists inside the
// Firefox source tree. This directory is not on the Gecko build's include
// path (see moz.build: LOCAL_INCLUDES is "/camoucfg", not
// "/camoucfg/test_stubs"), so it never shadows the real header there — it
// only exists to let test_mouse_trajectories.cpp compile standalone with:
//   clang++ -std=c++17 -I test_stubs test_mouse_trajectories.cpp -o /tmp/t && /tmp/t
#pragma once
#include <cstdio>
#include <cstdarg>

inline void printf_stderr(const char* fmt, ...) {
  va_list args;
  va_start(args, fmt);
  vfprintf(stderr, fmt, args);
  va_end(args);
}
