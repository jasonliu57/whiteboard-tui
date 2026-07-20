# JetBrains Mono 框線子集

`jetbrains-mono-box-wght-normal.woff2` 保留 JetBrains Mono 2.304 的
U+2500–U+259F（全部 160 個框線與方塊字元）及 100–800 可變字重。
檔案為 2,872 bytes；不含 Latin 或 CJK，CSS 以 `unicode-range` 限定用途。
Latin 繼續使用既有 Fontsource 套件，中文繼續使用裝置備援字型。

來源為 [JetBrains Mono v2.304](https://github.com/JetBrains/JetBrainsMono/tree/v2.304)，
原始檔為 `fonts/variable/JetBrainsMono[wght].ttf`，SHA-256：

```text
662a196d58f1183bf2d77428b6d5283fe3f45161ab021bea4036bc98e5cac016
```

子集 SHA-256：

```text
02e63ea99034395969baf7c7a074779b2866ae79233c7dedaa7464733f783806
```

授權為 SIL OFL 1.1，完整原文保留於 [OFL.txt](OFL.txt)，建置時複製至
`dist/licenses/jetbrains-mono-box.txt`。

一般建置直接複製已簽入的 WOFF2，不需要下載字型或安裝字型處理工具。
若需重新產生，可在暫存目錄執行以下命令；本次使用 FontTools 4.65.0 與
Google WOFF2 compressor。工具版本可能影響壓縮後的 bytes。

```sh
curl -fL 'https://raw.githubusercontent.com/JetBrains/JetBrainsMono/v2.304/fonts/variable/JetBrainsMono%5Bwght%5D.ttf' -o JetBrainsMono.ttf
sha256sum JetBrainsMono.ttf
pyftsubset JetBrainsMono.ttf --unicodes=U+2500-259F --layout-features= \
  --name-IDs=0,1,2,3,4,5,6,13,14 --name-languages=0x409 \
  --no-recalc-timestamp --output-file=jetbrains-mono-box-wght-normal.ttf
woff2_compress jetbrains-mono-box-wght-normal.ttf
```

更新時需核對來源 checksum、字元覆蓋及可變字重，並執行 Web 的首次載入、
框線／標點與縮放測試。終端首次量測前會一併載入 Latin 與框線子集；
載入失敗時沿用備援字型。
