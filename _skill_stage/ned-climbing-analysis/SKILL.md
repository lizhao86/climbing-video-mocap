---
name: ned-climbing-analysis
description: 把一段普通攀岩视频（单机位手机拍）变成一张攀岩动作分析报告卡。两步脚本：先用 MediaPipe 提取全身骨架，再算重心轨迹/爬升效率/流畅度/动作分段/crux 自动定位，输出标注视频 + 图表 + 自包含 HTML 报告卡，整理成独立文件夹。当用户说"分析我的攀岩视频"、"攀岩姿态"、"攀岩报告卡"、"climbing analysis"、"/ned-climbing-analysis"、或丢来一段攀岩 .mov/.mp4 想看动作时触发。
---

# Ned 攀岩动作分析

把一段**单机位**攀岩视频变成动作分析报告卡。纯本地、不依赖 GPU、不依赖云。底层 2D 姿态用 MediaPipe Pose。

## 适用边界（先说清）

- **单摄像头 + 相机静止**假设。长度/速度统一用「身长」为尺度无关单位，反映**相对趋势与节奏**，不是实验室级绝对测量。
- 单目对**深度方向不敏感**，分析以画面内（上下/左右）运动为主。
- iPhone 竖拍 .mov 常带 `rotate=90` 元数据，脚本会自动读 ffmpeg 旋转标记**转正**。
- 想要真三维（米制/深度/可导 Blender）→ 多机位 FreeMoCap 或 GVHMR（需 GPU/Colab），不在本 skill 范围。

## 依赖

```
pip install mediapipe opencv-python numpy matplotlib --break-system-packages
```
外加系统 `ffmpeg`（读取视频旋转标记）。脚本在 `scripts/`。

## 工作流程（两步）

### 1. 提取骨架 → 标注视频 + CSV

```bash
CLIMB_MAX_W=960 CLIMB_STEP=1 CLIMB_COMPLEXITY=2 \
  python3 scripts/climb_pose.py <视频路径> <输出目录>
```

环境变量（性能/精度旋钮）：
- `CLIMB_MAX_W`：按最大宽度等比缩放（0=不缩放）。4K 原片建议设 960，CPU 上约 0.16s/帧。
- `CLIMB_STEP`：每隔几帧取一帧（1=全帧）。
- `CLIMB_COMPLEXITY`：MediaPipe 模型复杂度 0/1/2，2 最准。
- `CLIMB_ROTATE`：手动覆盖旋转角（一般不用，自动探测）。

产出（`<base>` = 视频文件名前缀）：
- `<base>_annotated.mp4` — 骨架叠加 + 左上角实时关节角，已转正。
- `<base>_angles.csv` — 每帧关节角度（肘/肩/髋/膝 左右 + 躯干倾角 + 平均可见度）。
- `<base>_pose2d.csv` — 每帧 33 点 2D 画面坐标（归一化 + 像素），全局重心/效率靠它。
- `<base>_landmarks.csv` — 每帧 33 点 3D 相对坐标（髋为原点），关节角度靠它。

**先看「检测到人体的帧」占比**——攀岩贴墙遮挡重，这是判断本路线能否用的关键。低于 ~80% 再考虑换方案。

### 2. 算指标 + 出图 + 截 crux + 生成报告卡（一步到位）

```bash
python3 scripts/climb_analyze_report.py \
  --dir <CSV所在目录> --base <文件名前缀> \
  --annotated <标注视频mp4> --out <报告输出目录> \
  --route "V2 抱石·绿线" --title "IMG_xxxx"
```

产出到 `--out`：
- `攀岩动作报告卡.html` — 自包含报告（核心指标卡 + 4 张图 + crux 截图 + 动态解读建议 + 数据口径）。`--route` 会作为绿色标签显示在标题旁。
- `report_assets/` — progress / com_path / limb_activity / angles 四张图 + 5 张 crux 关键帧。
- `<base>_metrics.json`（写回 `--dir`）— 全部指标的机读数值。

## 指标口径

- **净上升（身长）**：重心从最低到最高的纵向位移。
- **攀爬效率** = 净上升 ÷ 重心总走线，越高越省力（多余横移越少）。
- **流畅度评分 /100**：基于重心 jerk（加加速度），越平滑越高。
- **动作数 move**：各肢体速度超阈值的连续活跃段（≥0.15s 才计一次）。
- **静止/锁定占比**：所有肢体都低速的时间比例。
- **crux**：综合「重心加速度 + 肢体速度 + 关节极端屈曲」强度排序，排除首尾 1.5s 差分边界假峰，取相互间隔 >2.5s 的 5 个最吃力瞬间。
- **左右用力**：左右手 / 左右腿累计移动量占比，看惯用侧与脚法均衡度。

## 结果归档（约定）

每段视频结果整理成一个独立文件夹，放在视频所在处：

```
<片名>_攀岩动作分析/
├── 攀岩动作报告卡.html      ← 从这看
├── report_assets/           图表 + crux 截图
├── 标注视频/<base>_annotated.mp4
├── 数据/                    metrics.json + 3 份 CSV
├── 脚本/                    climb_pose.py + climb_analyze_report.py（随结果带一份，便于复跑）
└── README.md                索引 + 关键结论 + 与历史片对比表
```

## 多片对比

分析多条线后，可把各自 `metrics.json` 横向汇成对比表（时长/净上升/效率/流畅度/move/脚法均衡度），跟踪 Ned 的进步。新片分析完在其 README 里追一行对比表。

## 触发词

`/ned-climbing-analysis`、`分析我的攀岩视频`、`攀岩姿态`、`攀岩动作分析`、`攀岩报告卡`、`climbing analysis`、`看下我这条线`、以及用户直接丢来攀岩 `.mov`/`.mp4` 并想看动作时。

## 汇报口吻

完成后给老板：检出率、3-5 个关键指标、最值得注意的 1-2 个发现（如脚法偏废、静止占比高），并附报告卡文件位置。不堆术语，先给结论。
