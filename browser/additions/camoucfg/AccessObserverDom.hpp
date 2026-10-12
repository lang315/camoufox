#ifndef CAMOUFOX_ACCESS_OBSERVER_DOM_HPP
#define CAMOUFOX_ACCESS_OBSERVER_DOM_HPP

// DOM-aware convenience wrapper over AccessObserver::Record().
//
// Kept OUT of AccessObserver.hpp so that header stays a pure POD/std buffer with
// no Gecko dependencies; only the surface emit sites (canvas / navigator /
// screen / fonts / audio / webrtc) pull this in. It factors out the
// Document -> principal -> (base-domain, userContextId) extraction that every
// emit site would otherwise copy verbatim.
//
// Callers MUST gate on `AccessObserver::IsArmed()` BEFORE calling this, so the
// disarmed hot path never computes the Document nor enters here:
//
//   if (camoufox::AccessObserver::IsArmed())
//     camoufox::RecordSurfaceFromDocument(doc, camoufox::SurfaceId::Navigator);

#include "AccessObserver.hpp"
#include "mozilla/dom/Document.h"
#include "mozilla/OriginAttributes.h"
#include "nsIPrincipal.h"
#include "nsString.h"
#include "prtime.h"
#include <string>

namespace camoufox {

// aDoc may be null (callers often pass `win ? win->GetExtantDoc() : nullptr`).
inline void RecordSurfaceFromDocument(mozilla::dom::Document* aDoc,
                                      SurfaceId aSurface) {
  if (!aDoc) return;
  nsAutoCString baseDomain;
  uint32_t uctx = 0;
  if (nsIPrincipal* p = aDoc->NodePrincipal()) {
    p->GetBaseDomain(baseDomain);
    uctx = p->OriginAttributesRef().mUserContextId;
  }
  AccessObserver::Record(uctx, std::string(baseDomain.get()), aSurface,
                         static_cast<uint64_t>(PR_Now() / 1000));
}

}  // namespace camoufox

#endif  // CAMOUFOX_ACCESS_OBSERVER_DOM_HPP
