#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""climb_match.py —— 动作识别·窄启动版（B 路线，2026-07-18）

只做「位置/时序信号可判」的 6 个动作——这是深度调研后的刻意收缩
（docs/2026-07-18-指标价值review与路线决策.md §四）：54 个动作里 rule 级只有 9 个，
且全靠位置/时序（单目可信区）；依赖角度/朝向的 19 个 rule_weak 不做规则（会批量产出
噪声结论），留给视觉判定。脚部信号可信度远高于手（单目实测脚 92-95% vs 手 76-80%）。

识别（按证据强度排）：
  high_step  高跨步    脚事件落点接近髋高。RCT 里唯一被证明视频反馈显著有效的动作，
                        且靠脚部信号——本清单里教练价值证据最硬的一个。
  match      同點      一手到位后另一手在短窗内到达同一位置（两手同时在）。
  hand_change 換手     一手离开某位置后另一手接管该位置（先后替换）。
  cross      交叉手    出手落点越过另一只手（画面 x 交叉；素材约定人背对相机）。
  heel_hook  掛腳      脚高 + 脚跟高于脚尖（heel/toe 关键点噪声大 → 只给 low）。
  hand_sequence 手顺   左右轮流 vs 连抓的全程统计（教材：左右輪流是基本手顺）。

输入：segments.json（换点事件）+ pose2d.csv（关键点轨迹）
输出：<base>_recognition.json —— 动作序列唯一真相文件（CLAUDE.md 硬约定：
      rule/vision/manual 三源逐级覆写，每条带 source + confidence）。
      本脚本只写 source=rule；vision/manual 由后续环节覆写。

用法：python3 climb_match.py <segments.json> [--pose2d <csv>] [--out <json>]
"""
import csv, json, os, sys, argparse
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import numpy as np

# ── 旋钮（位置阈值全部以身长 bl 为单位）──────────────────────────────
MATCH_DIST   = 0.35   # 同点/换手：两手位置差小于此值算「同一个点」。岩点间距通常 >0.5bl
MATCH_WIN_S  = 3.0    # 同点：第二只手需在第一只手到位后此窗口内到达
CHANGE_WIN_S = 2.5    # 换手：接管手需在离开手撤出后此窗口内到达
CROSS_MARGIN = 0.15   # 交叉手：左腕画面 x 需超过右腕此幅度才算真交叉（滤噪声抖动）
                      # ⚠️ 前提：人背对相机（解剖左手在画面左侧）。当前素材全部满足。
CROSS_HOLD_S = 0.8    # 交叉手需在落定后持续此秒数（取窗口中位）——单帧判定会被
                      # MediaPipe 左右认错污染，实测产出过画面上不存在的交叉
HIGH_STEP_GAP = 0.35  # 高跨步：落脚时该脚踝距髋中垂直落差 < 此值（正常踩点 0.9-1.0bl）
HEEL_UP_MIN  = 0.03   # 掛腳：脚跟需高于脚尖此幅度（bl）。heel/toe 点噪声大，阈值给松
VIS_FOOT     = 0.30   # 脚部关键点可见度门槛

KB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "knowledge_base", "moves.json")
# 识别 id → 知识库中文名（用于带出 book_ref；查不到不挡输出）
KB_NAME = {"high_step": "高跨步", "match": "同點（Match）", "cross": "交叉手（Cross Move）",
           "hand_change": "換手（Change）", "heel_hook": "掛腳（Heel Hook）",
           "alternating": "左右輪流"}


def load_csv(p):
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def col(rows, name):
    o = []
    for r in rows:
        try:
            o.append(float(r.get(name, "")))
        except Exception:
            o.append(np.nan)
    return np.array(o)


def book_refs():
    try:
        kb = json.load(open(KB_PATH, encoding="utf-8"))
        moves = kb["moves"] if "moves" in kb else kb
        return {m.get("name_zh"): m.get("book_ref") for m in moves}
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("segments")
    ap.add_argument("--pose2d", default=None)
    ap.add_argument("--out", default=None)
    A = ap.parse_args()

    S = json.load(open(A.segments, encoding="utf-8"))
    base = S["base"]
    d = os.path.dirname(os.path.abspath(A.segments))
    p2_path = A.pose2d or os.path.join(d, f"{base}_pose2d.csv")
    out_path = A.out or os.path.join(d, f"{base}_recognition.json")
    rows = load_csv(p2_path)
    t = col(rows, "time_s")
    bl = S["body_scale"]

    def pt(n):
        """(N,2)，画面坐标系（y 向下），除以 body_scale 归一。"""
        return np.vstack([col(rows, f"{n}_nx"), col(rows, f"{n}_ny")]).T / bl

    def vis(n):
        return col(rows, f"{n}_vis")

    LW, RW = pt("left_wrist"), pt("right_wrist")
    hip = (pt("left_hip") + pt("right_hip")) / 2

    def idx(ts):
        return int(np.clip(np.searchsorted(t, ts), 0, len(t) - 1))

    def wrist_at(side, ts):
        return (LW if side == "left_wrist" else RW)[idx(ts)]

    events = S["events"]
    hands = [e for e in events if e["joint"] in ("left_wrist", "right_wrist")]
    feet = [e for e in events if e["joint"] in ("left_ankle", "right_ankle")]
    moves_out = []
    refs = book_refs()

    def emit(mid, ts, limb, conf, evidence):
        name = KB_NAME[mid]
        moves_out.append({
            "t_s": round(ts, 2), "limb": limb, "move_id": mid,
            "name_zh": name, "book_ref": refs.get(name),
            "source": "rule", "confidence": conf, "evidence": evidence})

    # ── 同点 / 换手 / 交叉手（手事件的位置时序关系）──────────────────
    for i, e in enumerate(hands):
        side, other = e["joint"], ("right_wrist" if e["joint"] == "left_wrist" else "left_wrist")
        p_end = wrist_at(side, e["end_s"])          # 这次出手的落点
        if np.isnan(p_end).any():
            continue
        # 同点：落点与另一只手当前位置几乎重合（另一手没在动）
        p_other = wrist_at(other, e["end_s"])
        other_moving = any(o["joint"] == other and o["start_s"] < e["end_s"] < o["end_s"]
                           for o in hands)
        if (not other_moving and not np.isnan(p_other).any()
                and np.linalg.norm(p_end - p_other) < MATCH_DIST):
            emit("match", e["end_s"], e["limb"], "high",
                 {"dist_bl": round(float(np.linalg.norm(p_end - p_other)), 2)})
            continue                                 # 同点了就不再判交叉
        # 换手：这次落点 ≈ 另一只手刚离开的位置
        for o in hands[:i][::-1]:
            if o["joint"] != other:
                continue
            if not (0 <= e["end_s"] - o["end_s"] <= CHANGE_WIN_S + (e["end_s"] - e["start_s"])):
                break
            p_left_from = wrist_at(other, o["start_s"])   # 对方离开前占着的位置
            if (not np.isnan(p_left_from).any()
                    and np.linalg.norm(p_end - p_left_from) < MATCH_DIST):
                emit("hand_change", e["end_s"], e["limb"], "medium",
                     {"took_over_from": o["limb"], "dist_bl":
                      round(float(np.linalg.norm(p_end - p_left_from)), 2)})
            break
        # 交叉手：落点越过另一只手（背对相机：解剖左手画面 x 更小为正常位）。
        # ⚠️ 不能拿单帧判（2026-07-18 抽帧核对翻车：IMG_6152@18.9 报了 cross，画面里
        # 两手根本没交叉——MediaPipe 整臂认错左右是已知问题，单帧必被它污染）。
        # 改为出手落定后 CROSS_HOLD_S 窗口内的**中位**交叉量，交叉得持续才算。
        i0c, i1c = idx(e["end_s"]), idx(e["end_s"] + CROSS_HOLD_S)
        if i1c > i0c + 2:
            lxs, rxs = LW[i0c:i1c + 1, 0], RW[i0c:i1c + 1, 0]
            with np.errstate(invalid="ignore"):
                med_overlap = float(np.nanmedian(lxs - rxs))
            if np.isfinite(med_overlap) and med_overlap > CROSS_MARGIN:
                # conf=low 定死（2026-07-18 抽验 2 例：1 例画面无交叉（单帧标签错，已改
                # 中位窗），1 例画面与肘角证据矛盾（疑窗口内标签翻转）。交叉判定的命门
                # 正是左右标签，而标签错误无启发式可靠识别（CLAUDE.md）——precision
                # 未达标，**展示层不应采用 low**，留给视觉判定环节确认后升级。
                emit("cross", e["end_s"], e["limb"], "low",
                     {"overlap_med_bl": round(med_overlap, 2),
                      "held_s": CROSS_HOLD_S})

    # ── 高跨步 / 掛腳（脚事件；脚部信号是单目可信区）────────────────
    HL, HR = pt("left_heel"), pt("right_heel")
    TL, TR = pt("left_foot_index"), pt("right_foot_index")
    AL, AR = pt("left_ankle"), pt("right_ankle")
    for e in feet:
        side = e["joint"]
        i1 = idx(e["end_s"])
        ank = (AL if side == "left_ankle" else AR)[i1]
        if np.isnan(ank).any() or np.isnan(hip[i1]).any():
            continue
        gap = float(ank[1] - hip[i1][1])            # 画面 y 向下：正 = 脚在髋下方
        if gap < HIGH_STEP_GAP:
            hs_conf = "high" if vis(side)[i1] >= VIS_FOOT else "medium"
            emit("high_step", e["end_s"], e["limb"], hs_conf,
                 {"ankle_below_hip_bl": round(gap, 2)})
        heel = (HL if side == "left_ankle" else HR)[i1]
        toe = (TL if side == "left_ankle" else TR)[i1]
        if (not np.isnan(heel).any() and not np.isnan(toe).any()
                and gap < 0.7 and toe[1] - heel[1] > HEEL_UP_MIN):
            emit("heel_hook", e["end_s"], e["limb"], "low",
                 {"heel_above_toe_bl": round(float(toe[1] - heel[1]), 2),
                  "ankle_below_hip_bl": round(gap, 2)})

    moves_out.sort(key=lambda m: m["t_s"])

    # ── 手顺统计（全程一条）────────────────────────────────────────
    seq = [e["joint"] for e in hands]
    alt = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
    repeats = []
    for a, b in zip(hands, hands[1:]):
        if a["joint"] == b["joint"]:
            repeats.append({"limb": a["limb"], "t1_s": a["end_s"], "t2_s": b["end_s"]})
    hand_seq = {
        "n_hand_moves": len(hands),
        "alternating_pct": round(100 * alt / max(len(seq) - 1, 1), 1) if len(seq) > 1 else None,
        "name_zh": KB_NAME["alternating"], "book_ref": refs.get(KB_NAME["alternating"]),
        "same_hand_repeats": repeats,   # 连抓：候选跳點/加把手，教练价值待 C 阶段看图定
    }

    out = {"base": base, "generated_by": "climb_match.py (rule, 窄启动 6 动作)",
           "source_file": os.path.basename(A.segments),
           "note": "只识别位置/时序可判的动作；角度/朝向类（掛旗/drop knee/锁膝…）"
                   "留给视觉判定，不上规则（单目角度不可信，见决策文档）",
           "moves": moves_out, "hand_sequence": hand_seq,
           "params": {"MATCH_DIST": MATCH_DIST, "MATCH_WIN_S": MATCH_WIN_S,
                      "CHANGE_WIN_S": CHANGE_WIN_S, "CROSS_MARGIN": CROSS_MARGIN,
                      "HIGH_STEP_GAP": HIGH_STEP_GAP, "HEEL_UP_MIN": HEEL_UP_MIN}}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    from collections import Counter
    c = Counter(m["move_id"] for m in moves_out)
    print(f"✅ {base}: 识别 {len(moves_out)} 个动作  {dict(c)}")
    print(f"   手顺：{len(hands)} 次出手，左右轮流 {hand_seq['alternating_pct']}%，"
          f"连抓 {len(repeats)} 次")
    print(f"   → {out_path}")


if __name__ == "__main__":
    main()
