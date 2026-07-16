# 攀岩视频动作分析

把单机位手机拍的攀岩视频变成动作分析报告：MediaPipe 骨架提取 → 指标计算 → HTML 报告卡（v1 已可用），正在扩展动作知识库 + 动作识别 + 节奏/缺陷统计报告 v2（进度见 [PLAN.md](PLAN.md) 看板）。

## 现状（2026-07-16）

- **v1 流水线**：可用。`climb_pose.py`（视频→骨架 CSV）+ `climb_analyze_report.py`（CSV→HTML 报告卡）。
- **S1 动作知识库**：已完成。从教材《攀岩技術教本詳細圖解》（東秀磯）提炼 54 个动作，含分类/可判性/骨架规则/视觉线索/教材页码。
- **S2 全身动作分段**：已完成。`climb_segments.py` 锚点位移法——手/脚末端净位移 ≥0.5 身长判"真换点"，输出 move/static 段 + 肢体换点事件两层；`climb_segments_review.py` 生成烧字幕审阅视频供人眼验收。IMG_6952 人眼零漏检，IMG_6424 零改参泛化通过。
- **S3 节奏统计报告 v2a**：已实现，待老板验收。`climb_report_v2.py` 出「攀岩节奏报告卡.html」
  + `metrics_v2.json`，六项指标：完成时间 / 切换耗时 / 难点 / 三段占比(move·rest·adjust) /
  弯臂耗力 / 休息点质量。IMG_6942 + IMG_6152 两条素材抽帧自验证通过。
  难点分**两类并列**：v2a「卡住型」（停顿长/同高度反复出手=不知道怎么办）与 v1「发力型」
  （加速度+关节屈曲=拼尽全力），测的是正交现象，谁也不验证谁。遗留一项（rest 从未触发）
  见 [PLAN.md](PLAN.md) 看板。
- S4-S10（规则匹配、视觉判定、标注回流、报告 v2b）：待做。
- 历史两条视频（IMG_6424/6952）的分析产物已清理出工作区（2026-07-16）：均可由原视频一键重建，CSV 亦存于 git 历史（`git checkout 14b701f -- <path>` 可取回）。

## 怎么用

### 分析一条新视频（v1 报告卡 + S2 分段）

**素材库结构（2026-07-17 定稿）：一条线一个文件夹，原片和分析产物放在一起。**

```
素材/IMG_6942/
├── IMG_6942.MOV              原片
├── 攀岩动作报告卡.html         v1 报告卡
├── 攀岩节奏报告卡.html         v2a 节奏报告卡  ← 从这看
├── 数据/                     3 份 CSV + metrics.json + metrics_v2.json + segments.json
├── report_assets/            v1 图表 + crux 截图
├── report_assets_v2/         v2a 图表
└── 标注视频/                  骨架标注视频 + 分段审阅视频
```

分析一条新线（把 `<片名>.MOV` 放进 `素材/<片名>/` 后，四条命令一路到底）：

```bash
pip install mediapipe==0.10.14 opencv-python numpy matplotlib pillow
V=IMG_6942; D=素材/$V                                  # 改这一行即可换片
python3 climb_pose.py "$D/$V.MOV" "$D/数据"                                    # 视频 → 骨架 CSV
python3 climb_analyze_report.py --dir "$D/数据" --base $V \
    --annotated "$D/数据/${V}_annotated.mp4" --out "$D"                        # v1 报告卡
python3 climb_segments.py "$D/数据/${V}_pose2d.csv"                            # S2 分段+换点事件
python3 climb_report_v2.py --dir "$D/数据" --base $V --out "$D"                # S3 节奏报告卡 v2a
python3 climb_segments_review.py "$D/$V.MOV" "$D/数据/${V}_segments.json" \
    --out "$D/标注视频/${V}_segments_review.mp4"                                # 审阅视频
```

注意 mediapipe 要 0.10.14（≥0.10.2x 移除了 `mp.solutions` 旧 API，脚本会报错）。

**Windows 上必须加环境变量**（Mac 不用；三条铁律的来龙去脉见 [CLAUDE.md](CLAUDE.md)）：

```bash
# venv 必须在纯 ASCII 路径（mediapipe 无法从含中文的路径加载模型）
py -3.10 -m venv C:/venvs/climb310
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8   # v1 脚本写文件没指定编码，Windows 默认 GBK 会挂
export CLIMB_MAX_W=960 CLIMB_ROTATE=0        # ★CLIMB_ROTATE=0 必须加：OpenCV 在 Windows 会
                                             #  自动转正，脚本再转一次→人躺着，检出率仍 100%
                                             #  但重心高度量的是水平方向，结果全错
```

**验证素材要求**：全程不能有路人从镜头前走过（MediaPipe 只跟一个人，会跟错，而且检出率
不会掉、发现不了）、攀岩者不能爬出画面。视频开头含「走向岩壁」没关系，v2a 有上墙门会自动
排除。当前素材：`素材/IMG_6942/`（41s，含走近段）、`素材/IMG_6152/`（31s，一上来就在墙上）。
审阅视频里左右肢标错的段：在 `annotations/<base>_side_overrides.json` 写
`[{"t": 秒, "limb": "左手", "note": "..."}]` 后重跑 climb_segments.py 即回流。

### 知识库：浏览 / 重新生成

```bash
open knowledge_base/moves_viewer.html          # 直接浏览（54 动作卡片，可搜索/筛选/看教材页图）
python3 knowledge_base/kb_lint.py              # 校验 moves.json
python3 knowledge_base/kb_render.py            # moves.json 改动后重新生成 viewer
python3 knowledge_base/kb_extract_pages.py     # 重新渲染教材页图（需 brew install poppler）
```

教材页图存 `knowledge_base/book_pages/`，不入 git。教材 PDF 本体线下保管
（2026-07-16 起不在本机工作区），重建页图需先把 PDF 放回项目根目录再跑
kb_extract_pages.py。

## 目录速览

| 路径 | 内容 |
|---|---|
| `PLAN.md` | 总计划 + S1-S10 进度看板（唯一计划真相） |
| `素材/<片名>/` | 一条线一个文件夹：原片 + 报告卡 + 数据 + 图表 + 标注视频（不入 git） |
| `climb_pose.py` / `climb_analyze_report.py` | v1 流水线（冻结不改） |
| `climb_segments.py` / `climb_segments_review.py` | S2 分段+换点事件 / 审阅视频生成 |
| `climb_report_v2.py` | S3 节奏统计报告 v2a（阈值旋钮集中在文件顶部） |
| `knowledge_base/` | moves.json + lint/render/extract 脚本 + viewer |
| `annotations/` | 老板人工左右覆写 JSON（不可再生资产，入 git） |
| `cases/` | 标注案例库（S6 起启用） |
| `_skill_stage/ned-climbing-analysis/` | skill 暂存区（S10 收编） |
| `FreeMoCap_import/` | 多机位 3D 方案资料（与当前计划无关） |
