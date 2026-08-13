# -*- coding: utf-8 -*-
"""plot_style.py — 中文 + 出版级绘图样式统一注入

用法：
    import sys; sys.path.insert(0, r"<项目根>/scripts")   # 或复制到 code/ 同目录
    from plot_style import apply, save_fig

    apply()                       # 注入全局样式（中文字体自动探测回退）
    ...正常 matplotlib 绑图...
    save_fig(fig, "results/q1/figs/fig_q1_01_demo")   # 同时输出 .png(300dpi) + .pdf 矢量

规范：PNG ≥300dpi（Word）、PDF 矢量（LaTeX）；图内字号 ≥8pt；
禁止在别处手写 rcParams 字体设置。
"""
import os
import warnings

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

FONT_CANDIDATES = ["SimHei", "Microsoft YaHei", "DengXian", "KaiTi"]

_CHOSEN_FONT = None


def apply(font_size=11):
    """注入全局绘图样式，返回实际使用的中文字体名（找不到返回 None）。"""
    global _CHOSEN_FONT
    available = {f.name for f in fm.fontManager.ttflist}
    chosen = next((f for f in FONT_CANDIDATES if f in available), None)
    _CHOSEN_FONT = chosen

    if chosen is None:
        warnings.warn("[plot_style] 未找到任何中文字体，图中中文将显示为方块！"
                      "请安装 SimHei 或 Microsoft YaHei。")
    elif chosen != FONT_CANDIDATES[0]:
        warnings.warn(f"[plot_style] SimHei 缺失，已回退到 {chosen}")

    plt.rcParams.update({
        "font.sans-serif": ([chosen] if chosen else []) + ["Arial", "DejaVu Sans"],
        "axes.unicode_minus": False,      # 负号正常显示
        "font.size": font_size,
        "axes.titlesize": font_size + 2,
        "axes.labelsize": font_size,
        "xtick.labelsize": font_size - 1,
        "ytick.labelsize": font_size - 1,
        "legend.fontsize": font_size - 1,
        "figure.titlesize": font_size + 3,
        "figure.dpi": 100,
        "savefig.dpi": 300,               # 出版级
        "savefig.bbox": "tight",
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.linestyle": "--",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.autolayout": True,
    })
    return chosen


def save_fig(fig, stem, dpi=300, close=True):
    """双份输出：<stem>.png (300dpi) + <stem>.pdf (矢量)。自动建目录。"""
    d = os.path.dirname(stem)
    if d:
        os.makedirs(d, exist_ok=True)
    fig.savefig(stem + ".png", dpi=dpi, bbox_inches="tight")
    fig.savefig(stem + ".pdf", bbox_inches="tight")
    for ext in (".png", ".pdf"):
        path = stem + ext
        if not (os.path.exists(path) and os.path.getsize(path) > 0):
            warnings.warn(f"[plot_style] 输出文件异常: {path}")
    if close:
        plt.close(fig)
    return stem + ".png", stem + ".pdf"


if __name__ == "__main__":
    # 自检 demo：python scripts/plot_style.py
    import numpy as np
    font = apply()
    print(f"使用中文字体: {font}")
    fig, ax = plt.subplots(figsize=(6, 4))
    x = np.linspace(0, 10, 100)
    ax.plot(x, np.sin(x), label="正弦曲线 sin(x)")
    ax.plot(x, np.cos(x), label="余弦曲线 cos(x)")
    ax.set_title("中文绘图自检：温度曲线示例")
    ax.set_xlabel("时间 / 秒")
    ax.set_ylabel("温度 / ℃（负号测试 −12.5）")
    ax.legend()
    out = save_fig(fig, "_demo_plot", close=True)
    print(f"已输出: {out[0]} 和 {out[1]}")
