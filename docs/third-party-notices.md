# 第三方聲明

讀者：source/binary distributor、auditor 與檢視 dependency license 的使用者。

whiteboardTUI 自有原始碼採 MIT License，完整條款見專案根目錄的 `LICENSE`；
瀏覽器產物也在其根目錄附帶同一份 `LICENSE`。
下列第三方專案依各自授權使用或重新散布，不因專案採 MIT 而改變。
本文件記錄第三方 notices；實際條款以對應的 upstream license text 為準。

## 重新散布的原始碼

### Tree-sitter runtime

`vendor/tree-sitter/` 包含 Tree-sitter 0.26.9 runtime source，依 MIT License
散布。完整聲明保留在 `vendor/tree-sitter/LICENSE`；runtime 內的 Unicode tables
聲明保留在 `vendor/tree-sitter/lib/src/unicode/LICENSE`。

Copyright (c) 2018 Max Brunsfeld.

### tree-sitter-markdown

`vendor/tree-sitter-markdown/` 包含 tree-sitter-markdown 0.5.3 的 block 與 inline
grammars，依 MIT License 散布。完整聲明保留在
`vendor/tree-sitter-markdown/LICENSE`。

Copyright (c) 2021 Matthias Deiml.

### tree-sitter-cpp

`vendor/tree-sitter-cpp/` 下產生的 C++ grammar 衍生自 tree-sitter-cpp，並依
MIT License 散布。完整聲明保留在 `vendor/tree-sitter-cpp/LICENSE`。

Copyright (c) 2014 Max Brunsfeld and tree-sitter-cpp contributors.

## 建置與執行期相依套件

這些 libraries 由 vcpkg 或 operating system 提供，不會複製進 source
distribution：

- Abseil C++ — Apache License 2.0。
- FreeType — 由 distributor 選擇 FreeType Project License 或 GNU GPL v2。
- libpng — libpng License。

範例顯示的預設 screenshot path 會在使用者已安裝時使用 Source Han Mono。
Source Han fonts 採 SIL Open Font License 1.1，且本 repository 不散布字型。

Python renderer/materializer 以 Python standard library 執行。Python 本身與
platform C/C++ runtimes 各自保留其授權。

Binary distributor 有責任針對其實際發布的版本與 optional components 重現精確
聲明。

## 瀏覽器產物

瀏覽器套件包含 xterm.js 6.0.0 與 addon-fit 0.11.0（MIT License），以及以
Emscripten 6.0.0 建置的核心與 Abseil 20260526.0。完整 upstream 授權隨產物
放在 `licenses/`，涵蓋 xterm.js、addon-fit、Abseil、Emscripten、Tree-sitter
與 grammar／Unicode tables；bundle 另保留第三方程式碼聲明。

瀏覽器介面使用 WebTUI 0.1.10 與 Catppuccin theme 0.0.5（MIT License），
元件選擇器在建置時限縮到白板容器。完整授權見 `web/licenses/webtui.txt`。
JetBrains Mono Latin 字型由 Fontsource 5.3.0 提供，依 SIL Open Font License
1.1 散布，授權隨產物保留在 `licenses/jetbrains-mono.txt`。
框線與方塊字元子集取自 JetBrains Mono 2.304，依同一 SIL OFL 1.1 散布；
來源、checksum 與產生方式見 [字型子集說明](../web/fonts/README.md)，完整
授權隨產物保留在 `licenses/jetbrains-mono-box.txt`。

esbuild、PostCSS 與 Playwright 是建置／測試依賴，不是頁面執行期依賴。
瀏覽器產物不包含 FreeType 或 libpng。
