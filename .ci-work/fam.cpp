// Probe (not shipped): does a one-family DirectWrite collection group a family
// like the full bundled collection does? Usage: fam.exe <fonts dir>
#define NOMINMAX
#include <windows.h>
#include <dwrite.h>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <algorithm>
#include <map>
#include <set>
#include <string>
#include <tuple>
#include <vector>

using std::set;
using std::string;
using std::vector;
using std::wstring;

template <class T> struct Ptr {
  T* p = nullptr;
  ~Ptr() { if (p) p->Release(); }
  T** operator&() { return &p; }
  T* operator->() const { return p; }
  explicit operator bool() const { return p != nullptr; }
};

static string U8(const wstring& w) {
  if (w.empty()) return "";
  int n = WideCharToMultiByte(CP_UTF8, 0, w.data(), (int)w.size(), nullptr, 0, nullptr, nullptr);
  string s(n, 0);
  WideCharToMultiByte(CP_UTF8, 0, w.data(), (int)w.size(), s.data(), n, nullptr, nullptr);
  return s;
}

class Enumerator : public IDWriteFontFileEnumerator {
 public:
  Enumerator(IDWriteFactory* f, const vector<wstring>& v) : f_(f), v_(v) {}
  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID r, void** o) override {
    if (r == __uuidof(IUnknown) || r == __uuidof(IDWriteFontFileEnumerator)) { *o = this; AddRef(); return S_OK; }
    *o = nullptr; return E_NOINTERFACE;
  }
  ULONG STDMETHODCALLTYPE AddRef() override { return ++rc_; }
  ULONG STDMETHODCALLTYPE Release() override { ULONG n = --rc_; if (!n) delete this; return n; }
  HRESULT STDMETHODCALLTYPE MoveNext(BOOL* has) override { *has = (++i_ < (int)v_.size()); return S_OK; }
  HRESULT STDMETHODCALLTYPE GetCurrentFontFile(IDWriteFontFile** o) override {
    return f_->CreateFontFileReference(v_[i_].c_str(), nullptr, o);
  }
 private:
  IDWriteFactory* f_; const vector<wstring>& v_; int i_ = -1; std::atomic<ULONG> rc_{1};
};

class Loader : public IDWriteFontCollectionLoader {
 public:
  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID r, void** o) override {
    if (r == __uuidof(IUnknown) || r == __uuidof(IDWriteFontCollectionLoader)) { *o = this; AddRef(); return S_OK; }
    *o = nullptr; return E_NOINTERFACE;
  }
  ULONG STDMETHODCALLTYPE AddRef() override { return ++rc_; }
  ULONG STDMETHODCALLTYPE Release() override { ULONG n = --rc_; if (!n) delete this; return n; }
  HRESULT STDMETHODCALLTYPE CreateEnumeratorFromKey(IDWriteFactory* f, const void* key, UINT32, IDWriteFontFileEnumerator** o) override {
    *o = new Enumerator(f, **(const vector<wstring>* const*)key);
    return S_OK;
  }
 private:
  std::atomic<ULONG> rc_{1};
};

static IDWriteFactory* gF;

static IDWriteFontCollection* Build(const vector<wstring>& files) {
  Ptr<Loader> ld; ld.p = new Loader();
  if (FAILED(gF->RegisterFontCollectionLoader(ld.p))) return nullptr;
  const vector<wstring>* key = &files;
  IDWriteFontCollection* c = nullptr;
  HRESULT hr = gF->CreateCustomFontCollection(ld.p, &key, sizeof(key), &c);
  gF->UnregisterFontCollectionLoader(ld.p);
  return FAILED(hr) ? nullptr : c;
}

static vector<string> LocalizedNames(IDWriteLocalizedStrings* s) {
  vector<string> out;
  for (UINT32 i = 0; i < s->GetCount(); i++) {
    UINT32 len = 0; s->GetStringLength(i, &len);
    wstring w(len + 1, 0); s->GetString(i, w.data(), len + 1); w.resize(len);
    out.push_back(U8(w));
  }
  return out;
}

struct Face { string ps; int weight, stretch, style; bool operator<(const Face& o) const {
  return std::tie(ps, weight, stretch, style) < std::tie(o.ps, o.weight, o.stretch, o.style); }
  bool operator==(const Face& o) const {
  return std::tie(ps, weight, stretch, style) == std::tie(o.ps, o.weight, o.stretch, o.style); } };

static string PsName(IDWriteFont* f) {
  Ptr<IDWriteLocalizedStrings> s; BOOL ex = FALSE;
  if (FAILED(f->GetInformationalStrings(DWRITE_INFORMATIONAL_STRING_POSTSCRIPT_NAME, &s, &ex)) || !ex || !s) return "(none)";
  auto v = LocalizedNames(s.p);
  return v.empty() ? "(none)" : v[0];
}

// Non-simulated faces of a family, as the shared list records them.
static vector<Face> Faces(IDWriteFontFamily* fam, set<wstring>* files) {
  vector<Face> out;
  for (UINT32 j = 0; j < fam->GetFontCount(); j++) {
    Ptr<IDWriteFont> f; if (FAILED(fam->GetFont(j, &f))) continue;
    if (f->GetSimulations() != DWRITE_FONT_SIMULATIONS_NONE) continue;
    out.push_back({PsName(f.p), (int)f->GetWeight(), (int)f->GetStretch(), (int)f->GetStyle()});
    if (files) {
      Ptr<IDWriteFontFace> face; if (FAILED(f->CreateFontFace(&face))) continue;
      UINT32 n = 0; face->GetFiles(&n, nullptr);
      vector<IDWriteFontFile*> ff(n);
      if (SUCCEEDED(face->GetFiles(&n, ff.data()))) {
        for (auto* x : ff) {
          Ptr<IDWriteFontFileLoader> ld; Ptr<IDWriteLocalFontFileLoader> ll;
          const void* k = nullptr; UINT32 ks = 0;
          if (SUCCEEDED(x->GetLoader(&ld)) && SUCCEEDED(ld->QueryInterface(__uuidof(IDWriteLocalFontFileLoader), (void**)&ll)) &&
              SUCCEEDED(x->GetReferenceKey(&k, &ks))) {
            UINT32 len = 0;
            if (SUCCEEDED(ll->GetFilePathLengthFromKey(k, ks, &len))) {
              wstring path(len + 1, 0);
              if (SUCCEEDED(ll->GetFilePathFromKey(k, ks, path.data(), len + 1))) { path.resize(len); files->insert(path); }
            }
          }
          x->Release();
        }
      }
    }
  }
  return out;
}

int wmain(int argc, wchar_t** argv) {
  if (argc < 2) { printf("usage: fam <fonts dir>\n"); return 2; }
  if (FAILED(DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory), (IUnknown**)&gF))) { printf("no factory\n"); return 2; }
  wstring dir = argv[1];
  vector<wstring> all;
  WIN32_FIND_DATAW fd; HANDLE h = FindFirstFileW((dir + L"\\*").c_str(), &fd);
  if (h == INVALID_HANDLE_VALUE) { printf("no dir\n"); return 2; }
  do { if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) all.push_back(dir + L"\\" + fd.cFileName); } while (FindNextFileW(h, &fd));
  FindClose(h);
  auto t0 = std::chrono::steady_clock::now();
  Ptr<IDWriteFontCollection> full; full.p = Build(all);
  double tfull = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
  if (!full) { printf("full collection failed\n"); return 2; }
  UINT32 nfam = full->GetFontFamilyCount();
  printf("FILES %zu FAMILIES %u FULL_BUILD_SECONDS %.2f\n", all.size(), nfam, tfull);
  // For every shared-list entry (family i, one of its localized names n), the
  // S3b lookup is: FindFamilyName(one-family collection, n), then match each
  // face of family i by PostScript name in the family found.
  // Today's lookup is the index in the full collection, else FindFamilyName(full, n).
  int fails = 0, failsToday = 0, entries = 0, single = 0, multi = 0, ambiguous = 0;
  size_t faceCount = 0; double tsmall = 0; size_t maxfiles = 0;
  std::vector<std::pair<double, string>> times;
  auto widen = [](const string& nm) {
    int wl = MultiByteToWideChar(CP_UTF8, 0, nm.c_str(), -1, nullptr, 0);
    wstring w(wl, 0); MultiByteToWideChar(CP_UTF8, 0, nm.c_str(), -1, w.data(), wl); return w;
  };
  for (UINT32 i = 0; i < nfam; i++) {
    Ptr<IDWriteFontFamily> fam; if (FAILED(full->GetFontFamily(i, &fam))) continue;
    Ptr<IDWriteLocalizedStrings> ns; if (FAILED(fam->GetFamilyNames(&ns))) continue;
    auto names = LocalizedNames(ns.p);
    set<wstring> files; auto ref = Faces(fam.p, &files);
    faceCount += ref.size();
    if (ref.empty()) continue;
    set<Face> want(ref.begin(), ref.end());
    vector<wstring> fv(files.begin(), files.end());
    (fv.size() == 1 ? single : multi)++;
    if (fv.size() > maxfiles) maxfiles = fv.size();
    auto s0 = std::chrono::steady_clock::now();
    Ptr<IDWriteFontCollection> sm; sm.p = Build(fv);
    double dt = std::chrono::duration<double>(std::chrono::steady_clock::now() - s0).count();
    tsmall += dt; times.push_back({dt, names[0] + " (" + std::to_string(fv.size()) + " files)"});
    for (auto& nm : names) {
      entries++;
      auto w = widen(nm);
      // S3b
      bool ok = false; string why;
      UINT32 idx = 0; BOOL ex = FALSE;
      if (!sm) why = "small collection failed";
      else if (FAILED(sm->FindFamilyName(w.c_str(), &idx, &ex)) || !ex) why = "name not found";
      else {
        Ptr<IDWriteFontFamily> sf; sm->GetFontFamily(idx, &sf);
        auto got = Faces(sf.p, nullptr); set<Face> g(got.begin(), got.end());
        ok = true;
        for (auto& x : want) if (!g.count(x)) { ok = false; why = "face " + x.ps + " not matched (found family has " + std::to_string(got.size()) + " faces, first " + (got.empty() ? string("-") : got[0].ps) + ")"; break; }
      }
      // Today
      bool todayOK = false;
      {
        UINT32 fi = 0; BOOL fe = FALSE;
        bool byIndex = (nm == names[0]);
        Ptr<IDWriteFontFamily> tf;
        if (byIndex) tf.p = fam.p, tf.p->AddRef();
        else if (SUCCEEDED(full->FindFamilyName(w.c_str(), &fi, &fe)) && fe) full->GetFontFamily(fi, &tf);
        if (tf) { auto got = Faces(tf.p, nullptr); set<Face> g(got.begin(), got.end()); todayOK = true; for (auto& x : want) if (!g.count(x)) { todayOK = false; break; } }
        if (!byIndex && fe && fi != i) ambiguous++;
      }
      if (!ok) { fails++; if (!todayOK) failsToday++;
        printf("S3B_FAIL family[%u] %s via '%s' (%zu files): %s; today's lookup %s\n", i, names[0].c_str(), nm.c_str(), fv.size(), why.c_str(), todayOK ? "FINDS the faces" : "ALSO fails"); }
    }
  }
  std::sort(times.begin(), times.end(), [](auto& a, auto& b) { return a.first > b.first; });
  for (size_t k = 0; k < times.size() && k < 5; k++) printf("SLOWEST %.3fs %s\n", times[k].first, times[k].second.c_str());
  printf("SUMMARY families=%u entries(family x localized name)=%d non_simulated_faces=%zu single_file_families=%d multi_file_families=%d names_resolving_to_another_family_in_full=%d s3b_fails=%d of_which_today_also_fails=%d small_total_seconds=%.2f max_files_in_a_family=%zu\n",
         nfam, entries, faceCount, single, multi, ambiguous, fails, failsToday, tsmall, maxfiles);
  return 0;
}
