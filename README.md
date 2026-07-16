# 攀岩视频动作分析

把单机位手机拍的攀岩视频变成动作分析报告：MediaPipe 骨架提取 → 指标计算 → HTML 报告卡（v1 已可用），正在扩展动作知识库 + 动作识别 + 节奏/缺陷统计报告 v2（进度见 [PLAN.md](PLAN.md) 看板）。

## 现状（2026-07-16）

- **v1 流水线**：可用。`climb_pose.py`（视频→骨架 CSV）+ `climb_analyze_report.py`（CSV→HTML 报告卡）。
- **S1 动作知识库**：已完成。从教材《攀岩技術教本詳細圖解》（東秀磯）提炼 54 个动作，含分类/可判性/骨架规则/视觉线索/教材页码。
- **S2 全身动作分段**：已完成。`climb_segments.py` 锚点位移法——手/脚末端净位移 ≥0.5 身长判"真换点"，输出 move/static 段 + 肢体换点事件两层；`climb_segments_review.py` 生成烧字幕审阅视频供人眼验收。IMG_6952 人眼零漏检，IMG_6424 零改参泛化通过。
- S3-S10（节奏统计、规则匹配、视觉判定、标注回流、报告 v2）：待做。
- 历史两条视频（IMG_6424/6952）的分析产物已清理出工作区（2026-07-16）：均可由原视频一键重建，CSV 亦存于 git 历史（`git checkout 14b701f -- <path>` 可取回）。

## 怎么用

### 分析一条新视频（v1 报告卡 + S2 分段）

```bash
pip install mediapipe==0.10.14 opencv-python numpy matplotlib pillow
python3 climb_pose.py <视频路径> <输出目录>            # 视频 → 骨架 CSV
python3 climb_analyze_report.py <输出目录>             # v1 HTML 报告卡
python3 climb_segments.py <输出目录>/<base>_pose2d.csv  # S2 分段+换点事件
python3 climb_segments_review.py <视频路径> <输出目录>/<base>_segments.json  # 审阅视频
```

注意 mediapipe 要 0.10.14（≥0.10.2x 移除了 `mp.solutions` 旧 API，脚本会报错）。
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
| `climb_pose.py` / `climb_analyze_report.py` | v1 流水线（冻结不改） |
| `climb_segments.py` / `climb_segments_review.py` | S2 分段+换点事件 / 审阅视频生成 |
| `knowledge_base/` | moves.json + lint/render/extract 脚本 + viewer |
| `annotations/` | 老板人工左右覆写 JSON（不可再生资产，入 git） |
| `cases/` | 标注案例库（S6 起启用） |
| `_skill_stage/ned-climbing-analysis/` | skill 暂存区（S10 收编） |
| `FreeMoCap_import/` | 多机位 3D 方案资料（与当前计划无关） |
