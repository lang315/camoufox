// Standalone unit test — NOT compiled into xul. MouseTrajectories.hpp is
// header-only, so there is no .cpp to compile alongside (like
// test_access_observer.cpp). It transitively includes MaskConfig.hpp, which
// pulls in the Gecko-only "mozilla/glue/Debug.h" for printf_stderr();
// test_stubs/ provides a minimal stand-in so this compiles outside the
// Firefox tree. Build with:
//   clang++ -std=c++17 -I test_stubs test_mouse_trajectories.cpp -o /tmp/mtest && /tmp/mtest
//
// Regression test for #412: humanized mouse.move() stopped a fraction short
// of the destination instead of landing on it exactly.
#include "MouseTrajectories.hpp"
#include <cstdio>
#include <cmath>
#include <utility>
#include <vector>
#include <random>

namespace {

int gFailures = 0;

void checkLandsExactlyOnTarget(std::pair<double, double> from,
                               std::pair<double, double> to) {
  HumanizeMouseTrajectory traj(from, to);
  std::vector<int> pts = traj.getPoints();

  if (pts.empty() || pts.size() % 2 != 0) {
    printf("FAIL: bad point list size %zu for (%.1f,%.1f)->(%.1f,%.1f)\n",
           pts.size(), from.first, from.second, to.first, to.second);
    gFailures++;
    return;
  }

  size_t n = pts.size() / 2;
  int lastX = pts[pts.size() - 2];
  int lastY = pts[pts.size() - 1];
  int expectedX = static_cast<int>(std::round(to.first));
  int expectedY = static_cast<int>(std::round(to.second));

  if (lastX != expectedX || lastY != expectedY) {
    printf(
        "FAIL: (%.1f,%.1f)->(%.1f,%.1f): last point = (%d,%d), expected "
        "(%d,%d)\n",
        from.first, from.second, to.first, to.second, lastX, lastY,
        expectedX, expectedY);
    gFailures++;
  }

  if (n <= 1) {
    printf("FAIL: only %zu point(s) generated for (%.1f,%.1f)->(%.1f,%.1f)\n",
           n, from.first, from.second, to.first, to.second);
    gFailures++;
  }

  // Shape sanity: for a non-zero move, the path should actually start away
  // from the destination -- i.e. it isn't collapsed onto the target
  // throughout, only reaching it at the very end.
  if (from.first != to.first || from.second != to.second) {
    double startDist = std::hypot(pts[0] - expectedX, pts[1] - expectedY);
    if (startDist <= 0.0) {
      printf("FAIL: (%.1f,%.1f)->(%.1f,%.1f): path starts on destination\n",
             from.first, from.second, to.first, to.second);
      gFailures++;
    }
  }
}

}  // namespace

int main() {
  // Hand-picked edge cases: ordinary move, very short move, long move
  // crossing quadrants, zero-length move, negative coordinates.
  checkLandsExactlyOnTarget({0, 0}, {100, 100});
  checkLandsExactlyOnTarget({50, 50}, {51, 50});
  checkLandsExactlyOnTarget({500, 500}, {10, 800});
  checkLandsExactlyOnTarget({0, 0}, {0, 0});
  checkLandsExactlyOnTarget({-40, 300}, {700, -20});

  // Randomized sweep: the curve depends on a randomly-seeded internal
  // engine (knot placement + jitter), so repeat across many (from, to)
  // pairs to make sure no geometry/seed combination samples a final index
  // short of the destination.
  std::mt19937 rng(0xC0FFEE);
  std::uniform_real_distribution<double> coord(-2000.0, 2000.0);
  for (int i = 0; i < 300; i++) {
    std::pair<double, double> from = {coord(rng), coord(rng)};
    std::pair<double, double> to = {coord(rng), coord(rng)};
    checkLandsExactlyOnTarget(from, to);
  }

  if (gFailures) {
    printf("%d FAILURE(S)\n", gFailures);
    return 1;
  }
  printf("ALL PASS\n");
  return 0;
}
