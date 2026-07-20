# 測試

讀者：執行完整驗證、效能檢查或套件檢查的使用者。

專案以 CTest 作為頂層 test runner。測試涵蓋 C++ unit/contract suites、generated
files、Python renderers、跨語言 Unicode 行為、Agent CLI framing、quick stress
workload，以及真實 PTY/TUI integration。一般編譯與安裝由
[`building.md`](building.md) 擁有；本文件擁有 verification profiles 與 expected
coverage。

## 本機必要條件

準備 [`building.md`](building.md) 列出的工具與 `VCPKG_ROOT`。測試會在 OS
temporary directories，以及所選 build tree 下的唯一 install test workspace，
建立可丟棄檔案與 Unix sockets。每個測試自行建立並清理工作目錄。

## 完整 Debug 測試

```sh
cmake --preset vcpkg-debug
cmake --build --preset vcpkg-debug
ctest --preset vcpkg-debug
```

PTY integration 會從 CMake target expressions 接收 executable paths，因此支援
任意 out-of-tree `-B` 目錄，不假設 source tree 內一定有名為 `build` 的目錄。

目前 CTest coverage 分為：

- core/model/history 與 native storage；
- atomic writer、單檔搬移、格式驗證與失敗時保留文件；
- socket lifecycle、framing、limits、timeout、分頁 canonical snapshot 與
  `whiteboardctl` atomic output 行為；
- coordinate boundary 與 signed-overflow cases；
- 嚴格 transactional CSV；
- C++ 與 Python 中固定的 Unicode width/combining 行為；
- 稀疏 card grid 的邊界、更新、去重、大範圍查詢與 quick stress；
- 100k-line/style text-edit performance contracts；
- 所有 Python renderer、materializer 與白板 verifier unit tests；
- 文件內本機 Markdown links；
- PTY creation、replacement、deletion、save 與 reload integration。

C++ 邏輯案例各自是 named CTest process。單獨執行範例：

```sh
./build/vcpkg-release/whiteboard_tests --case storage.atomic_writer
ctest --test-dir build/vcpkg-release -R '^whiteboard_storage_atomic_writer$'
```

Python unit tests 由 AST 列舉器註冊為每個 method 一個 CTest process；socket
與 PTY 黑箱案例也採相同粒度。`ctest --rerun-failed` 只重跑失敗單位。

## 將警告視為錯誤

```sh
cmake --preset vcpkg-release -DWHITEBOARD_WARNINGS_AS_ERRORS=ON
cmake --build --preset vcpkg-release
ctest --preset vcpkg-release
```

發行前請分別以 GCC 與 Clang 執行。

## Sanitizer

```sh
cmake --preset vcpkg-sanitize -DWHITEBOARD_WARNINGS_AS_ERRORS=ON
cmake --build --preset vcpkg-sanitize
ASAN_OPTIONS=detect_leaks=0 \
  ctest --preset vcpkg-sanitize -j1
```

此選項會使用 AddressSanitizer 與 GCC/Clang 的 signed-integer-overflow sanitizer
instrument 專案 C++。它刻意比完整 UBSan checks 更窄，因為 system Abseil
headers/libraries 必須維持相同的 Swiss-table ABI。一般、未被 trace 的 host 可
啟用 LeakSanitizer；範例將其關閉，是因為 LSan 無法在部分以 ptrace 為基礎的
CI/sandbox runner 初始化。

## 僅執行 Python

```sh
PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m unittest discover \
  -s tools/textart_notes/tests -t . -p 'test_*.py'
```

四個 PTY tests 位於獨立 integration package，涵蓋儲存重開、自動化驗證與開啟失敗時保留原檔，只有在明確啟用時才會執行。
其中 mind-map 案例從 `plan.md` 編譯七種原生格式與 outline renderer，依序執行
preview、materialize、Ctrl-S、final 與 attestation；也驗證未儲存修改與損壞文件
不能通過檢查。之後刪除來源、payload、renderer 與 run artifacts，只搬移
format-11 `.tiwb`，確認重開及再次儲存的 canonical snapshot、CardIds、Folder
references 與連邊一致，並逐 byte 比對再次儲存的 `.tiwb` 與原檔。

```sh
ctest --test-dir build/vcpkg-release -L skill --output-on-failure
ctest --test-dir build/vcpkg-release -R whiteboard_python_pty --output-on-failure
```

直接執行 integration package：

```sh
WHITEBOARD_TEXTART_INTEGRATION=1 PYTHONDONTWRITEBYTECODE=1 \
  WHITEBOARD_TUI_BINARY=build/vcpkg-release/whiteboard_tui \
  WHITEBOARDCTL_BINARY=build/vcpkg-release/whiteboardctl \
  WHITEBOARD_INSPECT_BINARY=build/vcpkg-release/whiteboard-inspect \
  python3 -B -m unittest -v \
  tools.textart_notes.integration_tests.test_materializer_board
```

三個 binary path 均為明確輸入。

## Generated contracts

```sh
python3 -B tools/generate_unicode_width.py --check
python3 -B tools/generate_contract_schema.py --check
python3 -B tests/check_documentation.py
```

第一個檢查避免 C++/Python Unicode tables 產生 drift。第二個檢查 manifest
schema、JSON limits、generated C++ Agent limits，以及由
`contracts/card-formats.json` 產生的 C++/Python card-format contract。第三個檢查
原始碼目錄中 README、docs 與 skill 的本機 links。

Skill 結構：

```sh
python3 -B tests/check_whiteboard_skill.py
```

## 完整 stress benchmark

```sh
cmake --preset vcpkg-benchmark
cmake --build --preset vcpkg-benchmark
./build/vcpkg-benchmark/whiteboard_stress > benchmark.csv
```

預設 `board` workload 會建立 100,000 張 cards 與 198,900 條 edges。列出與執行
scenario：

```sh
./build/vcpkg-benchmark/whiteboard_stress --help
./build/vcpkg-benchmark/whiteboard_stress --scenario native-glyphs
./build/vcpkg-benchmark/whiteboard_stress --scenario create-cards
./build/vcpkg-benchmark/whiteboard_stress --scenario all
```

`all` 以獨立 process 執行 board、registry 建卡、最大 Agent batch、dense board、
64 MiB payload、100 萬 Glyph、100 萬 slots/tombstones 與
byte-repeatability。輸出含 schema、scenario、input/output counts、時間、吞吐量、
checksum、peak RSS、compiler、build type、OS 與 architecture。

Quick mode只做 correctness smoke：

```sh
./build/vcpkg-benchmark/whiteboard_stress --quick --scenario all
```

頂層 CTest 將八個 quick scenario 各註冊為一個獨立 process；benchmark runner 與
comparator 的 unit tests 使用合成輸出，不會重跑壓力 workload。情境名稱集中在
`benchmarks/stress_scenarios.def`，C++ binary、Python runner 與 CTest 共用此表。

固定五次 runner、JSON baseline 與 regression gate 見
[`../benchmarks/README.md`](../benchmarks/README.md)。不要比較 Debug 與 Release，
也不要比較不同 runner。

## 安裝 smoke test

安裝至可丟棄 prefix，並以 exported `whiteboard::*` targets 編譯一個下游
`find_package` project。Smoke test 也會驗證 install tree 中不存在 private
format/storage/TUI implementation headers：

```sh
ctest --test-dir build/vcpkg-release --output-on-failure \
  -R '^whiteboard_install_package_tests$'
```

此 test 會在 build tree 下建立獨立 install prefix 與 consumer build directory，
不修改 system prefix。

## 平行、亂序與重複執行

```sh
ctest --test-dir build/vcpkg-release --schedule-random -j8 --output-on-failure
ctest --test-dir build/vcpkg-release --repeat until-fail:3 -j8 --output-on-failure
```

PTY tests 共用 `whiteboard_tui` resource lock，只彼此互斥。其他測試可繼續平行
執行。

`vendor/tree-sitter*/test/corpus/` 是 vendored grammar 的上游 corpus，不屬於根
專案 CTest。更新 grammar 時，在對應 vendor 專案執行其 corpus runner。

Release validation 使用複製的 board，並確認 load 後 save 會產生可重新載入的
native-format file。

## 平台矩陣與發布

GitHub Actions 對每次 push 與 pull request 執行：

| Runner | Compiler |
|---|---|
| Ubuntu 24.04 x86-64 | GCC、Clang |
| Ubuntu 24.04 ARM64 | GCC |
| macOS 15 Apple silicon | AppleClang |
| macOS 15 Intel | AppleClang |

每個 runner 都先安裝 CMake 4.3.4，再執行 configure、build、完整 CTest、CPack
與 artifact upload。
`v*` tag 在所有 runner 通過後發布五個平台 archive。WSL2 使用
`vcpkg-release` 在 Linux filesystem 執行同一份完整 CTest。

## 瀏覽器驗證

瀏覽器互通 fixture 由原生 `whiteboard_web_fixture` target 產生，涵蓋所有卡片格式、
樣式、tombstone、連線與 Unicode。WASM 使用同一文件往返，逐 byte 比對輸出的
`.tiwb` 與原檔，另交由原生 inspector 比對 canonical snapshot。Snapshot 涵蓋欄位
見 [`agent-protocol.md`](agent-protocol.md#canonical-snapshot)。純記憶體 codec 的
配置預算與提交原子性也納入 CTest。

JavaScript／WASM 與實際頁面測試在 `web/` 執行，包含儲存 revision、唯讀輸入
限制、跨分頁草稿衝突、手機雙指手勢與旋轉。指令與範圍見原始碼目錄中
`web/README.md` 的「驗證與 benchmark」。

顯示回歸測試另量測 CJK 標點的實際 DOM 格寬，並以延遲 Worker 回覆驗證縮放
期間保留完整舊畫面、視野佇列有界、文件切換不遺失已接受的輸入。縮放效能的
request／frame 次數、ANSI bytes 與時間比較由瀏覽器 benchmark 提供。

小地圖的 C++ 投影測試涵蓋負座標、i64 邊界、tombstone、失效連線端點及原生 PNG。
WASM／瀏覽器測試驗證幾何元素上限、查詢不消耗 ANSI、導航不修改文件、過期回覆
與文件切換、Glyph-only 文件、收合／隱藏停止更新，以及平移只更新視野框。
`benchmark:browser -- --minimap` 對照同一份 500 卡片文件的收合／展開成本。
