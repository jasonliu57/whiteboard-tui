# Benchmark baseline

使用固定的 Release runner 建立五次量測：

```sh
python3 -B benchmarks/run.py ./build-stress/whiteboard_stress \
  --runs 5 \
  --reason "更新原因" \
  --output benchmarks/baselines/linux-x86_64-gcc-release.json
```

每個 scenario 由獨立 process 執行。JSON 保存五次原始結果、median、編譯器、
build type、OS 與 architecture。

比較同一 runner 的結果：

```sh
python3 -B benchmarks/run.py ./build-stress/whiteboard_stress \
  --runs 5 --reason "驗證變更" --output /tmp/current.json
python3 -B benchmarks/compare.py \
  benchmarks/baselines/linux-x86_64-gcc-release.json \
  /tmp/current.json
```

`iterations`、input/output counts、output bytes 與 checksum 採精確比較。全部
專用 scenario 與至少 5 ms 的 board metric 套用 15% median 時間門檻；所有
metric 的 median peak RSS 套用 10% 門檻。新增與消失的 scenario 或 metric
也會失敗。

Quick mode只驗證 correctness：

```sh
python3 -B benchmarks/run.py ./build/whiteboard_stress \
  --quick --runs 1 --reason "smoke" --output /tmp/quick.json
```

基準涵蓋 `native-*` 序列化、registry、Agent batch 與 `board` 完整白板
workloads。所有 scenario 都保存相同 runner 的五次原始量測。
