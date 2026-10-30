// Probe (not shipped): does a one-family DirectWrite collection group a family
// like the full bundled collection does? Usage: fam.exe <fonts dir>
#define NOMINMAX
#include <windows.h>
#include <dwrite_3.h>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <algorithm>
#include <map>
#include <set>
#include <exception>
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

struct Face { string ps; int weight, stretch, style; string path; unsigned idx = 0;
  auto key() const { return std::tie(ps, path, idx, weight, stretch, style); }
  bool operator<(const Face& o) const { return key() < o.key(); }
  bool operator==(const Face& o) const { return key() == o.key(); } };

static string PsName(IDWriteFont* f) {
  Ptr<IDWriteLocalizedStrings> s; BOOL ex = FALSE;
  if (FAILED(f->GetInformationalStrings(DWRITE_INFORMATIONAL_STRING_POSTSCRIPT_NAME, &s, &ex)) || !ex || !s) return "(none)";
  auto v = LocalizedNames(s.p);
  return v.empty() ? "(none)" : v[0];
}

// Non-simulated faces of a family, as the shared list records them, with the
// file path and index-in-file of each face's first file.
static vector<Face> Faces(IDWriteFontFamily* fam, set<wstring>* files) {
  vector<Face> out;
  for (UINT32 j = 0; j < fam->GetFontCount(); j++) {
    Ptr<IDWriteFont> f; if (FAILED(fam->GetFont(j, &f))) continue;
    if (f->GetSimulations() != DWRITE_FONT_SIMULATIONS_NONE) continue;
    Face fc{PsName(f.p), (int)f->GetWeight(), (int)f->GetStretch(), (int)f->GetStyle(), "", 0};
    Ptr<IDWriteFontFace> face;
    if (SUCCEEDED(f->CreateFontFace(&face))) {
      fc.idx = face->GetIndex();
      UINT32 n = 0; face->GetFiles(&n, nullptr);
      vector<IDWriteFontFile*> ff(n);
      if (SUCCEEDED(face->GetFiles(&n, ff.data()))) {
        for (UINT32 q = 0; q < n; q++) {
          auto* x = ff[q];
          Ptr<IDWriteFontFileLoader> ld; Ptr<IDWriteLocalFontFileLoader> ll;
          const void* k = nullptr; UINT32 ks = 0;
          if (SUCCEEDED(x->GetLoader(&ld)) && SUCCEEDED(ld->QueryInterface(__uuidof(IDWriteLocalFontFileLoader), (void**)&ll)) &&
              SUCCEEDED(x->GetReferenceKey(&k, &ks))) {
            UINT32 len = 0;
            if (SUCCEEDED(ll->GetFilePathLengthFromKey(k, ks, &len))) {
              wstring path(len + 1, 0);
              if (SUCCEEDED(ll->GetFilePathFromKey(k, ks, path.data(), len + 1))) {
                path.resize(len);
                if (files) files->insert(path);
                if (q == 0) { for (auto& c : path) c = towlower(c); fc.path = U8(path); }
              }
            }
          }
          x->Release();
        }
      }
    }
    out.push_back(fc);
  }
  return out;
}


using Key = std::tuple<string, string, unsigned, int, int, int>;
struct Raw { Key key; string axes; };
// Every font of the family in GetFont order (simulations included), with the
// variation axis values of its face.
static vector<Raw> RawFaces(IDWriteFontFamily* fam) {
  vector<Raw> out;
  for (UINT32 j = 0; j < fam->GetFontCount(); j++) {
    Raw r{Key{"(fail)", "", 0, 0, 0, 0}, ""};
    Ptr<IDWriteFont> f;
    if (SUCCEEDED(fam->GetFont(j, &f))) {
      Face fc{PsName(f.p), (int)f->GetWeight(), (int)f->GetStretch(), (int)f->GetStyle(), "", 0};
      Ptr<IDWriteFontFace> face;
      if (SUCCEEDED(f->CreateFontFace(&face))) {
        fc.idx = face->GetIndex();
        UINT32 n = 0; face->GetFiles(&n, nullptr);
        vector<IDWriteFontFile*> ff(n);
        if (SUCCEEDED(face->GetFiles(&n, ff.data()))) {
          for (UINT32 q = 0; q < n; q++) {
            auto* x = ff[q];
            Ptr<IDWriteFontFileLoader> ld; Ptr<IDWriteLocalFontFileLoader> ll;
            const void* k = nullptr; UINT32 ks = 0;
            if (q == 0 && SUCCEEDED(x->GetLoader(&ld)) && SUCCEEDED(ld->QueryInterface(__uuidof(IDWriteLocalFontFileLoader), (void**)&ll)) &&
                SUCCEEDED(x->GetReferenceKey(&k, &ks))) {
              UINT32 len = 0;
              if (SUCCEEDED(ll->GetFilePathLengthFromKey(k, ks, &len))) {
                wstring path(len + 1, 0);
                if (SUCCEEDED(ll->GetFilePathFromKey(k, ks, path.data(), len + 1))) { path.resize(len); for (auto& c : path) c = towlower(c); fc.path = U8(path); }
              }
            }
            x->Release();
          }
        }
        Ptr<IDWriteFontFace5> f5;
        if (SUCCEEDED(face->QueryInterface(__uuidof(IDWriteFontFace5), (void**)&f5.p))) {
          UINT32 ac = f5->GetFontAxisValueCount();
          vector<DWRITE_FONT_AXIS_VALUE> av(ac);
          if (ac && SUCCEEDED(f5->GetFontAxisValues(av.data(), ac))) {
            for (auto& a : av) { char b[64]; snprintf(b, sizeof b, "%08x=%g;", (unsigned)a.axisTag, a.value); r.axes += b; }
          }
        }
      }
      r.key = fc.key();
    }
    out.push_back(r);
  }
  return out;
}

// ---- dump mode (#345): the live FontIsSharedFace comparison, field by field ----
static string EnglishOrFirst(IDWriteLocalizedStrings* s) {
  UINT32 idx = 0; BOOL ex = FALSE;
  if (FAILED(s->FindLocaleName(L"en-us", &idx, &ex)) || !ex) idx = 0;
  UINT32 len = 0; s->GetStringLength(idx, &len);
  wstring w(len + 1, 0); s->GetString(idx, w.data(), len + 1); w.resize(len);
  return U8(w);
}
// gfxDWriteFontList.cpp GetDirectWriteFaceName(PSNAME_ID): English locale, else the first string.
static string PsEnglish(IDWriteFont* f) {
  Ptr<IDWriteLocalizedStrings> s; BOOL ex = FALSE;
  if (FAILED(f->GetInformationalStrings(DWRITE_INFORMATIONAL_STRING_POSTSCRIPT_NAME, &s, &ex)) || !ex || !s) return "(none)";
  return EnglishOrFirst(s.p);
}
struct Live { string psFirst, psEn, path; unsigned idx = 0; int w = 0, st = 0, sl = 0; int sim = 0; string axes; bool ok = false; };
static Live ReadLive(IDWriteFont* f) {
  Live l; l.psFirst = PsName(f); l.psEn = PsEnglish(f);
  l.w = f->GetWeight(); l.st = f->GetStretch(); l.sl = f->GetStyle(); l.sim = (int)f->GetSimulations();
  Ptr<IDWriteFontFace> face;
  if (FAILED(f->CreateFontFace(&face))) return l;
  l.idx = face->GetIndex();
  UINT32 n = 0; face->GetFiles(&n, nullptr);
  vector<IDWriteFontFile*> ff(n);
  if (n && SUCCEEDED(face->GetFiles(&n, ff.data()))) {
    for (UINT32 q = 0; q < n; q++) {
      auto* x = ff[q];
      Ptr<IDWriteFontFileLoader> ld; Ptr<IDWriteLocalFontFileLoader> ll; const void* k = nullptr; UINT32 ks = 0;
      if (q == 0 && SUCCEEDED(x->GetLoader(&ld)) && SUCCEEDED(ld->QueryInterface(__uuidof(IDWriteLocalFontFileLoader), (void**)&ll)) && SUCCEEDED(x->GetReferenceKey(&k, &ks))) {
        UINT32 len = 0;
        if (SUCCEEDED(ll->GetFilePathLengthFromKey(k, ks, &len))) { wstring pth(len + 1, 0); if (SUCCEEDED(ll->GetFilePathFromKey(k, ks, pth.data(), len + 1))) { pth.resize(len); l.path = U8(pth); l.ok = true; } }
      }
      x->Release();
    }
  }
  Ptr<IDWriteFontFace5> f5;
  if (SUCCEEDED(face->QueryInterface(__uuidof(IDWriteFontFace5), (void**)&f5.p))) {
    UINT32 ac = f5->GetFontAxisValueCount(); vector<DWRITE_FONT_AXIS_VALUE> av(ac);
    if (ac && SUCCEEDED(f5->GetFontAxisValues(av.data(), ac))) for (auto& a : av) { char b[64]; snprintf(b, sizeof b, "%c%c%c%c=%g;", (char)(a.axisTag & 255), (char)((a.axisTag >> 8) & 255), (char)((a.axisTag >> 16) & 255), (char)(a.axisTag >> 24), a.value); l.axes += b; }
    l.axes += f5->HasVariations() ? "VAR" : "static";
  }
  return l;
}
// FontIsSharedFace, reporting the first field that differs (psName from the chosen source).
static string Why(const Live& shared, const Live& f, bool english) {
  if (f.sim != 0) return "simulated";
  if (!f.ok) return "nofile";
  if (f.idx != shared.idx) return "fileindex";
  if (f.path != shared.path) return "path";
  if (f.w != shared.w) return "weight";
  if (f.st != shared.st) return "width";
  if (f.sl != shared.sl) return "slant";
  if ((english ? f.psEn : f.psFirst) != (english ? shared.psEn : shared.psFirst)) return "psname";
  return "";
}
static void Dump(IDWriteFontCollection* full, const set<string>& want) {
  for (UINT32 i = 0; i < full->GetFontFamilyCount(); i++) {
    Ptr<IDWriteFontFamily> fam; if (FAILED(full->GetFontFamily(i, &fam))) continue;
    Ptr<IDWriteLocalizedStrings> ns; if (FAILED(fam->GetFamilyNames(&ns))) continue;
    auto names = LocalizedNames(ns.p); bool hit = false;
    for (auto n : names) { for (auto& c : n) c = (char)tolower((unsigned char)c); if (want.count(n)) hit = true; }
    if (!hit) continue;
    set<wstring> files; (void)Faces(fam.p, &files);
    vector<wstring> fv(files.begin(), files.end());
    Ptr<IDWriteFontCollection> sm; sm.p = Build(fv);
    printf("DUMPFAM full[%u] %s files=%zu small_families=%u\n", i, names[0].c_str(), fv.size(), sm ? sm->GetFontFamilyCount() : 0);
    for (UINT32 j = 0; j < fam->GetFontCount(); j++) {
      Ptr<IDWriteFont> f; if (FAILED(fam->GetFont(j, &f))) continue;
      Live sh = ReadLive(f.p);
      printf("DUMPFULL %u/%u ps_first=%s ps_en=%s w=%d st=%d sl=%d sim=%d file=%s fidx=%u %s\n", i, j, sh.psFirst.c_str(), sh.psEn.c_str(), sh.w, sh.st, sh.sl, sh.sim, sh.path.c_str(), sh.idx, sh.axes.c_str());
      if (sh.sim != 0 || !sm) continue;
      // live lookup, once per name source
      for (int english = 0; english < 2; english++) {
        int holderFam = -1, holderCount = 0; string firstWhy;
        for (UINT32 k = 0; k < sm->GetFontFamilyCount(); k++) {
          Ptr<IDWriteFontFamily> sf; sm->GetFontFamily(k, &sf);
          for (UINT32 q = 0; q < sf->GetFontCount(); q++) {
            Ptr<IDWriteFont> g; if (FAILED(sf->GetFont(q, &g))) continue;
            if (Why(sh, ReadLive(g.p), english).empty()) { if (holderFam < 0) holderFam = (int)k; holderCount++; }
          }
        }
        string verdict;
        if (sm->GetFontFamilyCount() == 1) holderFam = 0;
        if (holderFam < 0) verdict = "NO_HOLDER";
        else {
          Ptr<IDWriteFontFamily> hf; sm->GetFontFamily((UINT32)holderFam, &hf);
          Ptr<IDWriteFont> g;
          if (j >= hf->GetFontCount() || FAILED(hf->GetFont(j, &g))) verdict = "INDEX_OUT_OF_RANGE";
          else { Live lg = ReadLive(g.p); string w = Why(sh, lg, english != 0); verdict = w.empty() ? "HIT" : "MISS_" + w + " small_ps_first=" + lg.psFirst + " small_ps_en=" + lg.psEn + " small_w=" + std::to_string(lg.w) + " small_fidx=" + std::to_string(lg.idx) + " " + lg.axes; }
        }
        printf("DUMPLIVE %u/%u name_source=%s holders_found=%d holder_family=%d verdict=%s\n", i, j, english ? "english-or-first" : "first", holderCount, holderFam, verdict.c_str());
      }
    }
  }
}
static const char* gStage = "start";
int run(int argc, wchar_t** argv);
int wmain(int argc, wchar_t** argv) {
  setvbuf(stdout, nullptr, _IONBF, 0);
  SetUnhandledExceptionFilter([](EXCEPTION_POINTERS* e) -> LONG { HMODULE m = nullptr; char mn[260] = "?"; GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)e->ExceptionRecord->ExceptionAddress, &m); if (m) GetModuleFileNameA(m, mn, 260); printf("SEH %08lx at %p module %s +%llx stage %s\n", e->ExceptionRecord->ExceptionCode, e->ExceptionRecord->ExceptionAddress, mn, (unsigned long long)((char*)e->ExceptionRecord->ExceptionAddress - (char*)m), gStage); return EXCEPTION_EXECUTE_HANDLER; });
  try { return run(argc, argv); }
  catch (const std::exception& e) { printf("EXCEPTION %s\n", e.what()); return 3; }
  catch (...) { printf("EXCEPTION unknown\n"); return 3; }
}
int run(int argc, wchar_t** argv) {
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
  if (argc > 2) {  // dump mode: fam.exe <fonts dir> <family,family,...>
    set<string> want; string a = U8(argv[2]); size_t p0 = 0;
    for (;;) { size_t c = a.find(',', p0); want.insert(a.substr(p0, c == string::npos ? c : c - p0)); if (c == string::npos) break; p0 = c + 1; }
    Dump(full.p, want);
    return 0;
  }
  UINT32 nfam = full->GetFontFamilyCount();
  printf("FILES %zu FAMILIES %u FULL_BUILD_SECONDS %.2f\n", all.size(), nfam, tfull);
  // S3b lookup: in the one-family collection, ignore family names and find each
  // face of family i by PostScript name across ALL families of that collection.
  // Today's lookup: family i by index in the full collection, then the face by
  // PostScript name. Both must give the same face (PS name, weight, stretch, style).
  int single = 0, multi = 0, miss = 0, ambiguous = 0, mismatch = 0, found = 0, dupInFull = 0, buildFail = 0;
  size_t faceCount = 0, maxfiles = 0; int orderOk = 0, orderBadFam = 0, axisCompared = 0, varFam = 0, varFaces = 0; std::map<std::tuple<string, string, unsigned, int, int, int>, int> globalKey; double tsmall = 0;
  std::vector<std::tuple<double, string, size_t>> times;
  for (UINT32 i = 0; i < nfam; i++) {
    Ptr<IDWriteFontFamily> fam; if (FAILED(full->GetFontFamily(i, &fam))) continue;
    Ptr<IDWriteLocalizedStrings> ns; if (FAILED(fam->GetFamilyNames(&ns))) continue;
    auto names = LocalizedNames(ns.p); if (names.empty()) names.push_back("(noname)");
    printf("ENTER %u %s\n", i, names[0].c_str()); gStage = "faces-of-full-family"; set<wstring> files; auto ref = Faces(fam.p, &files);
    if (ref.empty()) continue;
    printf("FAM %u %s faces=%zu\n", i, names[0].c_str(), ref.size());
    faceCount += ref.size();
    vector<wstring> fv(files.begin(), files.end());
    (fv.size() == 1 ? single : multi)++;
    if (fv.size() > maxfiles) maxfiles = fv.size();
    auto s0 = std::chrono::steady_clock::now();
    gStage = "build-small"; Ptr<IDWriteFontCollection> sm; sm.p = Build(fv); gStage = "after-build";
    double dt = std::chrono::duration<double>(std::chrono::steady_clock::now() - s0).count();
    tsmall += dt; times.push_back({dt, names[0], fv.size()});
    if (!sm) { buildFail++; printf("BUILD_FAIL family[%u] %s\n", i, names[0].c_str()); continue; }
    {
      gStage = "order-check";
      auto rawF = RawFaces(fam.p);
      vector<vector<Raw>> rawS; std::map<Key, std::set<size_t>> holders;
      for (UINT32 k = 0; k < sm->GetFontFamilyCount(); k++) {
        Ptr<IDWriteFontFamily> sf; if (FAILED(sm->GetFontFamily(k, &sf))) { rawS.push_back({}); continue; }
        rawS.push_back(RawFaces(sf.p));
        for (auto& r : rawS.back()) holders[r.key].insert(rawS.size() - 1);
      }
      bool bad = false, var = false;
      for (size_t j = 0; j < rawF.size(); j++) {
        if (!rawF[j].axes.empty()) var = true;
        auto h = holders.find(rawF[j].key);
        if (h == holders.end() || h->second.size() != 1) { bad = true; printf("ORDER_NOHOLDER family[%u] %s idx=%zu holders=%zu\n", i, names[0].c_str(), j, h == holders.end() ? 0 : h->second.size()); continue; }
        auto& sv = rawS[*h->second.begin()];
        if (j >= sv.size() || !(sv[j].key == rawF[j].key)) { bad = true; printf("ORDER_DIFF family[%u] %s idx=%zu\n", i, names[0].c_str(), j); }
        else if (sv[j].axes != rawF[j].axes) { bad = true; printf("AXIS_DIFF family[%u] %s idx=%zu full=%s small=%s\n", i, names[0].c_str(), j, rawF[j].axes.c_str(), sv[j].axes.c_str()); }
        else { orderOk++; if (!rawF[j].axes.empty()) axisCompared++; }
      }
      if (bad) orderBadFam++;
      if (var) { varFam++; varFaces += rawF.size(); }
    }
    gStage = "faces-of-small"; std::map<std::tuple<string, string, unsigned, int, int, int>, int> inSmall;
    for (UINT32 k = 0; k < sm->GetFontFamilyCount(); k++) {
      Ptr<IDWriteFontFamily> sf; if (FAILED(sm->GetFontFamily(k, &sf))) continue;
      for (auto& f : Faces(sf.p, nullptr)) inSmall[f.key()]++;
    }
    std::set<std::tuple<string, string, unsigned, int, int, int>> seen;
    for (auto& f : ref) {
      auto kk = f.key();
      globalKey[kk]++;
      if (!seen.insert(kk).second) { dupInFull++; printf("DUP_KEY_IN_FULL family[%u] %s: ps=%s file=%s idx=%u w=%d st=%d sl=%d\n", i, names[0].c_str(), f.ps.c_str(), f.path.c_str(), f.idx, f.weight, f.stretch, f.style); continue; }
      int n = inSmall.count(kk) ? inSmall[kk] : 0;
      if (n == 0) { miss++; printf("MISS family[%u] %s: ps=%s file=%s idx=%u\n", i, names[0].c_str(), f.ps.c_str(), f.path.c_str(), f.idx); }
      else if (n > 1) { ambiguous++; printf("AMBIGUOUS family[%u] %s: ps=%s matches %d\n", i, names[0].c_str(), f.ps.c_str(), n); }
      else found++;
    }
  }
  int dupGlobal = 0; for (auto& kv : globalKey) if (kv.second > 1) dupGlobal++;
  printf("GLOBAL_DUP_KEYS_ACROSS_FAMILIES %d\n", dupGlobal);
  std::sort(times.begin(), times.end(), [](auto& a, auto& b) { return std::get<0>(a) > std::get<0>(b); });
  for (size_t k = 0; k < times.size() && k < 5; k++) printf("SLOWEST %.3fs %s (%zu files)\n", std::get<0>(times[k]), std::get<1>(times[k]).c_str(), std::get<2>(times[k]));
  printf("ORDER faces_ok=%d families_with_order_or_axis_diff=%d axis_values_compared=%d variable_families=%d variable_family_faces=%d\n", orderOk, orderBadFam, axisCompared, varFam, varFaces);
  printf("SUMMARY families=%u faces=%zu found_identical=%d miss=%d ambiguous=%d mismatch=%d dup_key_in_full_family=%d build_fail=%d single_file_families=%d multi_file_families=%d max_files_in_a_family=%zu small_total_seconds=%.2f\n",
         nfam, faceCount, found, miss, ambiguous, mismatch, dupInFull, buildFail, single, multi, maxfiles, tsmall);
  return 0;
}
