# 攀岩视频动作分析

把单机位手机拍的攀岩视频变成你的**攀岩账本**：MediaPipe 提骨架 → 算指标 →
账本页（累计数字 + 每条线一条记录）→ 点进单条线的动作分析报告卡。
2026-07-18 定案主干是「旅程账本」（Strava 模式），报告卡收编为详情页
（进度见 [PLAN.md](PLAN.md) 看板，定案见其 §10）。

## 现状（2026-07-19）

- **旅程账本（主干门面）**：可用。`攀岩账本.html` 一页看累计数字（线路数/爬升/
  在墙时间/出手次数/连续周数）、完攀难度徽章、动作收集、爬升足迹图、线路记录列表，
  每条记录点进对应报告卡。**填攀岩信息**：不用填表，Claude 分析视频时会在对话里问你，
  答完写进 `素材/<片名>/线路.json`。日期自动读视频拍摄时间（文件时间是拷贝时间，不可靠）。

- **报告卡**：可用。一条线出一张 `攀岩报告卡.html`，暗色·影像优先，图表全内联 SVG，
  难点/弯臂预览是 3 秒动作片段（切面前 1 后 2，h264 静态图当封面），鼠标悬浮才播。
  **2026-07-18 按深度调研重构**（依据见 docs/2026-07-18-指标价值review与路线决策.md）：
  KPI = 完攀用时 / 净上升 / 流畅度（轨迹熵 GIE，30 年文献背书、只用 2D 髋轨迹）/
  卡住 N 处；砍掉了「姿态最极端」（v1 crux 已退化）和「攀爬效率」（横移线失真）；
  停顿不再当坏事报（高手停得反而更多）。新增「动作记录」区块（只列骨架位置信号
  可靠的动作，只记不评）；卡住的地方若做过视觉判定，卡片显示看图结论并标「看过画面」。
- **S1 动作知识库**：已完成。从教材《攀岩技術教本詳細圖解》（東秀磯）提炼 54 个动作，含分类/可判性/骨架规则/视觉线索/教材页码。
- **S2 全身动作分段**：已完成。`climb_segments.py` 锚点位移法——手/脚末端净位移 ≥0.5 身长判"真换点"，输出 move/static 段 + 肢体换点事件两层；`climb_segments_review.py` 生成烧字幕审阅视频供人眼验收。IMG_6952 人眼零漏检，IMG_6424 零改参泛化通过。
- **S3 节奏统计**：已实现，待老板验收。六项指标：完成时间 / 切换耗时 / 难点 /
  三段占比(move·rest·adjust) / 弯臂耗力 / 休息点质量。IMG_6942 + IMG_6152 抽帧自验证通过。
  其中**休息点质量判据 2026-07-17 重做过一轮**（旧版默认墙是竖直的，外倾壁上把发力判成
  休息、还打了满分），重做后在六盘水先锋素材的 4 个真实挂绳休息上逐帧核对通过。
- **远景素材取数**：`climb_pose_roi.py`（2026-07-18）。人在 4K 里只有 ~300px 的户外
  远景（如六盘水 28min 先锋），标准流程谁都检不出，走这个脚本 ROI 跟踪取数，输出与
  标准流程逐列同格式，下游零改动。
- **S4 动作识别（窄版）**：完成。`climb_match.py` 只识别位置/时序信号可判的动作
  （高跨步/同点/换手 + 手顺统计，抽验 6/6 全对；交叉/掛腳记 low 不展示），
  输出 `<base>_recognition.json`。角度类动作（掛旗、drop knee 等）不上规则——
  单目角度不可信，试做过蹲跳/外撐后因「素材零正例、全是误报」砍掉。
- **S5 视觉判定（卡点范围）**：首轮完成。`climb_keyframes.py` 给每个卡住型难点出
  关键帧联络表，按协议（判定词汇仅限知识库 54 动作、判断必须指回具体帧）看图判定,
  结果写回 recognition.json 并进报告卡。已实证能纠正几何误报。
- S6-S10（标注回流、案例库、动作缺陷、手型、skill 收编）：待做。

**已知短板**（细节见 [PLAN.md](PLAN.md) §8）：

1. **v1 的 crux 公式已从报告卡撤下**（2026-07-18）——实测退化成「关节弯得深」排序，
   不是「用力」排序。时间线上标记还在（可悬浮回看），但不再单独成区块。
   **S8 若想复用 v1 的 crux 当发力信号，先读 §8 那条警告。**
2. **流畅度（GIE/jerk）跨路线不可比**，只用于同一条线复爬对比或同人跨时间趋势——
   报告卡里已注明,别拿两条不同线路的数值比高低。

历史两条视频（IMG_6424/6952）的分析产物已清出工作区（2026-07-16）：均可由原视频重建，
CSV 存于 git 历史（`git checkout 14b701f -- <path>` 可取回）。

## 怎么用

### 看账本

双击 `攀岩账本.html` 就行，静态页，不用起任何服务。

### 分析一条新视频

1. 把视频丢进 `收件箱/`
2. 跟 Claude 说一句「分析」

Claude 会判重、跑流水线，**跑的同时在对话里问你**：类型（抱石/顶绳/先锋）、
难度、完攀与否、地点、（野外才问）线路名。答完就归档进 `素材/<片名>/`，
账本页自动刷新。

难度写法：抱石 `V4`，绳索 `5.10b`。两套刻度分开排榜，写混了会认不出来。

手动跑的话：

```bash
python3 climb_intake.py scan                    # 看收件箱有什么、哪些是重复的
python3 climb_intake.py run 收件箱/IMG_7001.MOV  # 跑六步流水线并落位
python3 climb_journal.py && python3 climb_journal_card.py   # 重算账本
```

远景素材（人在画面里很小）加 ROI 参数：

```bash
python3 climb_intake.py run 收件箱/xxx.MOV --roi --seed X,Y [--seed-roi W,H] [--start-s S]
```

`climb_intake.py` 已经把 Windows 三条铁律固化在脚本里，不用自己设环境变量。

**素材库结构（2026-07-17 定稿）：一条线一个文件夹，原片和分析产物放在一起。**

```
素材/IMG_6942/
├── IMG_6942.MOV              原片
├── 攀岩报告卡.html            ← 从这看（一条线就这一张）
├── 报告卡素材/                报告卡里的动作特写
├── 数据/                     3 份 CSV + metrics.json + metrics_v2.json + segments.json
│   └── v1原始/               v1 冻结脚本的副产品（用不到，它必然会生成）
└── 标注视频/                  骨架标注视频 + 分段审阅视频
```

下面是流水线内部的六条命令，`climb_intake.py run` 就是按这个顺序跑的，
需要单独调某一步时才用得上。

```bash
pip install mediapipe==0.10.14 opencv-python numpy matplotlib pillow
V=IMG_6942; D=素材/$V                                  # 改这一行即可换片
python3 climb_pose.py "$D/$V.MOV" "$D/数据"                                    # 视频 → 骨架 CSV
python3 climb_analyze_report.py --dir "$D/数据" --base $V \
    --annotated "$D/数据/${V}_annotated.mp4" --out "$D/数据/v1原始"             # → metrics.json
python3 climb_segments.py "$D/数据/${V}_pose2d.csv"                            # → segments.json
python3 climb_report_v2.py --dir "$D/数据" --base $V --out "$D/数据/v1原始"     # → metrics_v2.json
python3 climb_match.py "$D/数据/${V}_segments.json"                            # → recognition.json
python3 climb_report_card.py --dir "$D/数据" --base $V \
    --video "$D/$V.MOV" --out "$D"                                            # ★ 攀岩报告卡.html
python3 climb_segments_review.py "$D/$V.MOV" "$D/数据/${V}_segments.json" \
    --out "$D/标注视频/${V}_segments_review.mp4"                                # 审阅视频（可选）
```

前五条是**算指标**，各自写自己的 `*.json`；最后 `climb_report_card.py` 只做**展示**，
读那些 json 出唯一那张报告卡。所以改样式不用碰指标，改指标不用碰样式。
中间两条的 `--out` 指到 `数据/v1原始/` 是因为它们会顺手生成各自的旧报告卡——用不到，
但 v1 脚本冻结不能改，只好让它写到角落里。

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
排除。当前素材 6 条常规线（IMG_6152/6321/6411/6417/6418/6942，逐条特性见
[CLAUDE.md](CLAUDE.md) 的验证素材表）+ 1 条远景先锋（六盘水斗牛，走 ROI 流程）。

**远景素材（人在画面里很小）**：标准流程跑不了时改用
`python3 climb_pose_roi.py <视频> <输出目录> --seed X,Y [--seed-roi W,H] [--start-s S]`。
`--seed` 是首帧攀岩者在全画幅的像素坐标；旁边贴着站了第二个人（belayer）时必须加
`--seed-roi`（窄框只框攀岩者），并挑攀岩者站直的时刻 `--start-s`。跑完看
`<base>_roi_track.csv` 和标注视频核对跟踪对象——检出率 100% 不代表跟对了人。
审阅视频里左右肢标错的段：在 `annotations/<base>_side_overrides.json` 写
`[{"t": 秒, "limb": "左手", "note": "..."}]` 后重跑 climb_segments.py 即回流。

### 知识库：浏览 / 重新生成

```bash
open knowledge_base/moves_viewer.html          # 直接浏览（54 动作卡片，可搜索/筛选/看教材页图）
python3 knowledge_base/kb_lint.py              # 校验 moves.json
python3 knowledge_base/kb_render.py            # moves.json 改动后重新生成 viewer
python3 knowledge_base/kb_extract_pages.py     # 重新渲染教材页图（需 brew install poppler）
```

教材 PDF 在 `knowledge_base/` 里，页图存 `knowledge_base/book_pages/`，两者都不入 git。
kb_extract_pages.py 在 `knowledge_base/` 和项目根目录两处都会找 PDF。

## 目录速览

| 路径 | 内容 |
|---|---|
| `PLAN.md` | 总计划 + S1-S10 进度看板（唯一计划真相） |
| `素材/<片名>/` | 一条线一个文件夹：原片 + 报告卡 + 数据 + 图表 + 标注视频（不入 git） |
| `climb_pose.py` / `climb_analyze_report.py` | v1 流水线（冻结不改） |
| `climb_pose_roi.py` | 远景素材 ROI 跟踪取数（输出与 v1 同格式，下游零改动） |
| `climb_segments.py` / `climb_segments_review.py` | S2 分段+换点事件 / 审阅视频生成 |
| `climb_report_v2.py` | S3 节奏指标 v2a + 流畅度 → metrics_v2.json（阈值旋钮集中在文件顶部） |
| `climb_match.py` | S4 动作识别窄版 → recognition.json（只做位置/时序可判的动作） |
| `climb_keyframes.py` | S5 卡点关键帧联络表 + 视觉判定协议（协议在 docstring） |
| `climb_report_card.py` | **合并报告卡**（展示层，读 metrics 出唯一那张 HTML） |
| `climb_journal.py` / `climb_journal_card.py` | **旅程账本**：聚合 → journal.json / 展示 → 攀岩账本.html |
| `climb_intake.py` | 收件箱编排层：判重 + 跑六步流水线 + 落位到 `素材/<片名>/` |
| `收件箱/` | 视频临时投放区，分析完自动搬进 `素材/<片名>/` |
| `素材/<片名>/线路.json` | 手填攀岩信息 sidecar（素材里唯一入 git 的文件） |
| `knowledge_base/` | moves.json + lint/render/extract 脚本 + viewer |
| `annotations/` | 老板人工左右覆写 JSON（不可再生资产，入 git） |
| `_skill_stage/ned-climbing-analysis/` | skill 暂存区（S10 收编） |
| `FreeMoCap-Mac使用指南.md` | 多机位 3D 方案资料（与当前计划无关） |
