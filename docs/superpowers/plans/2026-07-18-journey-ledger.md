# J1 旅程账本首版 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 扫全部现有素材文件夹出一张「攀岩账本.html」——门面是累计数字，每条线一条记录，可点进对应报告卡。

**Architecture:** 沿用项目分层硬约定：`climb_journal.py`（聚合层）扫 `素材/*/数据/*_metrics_v2.json` + 手填 sidecar `线路.json` → `素材/journal.json`；`climb_journal_card.py`（展示层）只读 journal.json → 项目根「攀岩账本.html」（暗色、内联 SVG，与报告卡一脉）。v1/v2 流水线零改动。

**Tech Stack:** Python 3.10（C:\venvs\climb310）、ffprobe（读拍摄日期）、纯 HTML/CSS/内联 SVG（无外部依赖）。

**设计依据:** PLAN.md §10 + ~/.claude/plans/1-2-mellow-tome.md（2026-07-18 脑暴定案，老板逐项拍板）。

---

## 调研结论（2026-07-18 实测，设计以此为准）

- 7 条素材（IMG_6152/6321/6411/6417/6418/6942/六盘水斗牛）`metrics_v2.json`、`segments.json`、`recognition.json` 全齐。
- 六盘水缺 v1 `metrics.json` 和合并「攀岩报告卡.html」→ 账本记录必须容忍无报告卡（显示但不给链接）。
- **文件 mtime 不可靠**：IMG_6321/6411/6942 mtime 同为 2026-06-19 15:02（拷贝时间）。ffprobe 能读到真实拍摄日期（`com.apple.quicktime.creationdate` 带 +0800 时区，最准；实测 6152=2026-03-29、6942=2026-06-17、六盘水=2026-06-27）。
- 聚合基数（人工核对基准）：7 条记录；Σclimb_time = 26.4+53.2+29.6+14.2+27.4+29.7+1634.9 = 1815.4s；Σnet_gain = 3.96+8.15+2.98+4.00+4.49+3.41+18.01 = 45.00bl；Σevents = 27+38+28+44+58+23+533 = 751；动作 hi/med 计数 = 5+0+9+2+5+1+9 = 31。

## 关键设计决策

### 1. 线路.json（sidecar，老板手填，每条几秒）

路径 `素材/<片名>/线路.json`，UTF-8，中文键名（老板手填友好）。全部字段可空：

```json
{
  "线路名": "",
  "岩馆": "",
  "难度": "",
  "完攀": null,
  "日期": "",
  "备注": ""
}
```

- `难度`：自由文本（"V4" / "5.10b"），账本原样展示 + 完攀难度计数。
- `完攀`：true/false/null（null=未填）。
- `日期`："YYYY-MM-DD"，留空走自动回退。
- `线路名`：给未来同线对比（进步类）留的钩子，首版只存不用。
- `climb_journal.py --init` 为缺 sidecar 的素材文件夹生成上述模板，不覆盖已有文件。
- **入 git**（手填不可再生，与 annotations/ 同理）→ Task 3 改 .gitignore。

### 2. 账本配置.json（项目根，填一次）

```json
{ "身高_m": null }
```

定案：累计爬升米数 = 身长(bl) × 老板身高。`身高_m` 为 null 时账本降级显示「X.X 身长」，填了显示米。入 git。脚本缺文件时自动生成模板。

### 3. 日期解析优先级（写进 journal 每条记录的 `date_source`）

1. `线路.json` 的 `日期`（source=`manual`）
2. ffprobe `com.apple.quicktime.creationdate`（source=`metadata`，取本地日期部分）
3. ffprobe `creation_time`（UTC，+8h 转本地日）
4. 文件 mtime（source=`mtime`，账本页此类日期标「?」提示可疑）

### 4. journal.json 口径（素材/journal.json，可重建不入 git）

每条记录（来源注明）：
- `base`、`dir`（相对项目根）、`date` + `date_source`
- 手填透传：`route_name / gym / grade / sent / note`
- `video_duration_s`、`climb_time_s`（completion.climb_time_s）、`net_gain_bl`（completion.net_gain_bl）
- `n_events`（segments.json n_events，= 出手/出脚换点次数）
- `n_crux`（metrics_v2 crux.n）
- `moves`：recognition.json 中 confidence ∈ {high, medium} 的按 `move_id` 计数（与报告卡「动作记录」同口径，conf≥medium 才陈列）
- `report_card`：`素材/<片名>/攀岩报告卡.html` 存在则记相对路径，否则 null

totals（账本门面）：
- 打卡类：`n_routes`、`n_days`（去重日期数）、`n_this_month`（当月记录数）、`streak_weeks`（含最近记录的 ISO 周往回连续有记录的周数）
- 积累类：`total_climb_time_s`、`total_gain_bl`（身高非空时另出 `total_gain_m`）、`total_events`
- 动作收集类：`moves_collect`（各 move_id 全库累计 + name_zh + book_ref）
- 荣誉类：`sent_by_grade`（完攀==true 的按难度计数；难度空的归「未填」不计入）
- `this_month` 同结构小计

### 5. 页面信息层级（攀岩账本.html，项目根）

暗色与报告卡一脉。**不出现 v1/v2a 等代号；行文简洁用词简单（CLAUDE.md 汇报口吻）**。

1. 门面横幅「你的攀岩」：大数字——总条数 / 累计爬升 / 在墙总时间 / 累计出手 / 连续周数
2. 本月小结：本月条数 + 本月完攀难度
3. 动作收集：6 动作卡片（中文名 + 累计次数 + 书页码），0 次的显示灰色「待解锁」
4. 时间轴：内联 SVG，按日期一条线一根柱（高度=净爬升），悬浮显示片名
5. 记录列表：每条一行卡片——日期 / 片名(或线路名) / 岩馆 / 难度 / 完攀✓ / 爬升 / 用时 / 卡点数；有报告卡的整行可点，无报告卡的标「未生成报告卡」
6. 页脚注：日期来源为 mtime 的标注「日期按文件时间推断，可在 线路.json 填写核正」

已知口径限制照实呈现，不粉饰：六盘水是 28 分钟反复磨线，用时/出手数照实累计；横移线只统计到最高点。这些不在账本页解释（详情页的事），但绝不写成「完攀 27 分钟」这类误导文案——记录行只陈列数字不下结论。

---

### Task 1: climb_journal.py（聚合层）

**Files:**
- Create: `climb_journal.py`

- [ ] **Step 1: 实现脚本**。顶部旋钮区（项目惯例）：`MATERIAL_DIR="素材"`、`CONFIG="账本配置.json"`、`SIDECAR="线路.json"`、`OUT="素材/journal.json"`、`CONF_OK={"high","medium"}`。功能：`--init` 生成缺失 sidecar 模板与账本配置模板后退出；默认跑聚合。全部 `open(..., encoding="utf-8")`（Windows GBK 坑）。ffprobe 失败静默回退 mtime。
- [ ] **Step 2: 跑 `--init`**，确认 7 个素材文件夹各生成一份 线路.json 模板、根目录生成 账本配置.json。
- [ ] **Step 3: 跑聚合**，用调研结论的基数核对：n_routes=7、Σclimb_time≈1815.4s、Σgain≈45.00bl、Σevents=751、动作计数合计=31、六盘水 report_card=null 其余 6 条非空。
- [ ] **Step 4: Commit**（连同 .gitignore 改动见 Task 3，可并入一次 commit 或分开）。

### Task 2: climb_journal_card.py（展示层）

**Files:**
- Create: `climb_journal_card.py`

- [ ] **Step 1: 实现脚本**：读 `素材/journal.json` → 写项目根 `攀岩账本.html`。自包含单文件、无外部资源；SVG 内联；报告卡链接用相对路径（html 在根，链接 `素材/<片名>/攀岩报告卡.html`）。
- [ ] **Step 2: 生成并用浏览器打开验证**：五个层级都渲染；点一条记录能打开对应报告卡；六盘水行无链接；日期 mtime 的有「?」标注。
- [ ] **Step 3: Commit**。

### Task 3: .gitignore 让 线路.json 入 git

**Files:**
- Modify: `.gitignore`（`素材/` 一节）

- [ ] **Step 1: 改写**：

```gitignore
# 素材库：…（原注释保留）
# 例外：线路.json 是老板手填元数据，不可再生，入 git（2026-07-18 账本层）
素材/**
!素材/*/
!素材/*/线路.json
```

同节确认 `journal.json`（在 素材/ 下，天然被忽略）与根目录 `攀岩账本.html` 的忽略（新增一行 `攀岩账本.html`，可重建不入 git）。
- [ ] **Step 2: 验证**：`git check-ignore -v 素材/IMG_6942/IMG_6942.MOV`（仍忽略）、`git status` 里 7 份 线路.json 出现为未跟踪。
- [ ] **Step 3: Commit**（与 Task 1 产物一起）。

### Task 4: 验收 + 知识同步

- [ ] **Step 1: 对照 J1 验收标准**（PLAN.md §10 预告）：扫全部现有素材出一张账本页 ✓；打卡/积累两类数字与素材清单人工核对一致 ✓（Task 1 Step 3 的基数核对）；每条记录可点进对应报告卡 ✓（六盘水例外，因其本无报告卡，如实标注）。
- [ ] **Step 2: 更新 PLAN.md**：进度看板 J1 行改「🔄 待老板验收」+ 日期 + 验证结果摘要；§10 架构段补实际文件名。
- [ ] **Step 3: 更新 CLAUDE.md 目录结构**（加 climb_journal.py / climb_journal_card.py / 账本配置.json 三行）。
- [ ] **Step 4: git commit 收尾**。

## Self-Review 备注

- 定案四类门面数字全覆盖：打卡（n_days/n_this_month/streak_weeks）、积累（time/gain/events）、动作收集（moves_collect）、进步类按定案「等素材出现同线重复爬」跳过，仅留 `线路名` 钩子。
- 分层硬约定不破：聚合层出 json、展示层只读 json；v1 冻结脚本零接触。
- 老板待办（账本页与汇报里都要提）：往 7 份 线路.json 里填难度/完攀/岩馆，往 账本配置.json 填身高——填完重跑两个脚本数字自动升级。
