# 建置

讀者：編譯、安裝或以 CMake 使用 whiteboardTUI 的使用者。

本文件擁有 prerequisites、一般 CMake configuration、安裝、exported targets 與
Python 工具的 source-tree 執行方式。測試矩陣由 [`testing.md`](testing.md)
擁有。

## 支援範圍

| 作業系統 | 架構 | 執行方式 |
|---|---|---|
| Linux | x86-64、ARM64 | 原生 POSIX build |
| macOS | Apple silicon、Intel | 原生 AppleClang build |
| Windows | x86-64、ARM64 | WSL2 內的 Linux build |

原生 Windows executable 不在支援範圍。WSL2 內的 source、build tree、`.tiwb`、
socket 都放在 Linux filesystem；`/mnt/c` 只用於匯入與匯出檔案。

所有平台沿用 `poll()`、Unix-domain socket、termios 與 POSIX atomic file
transaction。沒有第二套 transport 或 storage implementation。

## 必要條件

- Git；
- CMake 4.3 以上；
- Ninja；
- C++20 compiler；
- Python 3.11 以上；
- vcpkg。

Linux 使用 GCC 或 Clang。macOS 使用 AppleClang，並由 Xcode Command Line Tools
提供 compiler 與 SDK。Windows 先安裝 WSL2 與 Ubuntu，再於 WSL shell 執行同一組
Linux 指令。

`vcpkg.json` 固定 Abseil C++、FreeType 與 libpng 的解析 baseline。Tree-sitter
0.26.9、tree-sitter-markdown 0.5.3、tree-sitter-markdown-inline 0.5.3，以及
tree-sitter-cpp 0.23.4 的 C source 已放在 `vendor/`，不需要系統 Tree-sitter
package、Node.js 或 parser generator。

發行矩陣固定使用 CMake 4.3.4。Linux x86-64、Linux ARM64 與 macOS 都使用相同
patch version；本機可使用 CMake 4.3 以上版本。

準備固定版本的 vcpkg：

```sh
git clone https://github.com/microsoft/vcpkg.git /absolute/path/vcpkg
git -C /absolute/path/vcpkg checkout 7ebe9ffa933558af0c2fec88a1cdd5972fdcb51c
/absolute/path/vcpkg/bootstrap-vcpkg.sh -disableMetrics
export VCPKG_ROOT=/absolute/path/vcpkg
```

## Configure、build 與 test

Release 是所有支援平台的標準入口：

```sh
cmake --preset vcpkg-release
cmake --build --preset vcpkg-release
ctest --preset vcpkg-release
```

主要程式為：

```sh
./build/vcpkg-release/whiteboard_tui [board-file]
./build/vcpkg-release/whiteboardctl
./build/vcpkg-release/whiteboard-inspect snapshot BOARD --output FILE
```

未提供 board-file 時，`whiteboard_tui` 使用目前工作目錄下的
`whiteboard.tiwb`。

## 專案選項

| CMake option | 預設 | 用途 |
|---|---:|---|
| `BUILD_TESTING` | `ON` | Configure CTest 與 integration targets |
| `WHITEBOARD_BUILD_STRESS` | `OFF` | 在 `BUILD_TESTING=OFF` 時仍建立 standalone full stress benchmark |
| `WHITEBOARD_WARNINGS_AS_ERRORS` | `OFF` | 對專案 C++ targets 加上 `-Werror` |
| `WHITEBOARD_ENABLE_SANITIZERS` | `OFF` | 加上 AddressSanitizer 與 signed-overflow instrumentation |
| `WHITEBOARD_PACKAGE_PLATFORM` | system 與 CPU | 設定 CPack archive 檔名的平台標籤 |

Debug 與 sanitizer 使用同一份 manifest：

```sh
cmake --preset vcpkg-debug
cmake --build --preset vcpkg-debug
ctest --preset vcpkg-debug

cmake --preset vcpkg-sanitize
cmake --build --preset vcpkg-sanitize
ctest --preset vcpkg-sanitize -j1
```

`BUILD_TESTING=ON` 時，quick CTest 需要的 `whiteboard_stress` target 一定會建立；
`WHITEBOARD_BUILD_STRESS=ON` 的用途，是在關閉其餘 tests 時仍建立同一個 executable。

使用系統 package 的發行維護者仍可直接執行一般 CMake configure；CMake 只要求
`absl`、`Freetype` 與 `PNG` targets。Sanitizer、warnings-as-errors 與 benchmark
profile 見 [`testing.md`](testing.md)。

## Screenshot 字型

Renderer 依序嘗試平台上的常見 monospace 字型。完整 CJK screenshot 使用 Source
Han Mono，並以環境變數指定字型檔：

```sh
export WHITEBOARD_TUI_SCREENSHOT_FONT=/absolute/path/SourceHanMono.ttc
```

這個變數同時套用於 TUI screenshot、thumbnail 與相關測試。字型不包含在 source
或 binary package。

## CMake target 版圖

專案建立並 export 下列 targets：

| Exported target | 責任 |
|---|---|
| `whiteboard::tree_sitter` | 隨專案附帶的 Tree-sitter runtime |
| `whiteboard::tree_sitter_markdown` | 隨專案附帶的 Markdown block grammar |
| `whiteboard::tree_sitter_markdown_inline` | 隨專案附帶的 Markdown inline grammar |
| `whiteboard::tree_sitter_cpp` | 隨專案附帶的 tree-sitter-cpp grammar 支援 target |
| `whiteboard::core` | document/model、formats、text、style 與 syntax |
| `whiteboard::codec` | 純 `.tiwb` 與卡片內容編解碼 |
| `whiteboard::board_render` | 平台共用 framebuffer 繪製 |
| `whiteboard::io` | 原生檔案發布、Folder export 與 canonical snapshot |
| `whiteboard::render` | screenshot、thumbnail 與 font rasterizer，連結 board_render |
| `whiteboard::agent` | Agent protocol 與 Unix-socket server |
| `whiteboard::tui` | 由其他 capability 組成的 terminal runtime |

`whiteboard_tui`、`whiteboardctl` 與唯讀磁碟工具 `whiteboard-inspect` 是
executable targets。Dependency direction 與 ownership 理由由
[`architecture.md`](architecture.md) 擁有。

## 安裝

安裝至指定 prefix：

```sh
cmake --install build/vcpkg-release --prefix /tmp/whiteboard-install
```

Install 內容包含 binaries、static libraries、安裝清單列出的 public headers、
`find_package(whiteboard-tui)` metadata、README、繁中文件樹，以及四個隨附
Tree-sitter components 的第三方 licenses。
文中 `web/`、`tools/` 等路徑指向原始碼目錄，不屬於原生安裝文件樹。

CPack archive 預設名為
`whiteboard-tui-2.0.0-${CMAKE_SYSTEM_NAME}-${CMAKE_SYSTEM_PROCESSOR}.tar.gz`；
例如 Linux x86-64 通常是 `whiteboard-tui-2.0.0-Linux-x86_64.tar.gz`。CI 以
`WHITEBOARD_PACKAGE_PLATFORM` 產生 Linux/macOS 與 CPU 都明確的名稱。Archive
仍受作業系統 ABI 與最低系統版本約束；其他平台從 source 建置。

下游 CMake project 可使用 exported target：

```cmake
cmake_minimum_required(VERSION 4.3)
project(example LANGUAGES CXX)

find_package(whiteboard-tui 2 CONFIG REQUIRED)
add_executable(example main.cpp)
target_link_libraries(example PRIVATE whiteboard::core)
```

Package metadata 會要求建置 archive 時使用的 Abseil LTS ABI version。下游以同一份
`vcpkg.json` baseline，或提供相同版本的 Abseil CMake package。

若安裝位置不在 system search path，將 `CMAKE_PREFIX_PATH` 指向 prefix：

```sh
cmake -S consumer -B consumer-build \
  -DCMAKE_PREFIX_PATH=/tmp/whiteboard-install
```

只有 CMake install 清單中的 headers 會被安裝。`app.hpp`、binary/project/content
codecs、format implementation helpers，以及 `tui/entry.hpp` 以外的
TUI headers 都刻意排除。

## Python renderer/materializer 工具

Renderer 與 materializer 需要 Python 3.11+，直接從 source tree 使用：

```sh
python3 -m tools.textart_notes.render_note --help
python3 -m tools.textart_notes.materialize_textart --help
```

Materializer 以 `--whiteboardctl build/vcpkg-release/whiteboardctl` 指定執行檔。
純檔案檢查 `--check-only` 不需要執行檔。

目前 repository 沒有 `pyproject.toml`、`setup.py` 或 `setup.cfg`，因此不提供
sdist、wheel 或 console-script 安裝介面。

## Source-tree skill

Markdown 白板 skill 位於：

```text
.agents/skills/whiteboard-markdown-mind-map/
```

Skill 使用 repository 內的 Python packages、renderer fixtures、技術文件與 build
目錄中的 CLI binaries。操作命令必須提供 `--whiteboardctl`；`final` 與
`check-attestation` 另須提供 `--whiteboard-inspect`。參數值是執行檔路徑，
例如 `build/vcpkg-release/whiteboardctl` 與 `build/vcpkg-release/whiteboard-inspect`。
它與 source release 一起發布，並從 repository root 執行。

CMake install 與 binary CPack archive 包含 runtime、libraries、headers 與 docs。
Skill 隨 source release 發布。

## 常見 configuration failure

- `CMAKE_TOOLCHAIN_FILE` 不存在：確認 `VCPKG_ROOT` 是 vcpkg repository 的絕對路徑。
- vcpkg baseline 無法解析：將 vcpkg checkout 切到 `vcpkg.json` 的
  `builtin-baseline`。
- compiler 或 Ninja 不存在：安裝平台 compiler toolchain 與 Ninja。
- screenshot 無法載入字型：設定 `WHITEBOARD_TUI_SCREENSHOT_FONT`。
- Agent 或 PTY test 無法建立 Unix socket：在原生 Linux、原生 macOS 或 WSL2 的
  Linux filesystem 執行。

Build 成功後，在貢獻或 packaging 前依 [`testing.md`](testing.md) 執行符合風險的
驗證。

## 瀏覽器建置

瀏覽器版以 Emscripten 建置，使用獨立的 `build/web/`，不載入原生 vcpkg libraries。
啟用 Emscripten SDK（設定 `EMSDK`）後可使用 `web-release` configure/build presets；
也可直接使用 `emcmake`。完整步驟、套件與靜態頁面產物見原始碼目錄中的
`web/README.md`。
