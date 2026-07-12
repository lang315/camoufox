#ifndef CAMOUFOX_ACCESS_OBSERVER_HPP
#define CAMOUFOX_ACCESS_OBSERVER_HPP
#include <cstdint>
#include <string>
#include <array>
#include <mutex>
#include <atomic>
#include <cstdlib>

// Header-only (like MaskConfig.hpp / MouseTrajectories.hpp) — the camoucfg dir
// is NOT a compiled build target, so any out-of-line .cpp definition here never
// links into XUL. All state and functions are therefore inline. Single shared
// bounded buffer across all TUs via C++17 inline variables (on overflow it
// drops the NEWEST records — not a ring; see Record()). Gated at runtime by
// the CAMOU_OBSERVE env var, read once (cached) — disarmed default path is a
// single predicted-not-taken branch, no per-call getenv.

namespace camoufox {

enum class SurfaceId : uint16_t {
  Canvas = 1, WebGL = 2, WebRTC = 3, Navigator = 4,
  Screen = 5, Fonts = 6, Audio = 7,
};

namespace access_detail {

struct AccessRecord {
  uint32_t userContextId;
  uint64_t tsMillis;
  uint16_t surface;
  char site[64];  // POD, fixed — no allocation on the hot path
};

constexpr size_t kCapacity = 4096;

// C++17 inline variables: exactly one shared instance across every TU that
// includes this header, so a Record() in the canvas TU and a DrainJSON() in the
// ChromeUtils binding TU touch the same buffer.
inline std::mutex gMutex;
inline std::array<AccessRecord, kCapacity> gBuf;
inline size_t gCount = 0;
inline std::atomic<int> gForcedArm{-1};  // -1 = use env, 0/1 = forced (test)

inline void AppendEscaped(std::string& out, const char* s) {
  for (const char* p = s; *p; ++p) {
    if (*p == '"' || *p == '\\') out.push_back('\\');
    out.push_back(*p);
  }
}

}  // namespace access_detail

class AccessObserver {
 public:
  // Cached once from env CAMOU_OBSERVE. Runtime gate (compile-time gate dropped:
  // incompatible with header-only, and the cached bool keeps the off path free).
  static inline bool IsArmed() {
    int forced = access_detail::gForcedArm.load(std::memory_order_relaxed);
    if (forced >= 0) return forced == 1;
    static const bool sArmed = [] {
      const char* v = std::getenv("CAMOU_OBSERVE");
      return v && v[0] && !(v[0] == '0' && v[1] == '\0');
    }();
    return sArmed;
  }

  // Test-only override of the armed flag.
  static inline void ForceArmForTest(bool armed) {
    access_detail::gForcedArm.store(armed ? 1 : 0, std::memory_order_relaxed);
  }

  // O(1), allocation-free, thread-safe. No-op when disarmed. Safe off-main-thread.
  static inline void Record(uint32_t userContextId, const std::string& site,
                            SurfaceId surface, uint64_t tsMillis) {
    if (!IsArmed()) return;
    std::lock_guard<std::mutex> lock(access_detail::gMutex);
    if (access_detail::gCount >= access_detail::kCapacity) return;  // bounded
    access_detail::AccessRecord& r = access_detail::gBuf[access_detail::gCount++];
    r.userContextId = userContextId;
    r.tsMillis = tsMillis;
    r.surface = static_cast<uint16_t>(surface);
    size_t n = site.size() < sizeof(r.site) - 1 ? site.size() : sizeof(r.site) - 1;
    for (size_t i = 0; i < n; ++i) r.site[i] = site[i];
    r.site[n] = '\0';
  }

  // Pops all buffered records as a JSON array string. Empty -> "[]".
  static inline std::string DrainJSON() {
    std::lock_guard<std::mutex> lock(access_detail::gMutex);
    std::string out = "[";
    for (size_t i = 0; i < access_detail::gCount; ++i) {
      const access_detail::AccessRecord& r = access_detail::gBuf[i];
      if (i) out.push_back(',');
      out += "{\"u\":";
      out += std::to_string(r.userContextId);
      out += ",\"s\":\"";
      access_detail::AppendEscaped(out, r.site);
      out += "\",\"f\":";
      out += std::to_string(r.surface);
      out += ",\"t\":";
      out += std::to_string(r.tsMillis);
      out += "}";
    }
    out.push_back(']');
    access_detail::gCount = 0;
    return out;
  }
};

}  // namespace camoufox
#endif
