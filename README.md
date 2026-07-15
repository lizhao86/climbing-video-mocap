# 攀岩视频动作分析

把单机位手机拍的攀岩视频变成动作分析报告：MediaPipe 骨架提取 → 指标计算 → HTML 报告卡（v1 已可用），正在扩展动作知识库 + 动作识别 + 节奏/缺陷统计报告 v2（进度见 [PLAN.md](PLAN.md) 看板）。

## 现状（2026-07-15）

- **v1 流水线**：可用。`climb_pose.py`（视频→骨架 CSV）+ `climb_analyze_report.py`（CSV→HTML 报告卡），已分析 IMG_6424 / IMG_6952 两条视频。
- **S1 动作知识库**：已完成。从教材《攀岩技術教本詳細圖解》（東秀磯）提炼 54 个动作，含分类/可判性/骨架规则/视觉线索/教材页码。
- S2-S10（动作分段、规则匹配、视觉判定、标注回流、报告 v2）：待做。

## 怎么用

### v1：分析一条新视频

```bash
pip install mediapipe==0.10.14 opencv-python numpy matplotlib
python3 climb_pose.py <视频路径> <输出目录>
python3 climb_analyze_report.py <输出目录>
```

注意 mediapipe 要 0.10.14（≥0.10.2x 移除了 `mp.solutions` 旧 API，脚本会报错）。

### 知识库：浏览 / 重新生成

```bash
open knowledge_base/moves_viewer.html          # 直接浏览（54 动作卡片，可搜索/筛选/看教材页图）
python3 knowledge_base/kb_lint.py              # 校验 moves.json
python3 knowledge_base/kb_render.py            # moves.json 改动后重新生成 viewer
python3 knowledge_base/kb_extract_pages.py     # 重新渲染教材页图（需 brew install poppler）
```

教材页图存 `knowledge_base/book_pages/`，不入 git，缺了跑上面最后一条命令即可重建。

## 目录速览

| 路径 | 内容 |
|---|---|
| `PLAN.md` | 总计划 + S1-S10 进度看板（唯一计划真相） |
| `climb_pose.py` / `climb_analyze_report.py` | v1 流水线（冻结不改） |
| `knowledge_base/` | moves.json + lint/render/extract 脚本 + viewer |
| `IMG_*_攀岩动作分析/` | 两条视频的 v1 分析结果 |
| `cases/` `annotations/` | 标注案例库（S6 起启用） |
| `攀岩技術教本詳細圖解_*.pdf` | 知识库素材（不入 git） |
| `_skill_stage/ned-climbing-analysis/` | skill 暂存区（S10 收编） |
| `FreeMoCap_import/` | 多机位 3D 方案资料（与当前计划无关） |
