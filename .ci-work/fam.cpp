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
  // S3b lookup: in the one-family collection, ignore family names and find each
  // face of family i by PostScript name across ALL families of that collection.
  // Today's lookup: family i by index in the full collection, then the face by
  // PostScript name. Both must give the same face (PS name, weight, stretch, style).
  int single = 0, multi = 0, miss = 0, ambiguous = 0, mismatch = 0, found = 0, dupInFull = 0, buildFail = 0;
  size_t faceCount = 0, maxfiles = 0; double tsmall = 0;
  std::vector<std::tuple<double, string, size_t>> times;
  for (UINT32 i = 0; i < nfam; i++) {
    Ptr<IDWriteFontFamily> fam; if (FAILED(full->GetFontFamily(i, &fam))) continue;
    Ptr<IDWriteLocalizedStrings> ns; if (FAILED(fam->GetFamilyNames(&ns))) continue;
    auto names = LocalizedNames(ns.p);
    set<wstring> files; auto ref = Faces(fam.p, &files);
    if (ref.empty()) continue;
    faceCount += ref.size();
    vector<wstring> fv(files.begin(), files.end());
    (fv.size() == 1 ? single : multi)++;
    if (fv.size() > maxfiles) maxfiles = fv.size();
    auto s0 = std::chrono::steady_clock::now();
    Ptr<IDWriteFontCollection> sm; sm.p = Build(fv);
    double dt = std::chrono::duration<double>(std::chrono::steady_clock::now() - s0).count();
    tsmall += dt; times.push_back({dt, names[0], fv.size()});
    if (!sm) { buildFail++; printf("BUILD_FAIL family[%u] %s\n", i, names[0].c_str()); continue; }
    std::map<string, vector<Face>> byPs;
    for (UINT32 k = 0; k < sm->GetFontFamilyCount(); k++) {
      Ptr<IDWriteFontFamily> sf; if (FAILED(sm->GetFontFamily(k, &sf))) continue;
      for (auto& f : Faces(sf.p, nullptr)) byPs[f.ps].push_back(f);
    }
    std::map<string, int> inFull;
    for (auto& f : ref) inFull[f.ps]++;
    for (auto& f : ref) {
      if (inFull[f.ps] > 1) { dupInFull++; printf("DUP_IN_FULL family[%u] %s: PS name %s appears %d times in the full family\n", i, names[0].c_str(), f.ps.c_str(), inFull[f.ps]); continue; }
      auto it = byPs.find(f.ps);
      if (it == byPs.end()) { miss++; printf("MISS family[%u] %s: %s\n", i, names[0].c_str(), f.ps.c_str()); }
      else if (it->second.size() > 1) { ambiguous++; printf("AMBIGUOUS family[%u] %s: %s matches %zu faces\n", i, names[0].c_str(), f.ps.c_str(), it->second.size()); }
      else if (!(it->second[0] == f)) { mismatch++; printf("MISMATCH family[%u] %s: %s w=%d/%d s=%d/%d st=%d/%d\n", i, names[0].c_str(), f.ps.c_str(), f.weight, it->second[0].weight, f.stretch, it->second[0].stretch, f.style, it->second[0].style); }
      else found++;
    }
  }
  std::sort(times.begin(), times.end(), [](auto& a, auto& b) { return std::get<0>(a) > std::get<0>(b); });
  for (size_t k = 0; k < times.size() && k < 5; k++) printf("SLOWEST %.3fs %s (%zu files)\n", std::get<0>(times[k]), std::get<1>(times[k]).c_str(), std::get<2>(times[k]));
  printf("SUMMARY families=%u faces=%zu found_identical=%d miss=%d ambiguous_ps=%d mismatch=%d dup_ps_in_full_family=%d build_fail=%d single_file_families=%d multi_file_families=%d max_files_in_a_family=%zu small_total_seconds=%.2f\n",
         nfam, faceCount, found, miss, ambiguous, mismatch, dupInFull, buildFail, single, multi, maxfiles, tsmall);
  return 0;
}
