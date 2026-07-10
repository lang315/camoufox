#ifndef CAMOUFOX_ACCESS_OBSERVER_HPP
#define CAMOUFOX_ACCESS_OBSERVER_HPP
#include <cstdint>
#include <string>

namespace camoufox {

enum class SurfaceId : uint16_t {
  Canvas = 1, WebGL = 2, WebRTC = 3, Navigator = 4,
  Screen = 5, Fonts = 6, Audio = 7,
};

class AccessObserver {
 public:
  // O(1), allocation-free, thread-safe. No-op when disarmed. Safe off-main-thread.
  static void Record(uint32_t userContextId, const std::string& site,
                     SurfaceId surface, uint64_t tsMillis);
  // Cached once (env CAMOU_OBSERVE; compile-time flag supersedes in Task 9).
  static bool IsArmed();
  // Pops all buffered records as a JSON array string. Main-thread drain path.
  static std::string DrainJSON();
  // Test-only override of the armed flag.
  static void ForceArmForTest(bool armed);
};

}  // namespace camoufox
#endif
