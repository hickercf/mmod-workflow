# S5 任务简报：图表生成与清单（comp-figures）

派发对象：solver / data-processing（每问一个实例）
输入：S3/S4 的 winner 结果与证据
输出：

- 每问 `results/qN/figs/fig_*.png` 与**同 stem PDF** 成对产出（plot_style.py 注入中文样式）
- 图表自明标题；必要时 `results/qN/tables/*.csv`
- 每问 `results/qN/manifest-fragment.md` 正式片段（solver 只写本问片段）

主循环执行：

```bash
python scripts/merge_manifest.py <workspace>
python scripts/merge_manifest.py <workspace> --check
python scripts/workflow_engine.py <workspace> complete S5
```

gate S5 检查：canonical manifest 重建且 --check 通过、每问至少一对 PNG/PDF 图。
