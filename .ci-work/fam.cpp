// Probe (not shipped): does a one-family DirectWrite collection group a family
// like the full bundled collection does? Usage: fam.exe <fonts dir>
#define NOMINMAX
#include <windows.h>
#include <dwrite.h>
#include <atomic>
#include <chrono>
#include <cstdio>
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
          const void* k = nullptr; UINT32 ks = 0;
          if (SUCCEEDED(x->GetReferenceKey(&k, &ks))) files->insert(wstring((const wchar_t*)k, ks / sizeof(wchar_t) - ((ks >= 2 && ((const wchar_t*)k)[ks / 2 - 1] == 0) ? 1 : 0)));
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
  int diffs = 0, nameMiss = 0; size_t faceCount = 0; double tsmall = 0, tmax = 0; size_t maxfiles = 0;
  for (UINT32 i = 0; i < nfam; i++) {
    Ptr<IDWriteFontFamily> fam; if (FAILED(full->GetFontFamily(i, &fam))) continue;
    Ptr<IDWriteLocalizedStrings> ns; if (FAILED(fam->GetFamilyNames(&ns))) continue;
    auto names = LocalizedNames(ns.p);
    set<wstring> files; auto ref = Faces(fam.p, &files);
    faceCount += ref.size();
    if (ref.empty()) continue;
    vector<wstring> fv(files.begin(), files.end());
    if (fv.size() > maxfiles) maxfiles = fv.size();
    auto s0 = std::chrono::steady_clock::now();
    Ptr<IDWriteFontCollection> sm; sm.p = Build(fv);
    double dt = std::chrono::duration<double>(std::chrono::steady_clock::now() - s0).count();
    tsmall += dt; if (dt > tmax) tmax = dt;
    if (!sm) { printf("DIFF family[%u] %s: sm collection failed (%zu files)\n", i, names[0].c_str(), fv.size()); diffs++; continue; }
    for (auto& nm : names) {
      wstring w(nm.begin(), nm.end());
      int wl = MultiByteToWideChar(CP_UTF8, 0, nm.c_str(), -1, nullptr, 0);
      w.assign(wl, 0); MultiByteToWideChar(CP_UTF8, 0, nm.c_str(), -1, w.data(), wl);
      UINT32 idx = 0; BOOL ex = FALSE;
      if (FAILED(sm->FindFamilyName(w.c_str(), &idx, &ex)) || !ex) {
        printf("DIFF family[%u] %s: name '%s' not found in sm collection (%zu files)\n", i, names[0].c_str(), nm.c_str(), fv.size());
        nameMiss++; diffs++; continue;
      }
      Ptr<IDWriteFontFamily> sf; sm->GetFontFamily(idx, &sf);
      auto got = Faces(sf.p, nullptr);
      set<Face> a(ref.begin(), ref.end()), b(got.begin(), got.end());
      if (a != b || ref.size() != got.size()) {
        printf("DIFF family[%u] %s via '%s': full has %zu faces, sm has %zu (%zu files)\n", i, names[0].c_str(), nm.c_str(), ref.size(), got.size(), fv.size());
        for (auto& x : a) if (!b.count(x)) printf("   only in full : %s w=%d s=%d st=%d\n", x.ps.c_str(), x.weight, x.stretch, x.style);
        for (auto& x : b) if (!a.count(x)) printf("   only in sm: %s w=%d s=%d st=%d\n", x.ps.c_str(), x.weight, x.stretch, x.style);
        diffs++;
      }
    }
  }
  printf("SUMMARY families=%u non_simulated_faces=%zu diffs=%d name_misses=%d small_total_seconds=%.2f small_max_seconds=%.3f max_files_in_a_family=%zu\n",
         nfam, faceCount, diffs, nameMiss, tsmall, tmax, maxfiles);
  return 0;
}
