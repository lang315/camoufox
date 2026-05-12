# Fix Plan: CI build vỡ sau commit goapi

## Context

Workflow `Build and Release` fail 4/4 run gần nhất. Phân tích:

- **Commit `724ef4b` (goapi parity) KHÔNG gây fail** — CI build C++ Firefox source, không chạm `goapi/` hoặc `plan/`. Run `e1b227c` (cùng đường) cũng fail cùng pattern.
- **Lỗi gốc:** `bash ../scripts/copy-additions.sh 146.0.1 beta.25` fail tại dòng đầu:
  ```
  cp: cannot create regular file 'services/settings/dumps/main/search-config.json': No such file or directory
  ```
- **Version drift:** `upstream.sh` local pin `version=146.0.1`, upstream daijro/camoufox pin `version=150.0.2`. Fork 4 minor đằng sau.
- **Upstream cũng vỡ:** daijro CI 3/3 run gần nhất cũng `failure` — bug rộng hơn fork.
- **Patch ordering check là red-herring:** `webrtc-ip-spoofing.patch` < `webrtc-ip-spoofing2.patch` theo sort (ASCII `.`=46 < `2`=50). Echo trong log chỉ là script display, không trigger error.

Chiến lược: ship 3 path song song, độc lập với nhau.

## Path 3 — Skip CI cho goapi commit (zero blast radius, ship trước)

**Goal:** commit Go-only không trigger workflow build C++ vỡ.

**File sửa:** `.github/workflows/<build-and-release>.yml` (đọc tên file thật trong `.github/workflows/`).

**Change:** thêm `paths-ignore` ở `on.push`/`on.pull_request`:
```yaml
on:
  push:
    paths-ignore:
      - 'goapi/**'
      - 'plan/**'
      - 'README.md'
      - 'CONTRIBUTING.md'
  pull_request:
    paths-ignore:
      - 'goapi/**'
      - 'plan/**'
```

**Optional:** thêm workflow mới `.github/workflows/goapi-test.yml` chạy `go vet ./... && go build ./... && go test ./...` cho `paths: [goapi/**]` — green CI cho goapi commit độc lập.

**Verify:**
```bash
# Sau merge: push goapi-only change, confirm chỉ goapi workflow chạy
git commit -m "test goapi-only" --allow-empty
git push
gh run list --limit 3   # build-and-release skip, goapi-test run
```

**Effort:** 10 phút.

---

## Path 2 — Fix search-config path tại Firefox 146 (low blast radius)

**Goal:** giữ pin `version=146.0.1`, sửa `scripts/copy-additions.sh` cho khớp Firefox 146 source layout.

### Investigation trước khi fix

1. **Fetch Firefox 146 source tarball** để xem layout thực tế:
   ```bash
   curl -L -o /tmp/ff146.tar.xz \
     "https://archive.mozilla.org/pub/firefox/releases/146.0.1/source/firefox-146.0.1.source.tar.xz"
   tar -tJf /tmp/ff146.tar.xz | grep 'services/settings/dumps/main' | head
   tar -tJf /tmp/ff146.tar.xz | grep -i 'search-config' | head
   ```
   Xác định: directory có tồn tại không, file có đổi tên thành `search-config-v2.json` không.

2. **Đối chiếu Mozilla bug tracker:**
   - Bug 1850072 (search-config-v2 deployment) — Firefox migration timeline
   - Tìm bug nào REMOVED file `search-config.json` (suspect Firefox 134-140 range)

3. **Check Camoufox additions:**
   ```bash
   grep -rn 'search-config' additions/ patches/ settings/
   ```
   Xem Camoufox đăng ký RemoteSettings consumer nào — quyết định cần stub file gì.

### Fix dựa kết quả investigation

**Case A** — file đã đổi tên `search-config-v2.json`:
```bash
# scripts/copy-additions.sh
run 'mkdir -p services/settings/dumps/main'
run 'cp -v ../assets/search-config.json services/settings/dumps/main/search-config-v2.json'
```
Cập nhật `assets/search-config.json` content nếu schema v2 khác (verify v2 schema tại Mozilla source `toolkit/components/search/SearchService.sys.mjs`).

**Case B** — directory bị xóa hẳn, file không còn cần thiết:
```bash
# scripts/copy-additions.sh
if [ -d "services/settings/dumps/main" ]; then
  run 'cp -v ../assets/search-config.json services/settings/dumps/main/search-config.json'
else
  echo "search-config dump path absent in this Firefox version, skipping"
fi
```

**Case C** — Mozilla move sang `services/settings/dumps/<other-domain>/`:
Adjust target path theo đúng location mới.

### Verify

```bash
# Local repro
make fetch   # Hoặc tự download tarball
cd camoufox-146.0.1-beta.25 && bash ../scripts/copy-additions.sh 146.0.1 beta.25
echo $?   # Phải 0
```

Sau đó push, gh run list, xác nhận `make set-target` pass.

**Effort:** 1-2h (đa số là investigation Mozilla source).

---

## Path 1 — Bump local to upstream `version=150.0.2` (high blast radius)

**Goal:** sync fork lên Firefox 150.0.2 ngang upstream daijro.

### Risk surface

- **Canvas/WebRTC patches** của user trong commit `e1b227c` (`Add Go native client, canvas/WebRTC patches, modernize CI`) áp dụng cho Firefox 146 — có thể conflict khi rebase qua 4 phiên bản Mozilla.
- **Upstream daijro CI cũng đang vỡ** trên 150.0.2 — bump xong vẫn fail, cần fix song song bug khác.
- **`additions/`, `patches/`, `settings/`** local có thể đã divergent với upstream (Phase 1 ngoài upstream).

### Steps

1. **Backup local diverged work:**
   ```bash
   git checkout -b backup-pre-bump
   git push origin backup-pre-bump
   git checkout main
   ```

2. **Identify divergent files vs upstream daijro:**
   ```bash
   git remote add upstream https://github.com/daijro/camoufox.git
   git fetch upstream main
   git diff --stat upstream/main..HEAD -- additions/ patches/ settings/ scripts/
   ```
   Lưu danh sách file user đã custom — sẽ phải re-apply sau merge.

3. **Cherry-pick upstream Firefox 150 sync:**
   ```bash
   # Tìm commit upstream bump version
   git log upstream/main --oneline -- upstream.sh | head -5
   # Cherry-pick hoặc merge cả branch
   git merge upstream/main --no-commit
   ```
   Resolve conflict theo logic:
   - `upstream.sh` → lấy 150.0.2
   - `patches/canvas-*` / `patches/webrtc-*` → giữ local nếu user custom; otherwise upstream
   - `additions/` → ưu tiên upstream cho file Mozilla-tracking (Juggler protocol, branding); giữ local cho Camoufox-only patches
   - `goapi/`, `plan/` → giữ nguyên local (upstream không có)

4. **Re-apply user canvas/WebRTC patches lên Firefox 150:**
   - Đọc commit `e1b227c` xem custom changes
   - Apply qua `git apply` hoặc manual port
   - Test build local nếu có máy mạnh, hoặc dựa CI

5. **Verify CI:** push branch test, gh run list. Nếu vẫn fail Path 2 bug → fix song song.

### Caveat

- Build Camoufox/Firefox cần Linux + ~50GB disk + nhiều giờ compile. Nếu không có infra local, dựa CI.
- Mozilla migrate API/architecture giữa versions — patches có thể cần port không trivial (Juggler protocol đôi khi đổi).

**Effort:** 1-3 ngày tùy mức conflict + custom patches.

---

## Order of execution (recommend)

1. **Path 3 ngay** (10 phút) — unblock goapi commit, không trigger CI vỡ.
2. **Path 2 song song** (1-2h) — fix root cause cho Firefox 146 pin, nếu user muốn ở lại 146 ổn định trong khi upstream chưa fix 150.
3. **Path 1 tùy chọn** (1-3 ngày) — chỉ làm khi:
   - User muốn upgrade lên 150.0.2 để hưởng patches mới upstream
   - Hoặc upstream daijro tự fix 150 build, lúc đó merge sạch
   - Path 2 không apply được (Mozilla deprecated config infra hoàn toàn)

## Verification cuối plan

```bash
# Path 3 acceptance
git commit -m "trivial goapi tweak" --allow-empty
git push
gh run list --limit 3
# Expected: build-and-release SKIP cho goapi-only push, goapi-test PASS

# Path 2 acceptance
make fetch
cd camoufox-146.0.1-beta.25 && bash ../scripts/copy-additions.sh 146.0.1 beta.25
# Expected: exit 0
gh run list --limit 1
# Expected: Build and Release pass past 'set-target' step

# Path 1 acceptance (long-term)
cat upstream.sh   # version=150.0.2
gh run list --limit 1   # Full build green
```

## Out-of-scope

- KHÔNG sửa patch sort check (`webrtc-ip-spoofing`) — không phải bug.
- KHÔNG rebuild full Camoufox local nếu không có Linux runner — dựa CI.
- KHÔNG nâng FF version vượt upstream (150.0.2) — đợi daijro release.
