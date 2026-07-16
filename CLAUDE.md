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
- **指标与展示分层**（2026-07-17 定）：`climb_analyze_report.py` / `climb_segments.py` /
  `climb_report_v2.py` 各自只产出 `*.json`（metrics.json / segments.json / metrics_v2.json），
  它们是**产出契约**；`climb_report_card.py` 是唯一的展示层，读 json 出唯一那张
  「攀岩报告卡.html」。**改样式不碰指标，改指标不碰样式。** 老板 2026-07-17：
  「报告卡干嘛不合并」——v1/v2a 是开发阶段代号，不该漏到用户面前。
- **写图不能用 `cv2.imwrite`**：Windows 上遇到非 ASCII 路径**静默失败**（返回 False、
  不抛异常、不留文件；本项目路径含「我的代码」「素材」，必中）。v1 的
  climb_analyze_report.py 就栽在这——它的 5 张 crux 截图从来没落盘，报告卡里一直是裂图。
  用 `cv2.imencode` + Python `open(...,'wb')`，并检查返回值。**注意 `cv2.VideoCapture`
  读非 ASCII 路径是正常的**（走 FFmpeg 后端），只有 imwrite/imread 有这个坑。
- `<base>_recognition.json` 是动作序列的唯一真相文件，rule/vision/manual 三种来源逐级覆写，每段必须带 `source` + `confidence`。
- 长度/速度统一用 `body_scale`（肩中-髋中距中位数）归一化，与 v1 口径一致。
- 大文件（视频/PDF/report_assets 图）不入 git，见 .gitignore。
- **验证素材（2026-07-16 更新）**：历史两条视频（IMG_6424/6952）的目录已整体清出工作区（老板决定：均可由视频重建，不留副本）。旧 CSV 在 git 历史中，`git checkout 14b701f -- "IMG_6952_攀岩动作分析/数据/IMG_6952_pose2d.csv"` 可取回。S3 起的验证素材=老板届时提供的新视频，用 v1 流水线现跑；`annotations/` 的人工覆写与旧视频绑定，新视频需重新核对。
- 教材 PDF 线下保管（另一台机器），不在本机工作区；kb_extract_pages.py 需要时先放回根目录。
- 知识库动作分类沿用教材体系（5 大移动类 + 手顺 4 类），动作中文名用书中译名，记 `book_ref` 页码。
- **教材 PDF 页码换算：PDF 文件页 = 书本印刷页 + 2**（封面+版权页无编号，2026-07-15 实测校验）。book_ref 记的是印刷页。
- mediapipe 必须用 **0.10.14**（≥0.10.2x 移除了 `mp.solutions` 旧 API，v1 脚本会挂）。
- **Windows 上跑流水线的三条铁律（2026-07-16 首次在 Windows 跑通，逐条实测）**：
  1. **venv 必须建在纯 ASCII 路径**（本机 `C:\venvs\climb310`，Python 3.10）。项目路径含
     「我的代码」，mediapipe 无法从非 ASCII 路径加载模型，报 `FileNotFoundError:
     pose_landmark_cpu.binarypb`（文件其实存在）。项目代码留在原地没关系，只有 mediapipe
     包所在路径必须 ASCII。
  2. **跑 climb_pose.py 必须设 `CLIMB_ROTATE=0`**。OpenCV 在 Windows（FFmpeg 后端）默认
     自动应用旋转元数据（`CAP_PROP_ORIENTATION_AUTO=1`，4.10/5.0 都是），而脚本按 Mac
     行为（AVFoundation 后端不自动转）写了自己的手动转正 → **画面被转两次，人是躺着的**。
     后果极隐蔽：**检出率仍 100%**，但「重心高度」量的是水平方向，41s 的爬升会被算成
     2.6s 完攀。降 opencv 版本无用（4.10 也自动转）。数字荒谬时先怀疑上游数据方向。
  3. **设 `PYTHONUTF8=1 PYTHONIOENCODING=utf-8`**。v1 脚本的 `open(...,"w")` 没指定
     encoding，Windows 默认 GBK 写不了报告卡里的 `▸`；print 的 emoji 同理撞控制台 GBK。
  标准前缀：`PYTHONUTF8=1 PYTHONIOENCODING=utf-8 CLIMB_MAX_W=960 CLIMB_ROTATE=0
  /c/venvs/climb310/Scripts/python.exe climb_pose.py <视频> <输出目录>`
- **验证素材的隐性要求（S3 踩坑总结）**：① 全程不能有路人从镜头前走过——MediaPipe Pose
  只跟一个人，会跟错（已弃用的 IMG_6947 在 13-16s 就是，**检出率 98% 完全掩盖了这个问题**——
  检出率高 ≠ 跟对了人）；② 攀岩者不能爬出画面（IMG_6947 30s 后只剩腿在框内，重心用残缺
  骨架算）；③ 视频开头若含「走向岩壁」没关系，v2a 有上墙门会排除（见 PLAN.md §8）。
  **当前验证素材：`素材/IMG_6942/`（41s，含走近段）+ `素材/IMG_6152/`（31s，一上来就在
  墙上）。IMG_6947 因上述污染已被老板删除（2026-07-17），勿再引用。**
- **素材库结构（2026-07-17 老板定稿）：一条线一个文件夹 `素材/<片名>/`，原片 `<片名>.MOV`
  和全部分析产物（报告卡 / 数据/ / report_assets*/ / 标注视频/）都放在里面**，不再把视频和
  产物分开摆。整个 `素材/` 不入 git（原片大、产物可由原片复跑重建）。用法见 README。
- **MediaPipe 左右标签**：多数时候正确（IMG_6952 实测 12/15 段），但扭身/遮挡时会**整臂/整腿认错人**，且无启发式能可靠识别错误段（全局镜像互换、几何 x 判定、肩朝向、骨架链距离四种方案 2026-07-16 均实测否决——全局互换会把对的弄反）。定案：**标签默认可信 + 老板核对的错误段走 `annotations/<base>_side_overrides.json` 人工覆写**（source=manual），深度扭身段自动标 `side_confidence=low`。首尾 0.25s 速度有平滑边缘伪影，`climb_segments.py` 已钳制。
- moves.json 改动后跑 `kb_lint.py` 校验 + `kb_render.py` 重新生成 viewer。

## 目录结构

```
climb_pose.py / climb_analyze_report.py   v1 流水线（勿动）
climb_segments.py                          S2 分段+换点事件（锚点位移法，参数旋钮在顶部）
climb_segments_review.py                   审阅视频生成（老板验收用，烧字幕）
PLAN.md                                    总计划 + 进度看板
knowledge_base/                            moves.json + lint/render/extract 脚本 + moves_viewer.html（S1 产出）
cases/                                     标注案例库（跨视频累积，S6 起）
annotations/                               人工左右覆写 JSON（不可再生，入 git）
_skill_stage/ned-climbing-analysis/        skill 暂存区（S10 收编时同步）
FreeMoCap_import/ FreeMoCap-Mac使用指南.md  多机位 3D 方案资料（与本计划无关）

（教材 PDF 线下保管；历史视频分析目录 2026-07-16 已清出，见「验证素材」条款）
```

## 汇报口吻

完成后给老板：先结论、再 3-5 个关键数字、最后文件位置。不堆术语。
