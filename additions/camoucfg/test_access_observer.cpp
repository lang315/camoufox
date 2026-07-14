// Standalone unit test — NOT compiled into xul. AccessObserver is header-only,
// so there is no .cpp to compile alongside. Build with:
//   clang++ -std=c++17 test_access_observer.cpp -o /tmp/aotest && /tmp/aotest
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
  // Distinct sites so dedup doesn't collapse them (that's tested separately).
  for (int i = 0; i < 100000; ++i)
    AccessObserver::Record(1, "x" + std::to_string(i) + ".com", SurfaceId::WebGL, i);
  std::string big = AccessObserver::DrainJSON();
  assert(!big.empty() && big.front() == '[' && big.back() == ']');
  assert(AccessObserver::DrainJSON() == "[]");

  // Dedup: same (userContextId, surface, site) recorded repeatedly within a
  // drain window collapses to one record (differing timestamps are ignored).
  for (int i = 0; i < 50; ++i)
    AccessObserver::Record(3, "dedup.com", SurfaceId::Audio, 1000 + i);
  std::string dj = AccessObserver::DrainJSON();
  assert(dj.find("dedup.com") != std::string::npos);
  // exactly one record => exactly one closing "}" of a record object
  assert(dj.find("},{") == std::string::npos);
  // After the drain, gSeen is cleared, so the same key records again.
  AccessObserver::Record(3, "dedup.com", SurfaceId::Audio, 2000);
  assert(AccessObserver::DrainJSON().find("dedup.com") != std::string::npos);
  // A different surface on the same site is a distinct key (not deduped).
  AccessObserver::Record(3, "dedup.com", SurfaceId::Audio, 1);
  AccessObserver::Record(3, "dedup.com", SurfaceId::Canvas, 1);
  std::string two = AccessObserver::DrainJSON();
  assert(two.find("},{") != std::string::npos);  // two distinct records
  (void)AccessObserver::DrainJSON();

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
