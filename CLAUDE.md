# CLAUDE.md — 攀岩视频动作分析项目

个人项目（Ned/老板的攀岩训练分析），非 EVYD 工作项目。

## 项目是什么

把单机位手机拍的攀岩视频变成动作分析报告：MediaPipe 骨架提取 → 指标计算 → HTML 报告卡（已有，v1，对应 skill `ned-climbing-analysis`）。正在扩展三层新能力：**动作知识库**（从 PDF 教材构建）+ **动作识别**（规则匹配 → Claude 视觉判定 → 人工标注回流）+ **节奏/缺陷统计报告 v2**。

## 开始工作前必读

1. **先读 [PLAN.md](PLAN.md)** —— 跨 session 的唯一计划真相：总体架构、全部设计决策、S1-S10 session 划分与进度看板。
2. 老板说「继续」「做 S{n}」时，按 PLAN.md 对应 session 的 目标/产出/验证 执行。
3. **每个 session 结束时更新 PLAN.md 进度看板**（状态/日期/验证结果），并 git commit。

## 硬约定

- `climb_pose.py`、`climb_analyze_report.py`（v1 流水线）**不要改**——保证历史视频结果可比。新能力全部走新文件。
- `<base>_recognition.json` 是动作序列的唯一真相文件，rule/vision/manual 三种来源逐级覆写，每段必须带 `source` + `confidence`。
- 长度/速度统一用 `body_scale`（肩中-髋中距中位数）归一化，与 v1 口径一致。
- 大文件（视频/PDF/report_assets 图）不入 git，见 .gitignore。
- 验证素材固定用 `IMG_6952_攀岩动作分析/数据/` 下的 CSV。
- 知识库动作分类沿用教材体系（5 大移动类 + 手顺 4 类），动作中文名用书中译名，记 `book_ref` 页码。
- **教材 PDF 页码换算：PDF 文件页 = 书本印刷页 + 2**（封面+版权页无编号，2026-07-15 实测校验）。book_ref 记的是印刷页。
- mediapipe 必须用 **0.10.14**（≥0.10.2x 移除了 `mp.solutions` 旧 API，v1 脚本会挂）。
- **MediaPipe 左右标签**：多数时候正确（IMG_6952 实测 12/15 段），但扭身/遮挡时会**整臂/整腿认错人**，且无启发式能可靠识别错误段（全局镜像互换、几何 x 判定、肩朝向、骨架链距离四种方案 2026-07-16 均实测否决——全局互换会把对的弄反）。定案：**标签默认可信 + 老板核对的错误段走 `annotations/<base>_side_overrides.json` 人工覆写**（source=manual），深度扭身段自动标 `side_confidence=low`。首尾 0.25s 速度有平滑边缘伪影，`climb_segments.py` 已钳制。
- moves.json 改动后跑 `kb_lint.py` 校验 + `kb_render.py` 重新生成 viewer。

## 目录结构

```
climb_pose.py / climb_analyze_report.py   v1 流水线（勿动）
PLAN.md                                    总计划 + 进度看板
攀岩技術教本詳細圖解_*.pdf                  知识库素材（東秀磯，161页）
knowledge_base/                            moves.json + lint/render/extract 脚本 + moves_viewer.html（S1 产出）
cases/                                     标注案例库（跨视频累积）
annotations/                               老板导出的标注 JSON 收纳
IMG_6424_攀岩动作分析/ IMG_6952_攀岩动作分析/  已有两条视频的 v1 分析结果
_skill_stage/ned-climbing-analysis/        skill 暂存区（S10 收编时同步）
FreeMoCap_import/ FreeMoCap-Mac使用指南.md  多机位 3D 方案资料（与本计划无关）
```

## 汇报口吻

完成后给老板：先结论、再 3-5 个关键数字、最后文件位置。不堆术语。
