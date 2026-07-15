# 攀岩动作识别 + 知识库 + 统计报告（总计划）

> 本文件是跨 session 的唯一计划真相。每个 session 执行前先读本文件，执行后更新「进度看板」。
> 批准时间：2026-07-15。原始计划：~/.claude/plans/pdf-pdf-validated-barto.md（以本文件为准）。

## 进度看板

| # | Session | 状态 | 完成日期 | 验证结果 |
|---|---|---|---|---|
| S1 | 知识库构建（精读 PDF 教材） | ✅ 完成 | 2026-07-15 | lint 通过（54 moves）；老板抽查待确认 |
| S2 | 全身动作分段 | ✅ 完成 | 2026-07-15 | move=16 落在 12-18；调参 K_HI=0.4/K_LO=0.1（PLAN 初值漏检慢速爬升段，已记录）；叠加图与高度曲线吻合；老板人眼核对 10 段边界待确认 |
| S3 | 节奏统计报告 v2a | ⬜ 待做 | | |
| S4 | 特征+规则匹配 | ⬜ 待做 | | |
| S5 | 视觉判定环节 | ⬜ 待做 | | |
| S6 | 标注界面+回流 | ⬜ 待做 | | |
| S7 | 案例参考生效（kNN + few-shot） | ⬜ 待做 | | |
| S8 | 报告卡 v2b（动作序列/构成/缺陷） | ⬜ 待做 | | |
| S9 | 手型视觉识别（按需启动） | ⬜ 待做 | | |
| S10 | skill 收编 | ⬜ 待做 | | |

状态图例：⬜ 待做 / 🔄 进行中 / ✅ 完成 / ⏸ 暂缓

依赖图：S1（第一个执行，老板拍板）；S2→S3；(S1+S2)→S4→{S5,S6}→S7→S8；S9 按需；S10 收尾。

---

## Context

在现有攀岩视频分析流水线（ned-climbing-analysis skill：MediaPipe 骨架提取 → 指标计算 → HTML 报告卡）之上，加三层能力：**动作知识库**（从老板提供的 PDF 教材构建）、**动作识别**（混合路线：骨架规则匹配 → Claude 视觉判定 → 人工标注回流成案例库，越用越准）、**统计报告**（完成速度、动作序列、切换耗时、难点、动作缺陷、休息质量）。

老板已拍板的决策：
- 节奏统计和动作识别**都要，分阶段实现**
- 识别**以身体姿势为主**，手型（crimp/gaston 等）能看就看，看不到之后再做（阶段三）
- 混合识别路线：规则 + 视觉 + 人工标注回流
- **分多个独立 session 执行**，每个 session 有明确输入/产出/验证，用现有 IMG_6952 视频做验证素材
- **S1 知识库先行**

知识库素材：`攀岩技術教本詳細圖解_抓撐轉跳我就是蜘蛛人.pdf`（東秀磯著，161 页，项目根目录）。评估结论：物理原理驱动 + 带量化图解，是理想素材。其分类体系直接沿用为知识库分类：**5 大移动类**（调节平衡/吊挂/推拉/反作用力/动态移动）+ **手顺 4 类**（左右轮流/bump/换手/交叉）+ 手型 13 种（Ch2，阶段三用）+ 脚法踩法（Ch2）。

## 总体架构

```
climb_pose.py ──► CSV ──► climb_segments.py ──► <base>_segments.json
                              │
knowledge_base/moves.json ────┤
cases/cases.json ─────────────┼─► climb_match.py ──► <base>_recognition.json
                              │        │ (中置信度)
                              │        ▼
                              │   climb_keyframes.py ──► 关键帧 → Claude 会话内 Read 看图判定
                              │        │ (仍不确定)
                              │        ▼
                              │   climb_annotate_html.py ──► 标注界面.html → 老板标 → 导出 JSON
                              │        ▼
                              │   climb_merge_annotations.py ──► 更新 recognition.json + cases.json
                              ▼
                    climb_report_v2.py ──► 新版报告卡.html + metrics_v2.json
```

原则：每步幂等、可单独重跑；`recognition.json` 是唯一动作序列真相文件，被 rule/vision/manual 三种来源逐级覆写，每段记 `source` + `confidence`；v1 脚本（climb_pose.py / climb_analyze_report.py）**不动**，保证历史两条视频可比。

## 关键设计决策

### 1. 知识库 schema（knowledge_base/moves.json）

单 JSON 文件，每个动作：`id / name_zh(用书中译名) / aliases / category(沿用书的分类体系) / kind(posture静态|action动态) / book_ref(章节页码) / description / when_to_use / detectability(rule|rule_weak|vision|manual) / pose_rules / visual_cues_for_claude / common_errors / confusable_with`。

- **特征 = 命名特征 + 梯形隶属度区间**：condition 写 `{feature, range:[lo,hi], soft, weight, gate?}`，落区间得 1 分、soft 缓冲带线性衰减。读 PDF 只产出「哪个特征、什么区间、多重要」，规则引擎通用，加新动作零代码。
- `gate:true`（如可见度）不过 → confidence=null（遮挡≠不是该动作）。
- `side:either` 左右镜像各评一次取高者。
- 长度统一用现有 `body_scale`（肩中-髋中距中位数）归一化，与现有代码口径一致。
- posture 类带 `min_hold_s`（最短持续时长）。
- 教材定性为主：量化阈值由 Claude 定初值（书中物理讲解和图解做依据，note 记出处），再用老板视频调参 + 标注回流校准。**预期对齐：知识库是"读书起步、靠标注养准"。**

### 2. 动作分段（climb_segments.py）

从现有「单肢体 count_moves」升级为**全身状态机分段**：
- `allspeed = max(四肢速度)`，滞回二值化（T_hi=mean+1.0σ 进入、T_lo=mean+0.4σ 退出）
- 间隙 <0.4s 合并；合并后 <0.25s 丢弃
- move 段记主导肢体、位移方向/幅度、COM 位移、峰值速度
- **static 段同样输出**——posture 类动作（heel hook、锁定、休息、旗式）发生在静止段，是识别主战场
- 旧 count_moves 口径保留在 metrics.json 不动

### 3. 特征注册表（features.py）

帧级（posture 用，左右成对、身长归一化、y 向上为正）：`ankle_rel_hip_y、knee_rel_hip_y、wrist_rel_shoulder_y、knee/elbow/hip_angle、heel_leads_toe_x、foot_pitch、ankle_cross_midline、feet_spread、hands_gap、wrists_crossed、shoulder_width_ratio（侧身深度代理）、hip_wall_proxy、torso_lean、*_visibility`。
段级（action 用）：主导肢体、位移方向幅度、peak_com_speed、双手同时脱点、段前后髋高变化、段时长。
注：pose2d.csv 已含 heel / foot_index 点，挂脚/toe hook 判定可用。

### 4. 2D 可判性结论（写进知识库 detectability 字段）

- **rule 可判**：高跨步、挂脚 heel hook、直臂悬挂、锁定 lock-off、蹲跳 lunge/dyno、同点 match、交叉手、外撑 stemming、rockover、抖手休息
- **rule_weak 需视觉确认**：挂旗 flag（内/外旗区分靠视觉）、垂膝 drop knee、侧身/twist-lock、toe hook、下壓 mantling、deadpoint
- **vision/manual（阶段三）**：手型 13 种（无手指关键点）、smearing、锁膝 knee bar、campus

### 5. 置信度分层（阈值放 climb_match.py 顶部，验证时用 IMG_6952 调参）

top1 分数 s1、与 top2 差距 margin：
- **高**（s1≥0.75 且 margin≥0.20 且 rule 类）→ 直接采纳 `source:"rule"`
- **中**（0.45≤s1<0.75 或 margin<0.20 或 rule_weak/vision 类）→ 截 3 帧（段起/峰值/段末，原视频帧 + 骨架对照版）→ Claude 会话内 Read 判定，prompt 附规则命中明细 + visual_cues + 案例库 few-shot 图
- **视觉后仍中** 且段时长≥1s 或近 crux → 进人工标注队列
- **低**（s1<0.45 视觉也无候选）→ move 段标 `basic_move`、static 段标 `rest_or_adjust`，不打满屏 unknown

### 6. 标注 HTML（climb_annotate_html.py 生成）

单文件自包含，关键帧 base64 内嵌（每段 3 帧 480px JPEG）。每段一屏：3 帧可放大、Top-3 候选按钮（含分数+命中条件中文解释）、「其它动作…/普通移动/跳过」、备注框；快捷键 1/2/3/0；localStorage 防丢；底部「导出标注」Blob 下载 `<base>_annotations.json`（兜底：复制剪贴板）。老板导出后放 `annotations/` 目录，跑 merge 脚本回流。

### 6.5 已否决方案：教材卡通图跑骨架建 pattern（2026-07-15 实测否决）

MediaPipe 在教材手绘插图上实测：7 个用例（整页+单人裁剪）仅 2 个检出且关节点明显错位（髋部飘到背部等），单人裁剪图反而全部检不出。结论：**量化 pattern 只能来自真实视频的标注回流（见 7. 案例库），书图只做人看 + Claude 视觉判定的参考图**。不要再提议在卡通图上提取骨架特征。

### 7. 案例库（cases/cases.json + cases/keyframes/）

跨视频累积。每条案例：label、side、source(manual>vision)、时间段、**全量特征向量快照**、关键帧路径、老板备注。
- **kNN 校正（规则层自动）**：z-score 欧氏距离 k=3；近邻一致 → 置信 +0.15（封顶 0.95）；与规则 top1 冲突且距离近 → 强制进视觉裁决；案例 <5 条静默不生效
- **few-shot（视觉层）**：视觉判定时附 1-2 张最近邻已确认关键帧

### 8. 新版报告卡（climb_report_v2.py，v1 保留，分两步交付）

**v2a 节奏统计（不依赖识别，S3 交付）**：
- 完成时间：起攀（COM 首次持续上升 >0.3 身长）→ 完攀（COM 达全局最高后保持 >1.5s）
- 切换耗时：每 move 段前 static 段时长 = 准备/犹豫时间，条形图 + 中位数
- 难点：准备时长 >中位数×2.5，或同高度区间反复 move ≥3 次；与 v1 crux 互证，双命中标「确认难点」
- 休息/攀爬占比：static 再分 rest（直臂+低速+>2s）/ adjust，三段占比
- 弯臂检测：静止段肘角持续 <150° 超 2s = 弯臂耗力（高置信硬指标，先只上这类）
- 休息点质量：直臂(+)、脚高髋低(+)、难点前(+)、弯臂(−)、过长>8s(−)

**v2b 动作识别增强（S8 交付）**：
- 动作序列：泳道时间轴（按书的 5 大类着色，static 灰）+ 明细表（时间/动作/来源/置信度）
- 动作构成：各类型计数图（分类沿用书的体系）
- 动作缺陷：知识库 common_errors 逐段跑（挂点过低等），附时间+截帧。只上线高置信少数几条，避免误报

## 分阶段 Session 详情

### 阶段一：知识库 + 节奏统计

| # | Session | 产出 | 验证 | 依赖 |
|---|---|---|---|---|
| S1 | 知识库构建（精读 PDF 教材 Ch3 移动手法脚法 + Ch2 脚法） | knowledge_base/moves.json（姿势类动作，含 book_ref）、kb_lint.py | lint 通过；老板抽查 5 个动作与书对照 | 无 |
| S2 | 全身动作分段 | climb_segments.py、IMG_6952_segments.json、段边界叠加图 | 人眼对照标注视频核对 10 段边界；move 段数落在 12-18 合理区间 | 无 |
| S3 | 节奏统计报告 v2a | climb_report_v2.py（v2a 部分）、IMG_6952 新报告卡 + metrics_v2.json | 老板验收：完成时间/切换耗时/难点/休息占比/弯臂检测与视频观感一致 | S2 |

### 阶段二：动作识别（姿势类）

| # | Session | 产出 | 验证 | 依赖 |
|---|---|---|---|---|
| S4 | 特征+规则匹配 | features.py、climb_match.py、IMG_6952_recognition.json | 抽 8 段核对 top1；高置信准确率 ≥80%；记录调参 | S1+S2 |
| S5 | 视觉判定环节 | climb_keyframes.py、视觉判定协议（写 SKILL.md）、更新 recognition.json | IMG_6952 中置信段实跑一轮 | S4 |
| S6 | 标注界面+回流 | climb_annotate_html.py、climb_merge_annotations.py、标注界面.html、cases.json 首批 | 老板实标一轮→导出→merge 往返测试 | S4 |
| S7 | 案例参考生效 | climb_match.py 加 kNN；视觉 prompt 加 few-shot | 重跑 IMG_6952：已标类型置信提升、人工队列变短 | S6 |
| S8 | 报告卡 v2b（动作序列/构成/缺陷） | climb_report_v2.py 完整版 | 老板验收动作序列与视频一致 | S4（S5-S7 更佳但非必需） |

### 阶段三：手型与增强（后做，按需启动）

| # | Session | 产出 | 说明 |
|---|---|---|---|
| S9 | 手型视觉识别 | 知识库补 Ch2 手型 13 种（纯 vision 类）；关键帧手部放大裁剪；视觉判定协议扩展 | 无骨架特征可用，纯 Claude 看图；先验证单目画质下手型能否看清再决定投入 |
| S10 | skill 收编 | 更新 SKILL.md + scripts/ 同步全部新脚本 | 按 SKILL.md 对 IMG_6952 从零完整重跑全流程 |

## 文件清单

新建（项目根目录）：`knowledge_base/moves.json`、`knowledge_base/kb_lint.py`、`features.py`、`climb_segments.py`、`climb_match.py`、`climb_keyframes.py`、`climb_annotate_html.py`、`climb_merge_annotations.py`、`climb_report_v2.py`、`cases/`、`annotations/`

修改：`_skill_stage/ned-climbing-analysis/SKILL.md` + `scripts/`（S10 时同步）

不动：`climb_pose.py`、`climb_analyze_report.py`

## 关键参照文件

- `climb_analyze_report.py` — 特征/尺度口径、count_moves、crux 逻辑复用来源
- `climb_pose.py` — CSV 列定义与 33 点命名
- `IMG_6952_攀岩动作分析/数据/` — 全程验证素材（pose2d/angles/landmarks CSV + metrics.json）
- `攀岩技術教本詳細圖解_抓撐轉跳我就是蜘蛛人.pdf` — 知识库素材（S1 精读 Ch3 + Ch2 脚法；S9 读 Ch2 手型）
- `_skill_stage/ned-climbing-analysis/SKILL.md` — S10 要更新的工作流文档
