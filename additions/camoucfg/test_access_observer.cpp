// Standalone unit test — NOT compiled into xul. Build with:
//   clang++ -std=c++17 -DCAMOU_OBSERVE_TEST test_access_observer.cpp AccessObserver.cpp -o /tmp/aotest
#include "AccessObserver.hpp"
#include <cassert>
#include <cstdio>
#include <string>
using namespace camoufox;

int main() {
  // Force-arm for the test regardless of env.
  AccessObserver::ForceArmForTest(true);

  // Empty drain is a valid empty array.
  assert(AccessObserver::DrainJSON() == "[]");

  // One record round-trips with all fields.
  AccessObserver::Record(2, "facebook.com", SurfaceId::Canvas, 1000);
  std::string j = AccessObserver::DrainJSON();
  assert(j.find("\"u\":2") != std::string::npos);
  assert(j.find("\"s\":\"facebook.com\"") != std::string::npos);
  assert(j.find("\"f\":1") != std::string::npos);
  assert(j.find("\"t\":1000") != std::string::npos);

  // Drain clears: second drain is empty.
  assert(AccessObserver::DrainJSON() == "[]");

  // Overflow is bounded and lossy-newest-dropped, never a crash or OOB.
  for (int i = 0; i < 100000; ++i)
    AccessObserver::Record(1, "x.com", SurfaceId::WebGL, i);
  std::string big = AccessObserver::DrainJSON();
  assert(!big.empty() && big.front() == '[' && big.back() == ']');
  assert(AccessObserver::DrainJSON() == "[]");

  // Disarmed => Record is a no-op.
  AccessObserver::ForceArmForTest(false);
  AccessObserver::Record(2, "facebook.com", SurfaceId::Canvas, 1);
  AccessObserver::ForceArmForTest(true);
  assert(AccessObserver::DrainJSON() == "[]");

  // Site with a double-quote is JSON-escaped (defense in depth).
  AccessObserver::Record(0, "a\"b.com", SurfaceId::Fonts, 5);
  std::string esc = AccessObserver::DrainJSON();
  assert(esc.find("a\\\"b.com") != std::string::npos);

  printf("ALL PASS\n");
  return 0;
}
