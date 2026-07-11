#include "AccessObserver.hpp"

#ifdef MOZ_CAMOU_OBSERVE
#include <array>
#include <mutex>
#include <atomic>
#include <cstdlib>

namespace camoufox {
namespace {

struct Record_t {
  uint32_t userContextId;
  uint64_t tsMillis;
  uint16_t surface;
  char site[64];   // POD, fixed — no allocation on the hot path
};

constexpr size_t kCapacity = 4096;

std::mutex gMutex;
std::array<Record_t, kCapacity> gBuf;
size_t gCount = 0;               // number of valid records [0, kCapacity]

std::atomic<int> gForcedArm{-1}; // -1 = use env, 0/1 = forced (test)

void AppendEscaped(std::string& out, const char* s) {
  for (const char* p = s; *p; ++p) {
    if (*p == '"' || *p == '\\') out.push_back('\\');
    out.push_back(*p);
  }
}

}  // namespace

bool AccessObserver::IsArmed() {
  int forced = gForcedArm.load(std::memory_order_relaxed);
  if (forced >= 0) return forced == 1;
  static const bool sArmed = [] {
    const char* v = std::getenv("CAMOU_OBSERVE");
    return v && v[0] && !(v[0] == '0' && v[1] == '\0');
  }();
  return sArmed;
}

void AccessObserver::ForceArmForTest(bool armed) {
  gForcedArm.store(armed ? 1 : 0, std::memory_order_relaxed);
}

void AccessObserver::Record(uint32_t userContextId, const std::string& site,
                            SurfaceId surface, uint64_t tsMillis) {
  if (!IsArmed()) return;
  std::lock_guard<std::mutex> lock(gMutex);
  if (gCount >= kCapacity) return;   // bounded: drop newest, never OOB/crash
  Record_t& r = gBuf[gCount++];
  r.userContextId = userContextId;
  r.tsMillis = tsMillis;
  r.surface = static_cast<uint16_t>(surface);
  size_t n = site.size() < sizeof(r.site) - 1 ? site.size() : sizeof(r.site) - 1;
  for (size_t i = 0; i < n; ++i) r.site[i] = site[i];
  r.site[n] = '\0';
}

std::string AccessObserver::DrainJSON() {
  std::lock_guard<std::mutex> lock(gMutex);
  std::string out = "[";
  for (size_t i = 0; i < gCount; ++i) {
    const Record_t& r = gBuf[i];
    if (i) out.push_back(',');
    out += "{\"u\":";
    out += std::to_string(r.userContextId);
    out += ",\"s\":\"";
    AppendEscaped(out, r.site);
    out += "\",\"f\":";
    out += std::to_string(r.surface);
    out += ",\"t\":";
    out += std::to_string(r.tsMillis);
    out += "}";
  }
  out.push_back(']');
  gCount = 0;
  return out;
}

}  // namespace camoufox

#else  // !MOZ_CAMOU_OBSERVE — instrumentation compiled out, callers still link.

namespace camoufox {

bool AccessObserver::IsArmed() { return false; }

void AccessObserver::ForceArmForTest(bool /* armed */) {}

void AccessObserver::Record(uint32_t /* userContextId */,
                            const std::string& /* site */,
                            SurfaceId /* surface */, uint64_t /* tsMillis */) {}

std::string AccessObserver::DrainJSON() { return "[]"; }

}  // namespace camoufox

#endif  // MOZ_CAMOU_OBSERVE
