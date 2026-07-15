#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 Mac 上给 ned-personal-skills 仓库打补丁：README 加 skill 条目+结构树，CHANGELOG 追一行。
带断言，任何替换没命中即报错退出，避免静默改空。"""
import io, sys, datetime
REPO = "/Users/Li.ZHAO/我的代码/ned-personal-skills"

def read(p):
    with io.open(p, encoding="utf-8") as f: return f.read()
def write(p, s):
    with io.open(p, "w", encoding="utf-8") as f: f.write(s)
def sub_once(s, old, new, tag):
    assert s.count(old) == 1, f"[{tag}] 锚点命中 {s.count(old)} 次, 期望 1"
    return s.replace(old, new)

# ---------- README ----------
rp = REPO + "/README.md"; r = read(rp)

skill_entry = """### 8. 攀岩动作分析 (ned-climbing-analysis)

**目录**：`ned-climbing-analysis/`

把一段**单机位**攀岩视频（手机拍）变成攀岩动作分析报告卡。纯本地、不依赖 GPU。两步：① `climb_pose.py` 用 MediaPipe 提全身骨架 → 标注视频 + 3 份 CSV；② `climb_analyze_report.py` 算重心轨迹/爬升效率/流畅度/动作分段/crux 自动定位 → 图表 + 自包含 HTML 报告卡。每段视频结果整理成独立文件夹。

**适用边界**：单摄像头 + 相机静止假设，长度/速度以「身长」为尺度无关单位，看相对趋势而非绝对测量；单目深度不敏感。自动读 ffmpeg 旋转标记转正 iPhone 竖拍 .mov。真三维（米制/可导 Blender）需多机位 FreeMoCap 或 GVHMR（需 GPU）。

**输入**：攀岩视频 `.mov`/`.mp4`（单人、相机尽量静止）

**输出**：`<片名>_攀岩动作分析/` 文件夹（报告卡 html + report_assets 图表/crux 截图 + 标注视频 + 数据 CSV/json + 脚本 + README）

**依赖**：`mediapipe opencv-python numpy matplotlib` + 系统 `ffmpeg`

**触发词**：`/ned-climbing-analysis`、`分析我的攀岩视频`、`攀岩姿态`、`攀岩动作分析`、`攀岩报告卡`、`climbing analysis`、`看下我这条线`

---

"""
r = sub_once(r, "## 项目结构", skill_entry + "## 项目结构", "README/skill-entry")

old_tree = """└── ned-avoid-ai-writing/           # 英文去 AI 味（fork avoid-ai-writing v3.8.0）
    ├── SKILL.md
    ├── LICENSE
    └── detector/                   # 确定性 JS 检测引擎（43 类，0-100 评分）
```"""
new_tree = """├── ned-avoid-ai-writing/           # 英文去 AI 味（fork avoid-ai-writing v3.8.0）
│   ├── SKILL.md
│   ├── LICENSE
│   └── detector/                   # 确定性 JS 检测引擎（43 类，0-100 评分）
└── ned-climbing-analysis/          # 攀岩动作分析（单机位 MediaPipe，两步出报告卡）
    ├── SKILL.md
    └── scripts/
        ├── climb_pose.py           # 视频 → 骨架标注视频 + CSV
        └── climb_analyze_report.py # CSV → 指标 + 图表 + crux + 报告卡
```"""
r = sub_once(r, old_tree, new_tree, "README/tree")
write(rp, r)

# ---------- CHANGELOG ----------
cp = REPO + "/CHANGELOG.md"; c = read(cp)
c = sub_once(c,
    "**总纲：17 次迭代 · $34.29+ · 46+ files · 2026-04-30 至 2026-06-17**",
    "**总纲：18 次迭代 · $34.29+ · 49+ files · 2026-04-30 至 2026-06-17**",
    "CHANGELOG/总纲")
ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
row = ("| " + ts + " | 新增 ned-climbing-analysis：单机位攀岩视频→MediaPipe 骨架→重心/效率/流畅度/动作分段/crux 自动定位→自包含 HTML 报告卡 | — | 3 files, 1 new dir | 单目+相机静止假设，尺度用「身长」；脚本自动读 ffmpeg rotate 转正 iPhone 竖拍 .mov；已验证 IMG_6424 与 IMG_6952(V2绿线) 检出率 100%；真3D 需多机位 FreeMoCap 或 GVHMR(GPU) |\n")
anchor = "|------|----------|------|--------|---------|\n"
c = sub_once(c, anchor, anchor + row, "CHANGELOG/row")
write(cp, c)

print("PATCH OK")
print("README skill #8:", "### 8. 攀岩动作分析" in read(rp))
print("README tree:", "ned-climbing-analysis/          # 攀岩动作分析" in read(rp))
print("CHANGELOG 总纲18:", "18 次迭代" in read(cp))
print("CHANGELOG row:", "新增 ned-climbing-analysis" in read(cp))
