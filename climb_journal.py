#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
climb_journal.py —— 旅程账本·聚合层（J1，2026-07-18）

扫 素材/*/数据/*_metrics_v2.json + 手填 sidecar 线路.json → 素材/journal.json。
展示层 climb_journal_card.py 只读 journal.json（分层硬约定：改样式不碰指标）。

用法:
    python climb_journal.py            # 聚合，写 素材/journal.json
    python climb_journal.py --init     # 为缺 sidecar 的素材文件夹生成 线路.json 模板
                                       # 并生成根目录 账本配置.json 模板，然后退出

设计定案见 docs/superpowers/plans/2026-07-18-journey-ledger.md 与 PLAN.md §10。
日期优先级: 线路.json 手填 > quicktime.creationdate > creation_time(UTC+8) > 文件 mtime。
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

# ---------------- 旋钮 ----------------
MATERIAL_DIR = "素材"
CONFIG_PATH = "账本配置.json"
SIDECAR_NAME = "线路.json"
OUT_PATH = os.path.join(MATERIAL_DIR, "journal.json")
CONF_OK = {"high", "medium"}      # 动作收集口径 = 报告卡「动作记录」同口径
REPORT_CARD_NAME = "攀岩报告卡.html"
VIDEO_EXTS = (".mov", ".mp4", ".MOV", ".MP4")

SIDECAR_TEMPLATE = {
    "类型": "",          # 抱石 / 顶绳 / 先锋
    "难度": "",          # 抱石填 V4，绳索填 5.10b
    "完攀": None,
    "地点": "",          # 岩馆名或野外岩场名
    "线路名": "",        # 野外才有；室内线路通常没名字
    "日期": "",
    "备注": "",
    "视频指纹": "",      # climb_intake.py 自动填，判重用
    "登记时间": "",
}
CONFIG_TEMPLATE = {"身高_m": None, "体重_kg": None, "躯干长_m": None}

# ⚠️ 爬升的归一化单位是 body_scale = ||肩中点 − 髋中点||，也就是**躯干长**，
# 不是身高。J1 到 2026-07-20 一直误乘身高，把爬升放大了约 3.5 倍
# （IMG_6152 报成 7.1 米，实际约 2 米）。躯干长按人体测量学 ≈ 0.29×身高，
# 想更准就在 账本配置.json 填「躯干长_m」实测值。
TORSO_RATIO = 0.29


def torso_len_m(cfg):
    """→ 躯干长（米），没身高也没实测值就返回 None（那就只能报躯干数）。"""
    t = cfg.get("躯干长_m")
    if t:
        return float(t)
    h = cfg.get("身高_m")
    return float(h) * TORSO_RATIO if h else None

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_video(folder):
    for f in sorted(os.listdir(folder)):
        if f.endswith(VIDEO_EXTS):
            return os.path.join(folder, f)
    return None


def probe_date(video_path):
    """ffprobe 读拍摄日期。返回 (YYYY-MM-DD, source) 或 (None, None)。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries",
             "format_tags=creation_time,com.apple.quicktime.creationdate",
             "-of", "json", video_path],
            capture_output=True, text=True, timeout=30, encoding="utf-8")
        tags = json.loads(out.stdout).get("format", {}).get("tags", {})
    except Exception:
        return None, None
    qt = tags.get("com.apple.quicktime.creationdate", "")
    m = re.match(r"(\d{4}-\d{2}-\d{2})T", qt)
    if m:  # 带本地时区，日期部分直接可用
        return m.group(1), "metadata"
    ct = tags.get("creation_time", "")
    m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})", ct)
    if m:  # UTC → +8h 转本地日
        try:
            dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
            local = dt.astimezone(timezone(timedelta(hours=8)))
            return local.strftime("%Y-%m-%d"), "metadata"
        except ValueError:
            pass
    return None, None


def resolve_date(sidecar, video_path):
    d = (sidecar.get("日期") or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        return d, "manual"
    if video_path:
        d, src = probe_date(video_path)
        if d:
            return d, src
        d = datetime.fromtimestamp(os.path.getmtime(video_path)).strftime("%Y-%m-%d")
        return d, "mtime"
    return None, None


# ---------------- 难度双刻度 ----------------
# 抱石 V 级与绳索 YDS(5.x) 是两套刻度，不能混一个榜。
# rank 只用于同刻度内排序，跨刻度比较无意义。
GRADE_V = re.compile(r"^[Vv](\d+)$")
GRADE_YDS = re.compile(r"^5\.(\d+)([a-dA-D])?$")


def parse_grade(grade):
    """难度字符串 → (scale, rank)。无法识别返回 (None, None)。

    scale ∈ {"V", "YDS"}。rank 是同刻度内的序号，越大越难。
    YDS 用 数字*4+字母 编码，保证 5.9(36) < 5.10a(40) < 5.10b(41)——
    字符串排序会把 5.9 排到 5.10a 之后，必须走这里。
    """
    g = (grade or "").strip()
    m = GRADE_V.match(g)
    if m:
        return "V", int(m.group(1))
    m = GRADE_YDS.match(g)
    if m:
        letter = (m.group(2) or "a").lower()
        return "YDS", int(m.group(1)) * 4 + (ord(letter) - ord("a"))
    return None, None


def count_moves(rec):
    """recognition.json → {move_id: {n, name_zh, book_ref}}，只计 conf∈CONF_OK。"""
    out = {}
    for mv in rec.get("moves", []):
        if mv.get("confidence") not in CONF_OK:
            continue
        mid = mv.get("move_id", "unknown")
        slot = out.setdefault(mid, {"n": 0,
                                    "name_zh": mv.get("name_zh", mid),
                                    "book_ref": mv.get("book_ref", "")})
        slot["n"] += 1
    return out


def streak_weeks(dates):
    """返回 (最长连续周数, 当前连续周数)。周 = ISO 周（按该周周一归一）。
    当前连续以今天所在周为锚：本周没记录就是 0（Strava 口径，不粉饰）。"""
    if not dates:
        return 0, 0
    mondays = set()
    for d in dates:
        dt = datetime.strptime(d, "%Y-%m-%d")
        mondays.add((dt - timedelta(days=dt.weekday())).date())

    def run_len(anchor):
        n = 0
        while anchor in mondays:
            n += 1
            anchor -= timedelta(days=7)
        return n

    best = max(run_len(m) for m in mondays)
    today = datetime.now()
    this_monday = (today - timedelta(days=today.weekday())).date()
    current = run_len(this_monday)
    return best, current


def collect_entry(folder):
    """一个素材文件夹 → 一条账本记录，缺 metrics_v2 返回 None。"""
    base = os.path.basename(folder)
    data_dir = os.path.join(folder, "数据")
    mv2_path = os.path.join(data_dir, f"{base}_metrics_v2.json")
    if not os.path.exists(mv2_path):
        return None
    mv2 = load_json(mv2_path)

    seg_path = os.path.join(data_dir, f"{base}_segments.json")
    seg = load_json(seg_path) if os.path.exists(seg_path) else {}
    rec_path = os.path.join(data_dir, f"{base}_recognition.json")
    rec = load_json(rec_path) if os.path.exists(rec_path) else {}

    sidecar_path = os.path.join(folder, SIDECAR_NAME)
    sidecar = load_json(sidecar_path) if os.path.exists(sidecar_path) else {}

    video = find_video(folder)
    date, date_source = resolve_date(sidecar, video)

    grade = (sidecar.get("难度") or "").strip()
    grade_scale, grade_rank = parse_grade(grade)

    comp = mv2.get("completion", {})
    card = os.path.join(folder, REPORT_CARD_NAME)
    card_rel = os.path.relpath(card, ROOT).replace("\\", "/") if os.path.exists(card) else None

    return {
        "base": base,
        "dir": os.path.relpath(folder, ROOT).replace("\\", "/"),
        "date": date,
        "date_source": date_source,
        "route_name": (sidecar.get("线路名") or "").strip(),
        "place": (sidecar.get("地点") or "").strip(),
        "type": (sidecar.get("类型") or "").strip(),
        "grade": grade,
        "grade_scale": grade_scale,
        "grade_rank": grade_rank,
        "fingerprint": (sidecar.get("视频指纹") or "").strip(),
        "sent": sidecar.get("完攀"),
        "note": (sidecar.get("备注") or "").strip(),
        "video_duration_s": mv2.get("video_duration_s"),
        "climb_time_s": comp.get("climb_time_s"),
        "net_gain_bl": comp.get("net_gain_bl"),
        "n_events": seg.get("n_events"),
        "n_crux": mv2.get("crux", {}).get("n"),
        "moves": count_moves(rec),
        "report_card": card_rel,
    }


def honors(entries):
    """→ {scale: {best_sent, best_sent_rank, by_grade, n_sent, n_attempt}}。

    完攀的才进 best_sent 和 by_grade；没送顶的只算 n_attempt。
    难度识别不出来的条目整条跳过（它仍进里程/足迹统计）。
    """
    out = {}
    for e in entries:
        scale, rank = e.get("grade_scale"), e.get("grade_rank")
        if not scale:
            continue
        h = out.setdefault(scale, {"best_sent": None, "best_sent_rank": -1,
                                   "by_grade": {}, "n_sent": 0, "n_attempt": 0})
        h["n_attempt"] += 1
        if e.get("sent") is True:
            h["n_sent"] += 1
            g = e["grade"]
            h["by_grade"][g] = h["by_grade"].get(g, 0) + 1
            if rank > h["best_sent_rank"]:
                h["best_sent_rank"] = rank
                h["best_sent"] = g
    return out


def places(entries):
    """→ {n, list}。去重、去空、按名排序。"""
    ps = sorted({(e.get("place") or "").strip()
                 for e in entries if (e.get("place") or "").strip()})
    return {"n": len(ps), "list": ps}


def n_unknown_grade(entries):
    """填了难度但识别不出来的条数——账本页要如实标出来，不能装作没有。"""
    return sum(1 for e in entries
               if (e.get("grade") or "").strip() and not e.get("grade_scale"))


def aggregate(entries, torso_m):
    dates = [e["date"] for e in entries if e["date"]]
    this_month = datetime.now().strftime("%Y-%m")
    month_entries = [e for e in entries if (e["date"] or "").startswith(this_month)]

    def sums(es):
        return {
            "n_routes": len(es),
            "total_climb_time_s": round(sum(e["climb_time_s"] or 0 for e in es), 1),
            "total_gain_bl": round(sum(e["net_gain_bl"] or 0 for e in es), 2),
            "total_events": sum(e["n_events"] or 0 for e in es),
        }

    moves_collect = {}
    for e in entries:
        for mid, m in e["moves"].items():
            slot = moves_collect.setdefault(mid, {"n": 0, "name_zh": m["name_zh"],
                                                  "book_ref": m["book_ref"]})
            slot["n"] += m["n"]

    best_streak, cur_streak = streak_weeks(dates)
    totals = sums(entries)
    totals.update({
        "n_days": len(set(dates)),
        "n_this_month": len(month_entries),
        "streak_weeks_best": best_streak,
        "streak_weeks_current": cur_streak,
        "moves_collect": moves_collect,
        "honors": honors(entries),
        "places": places(entries),
        "n_unknown_grade": n_unknown_grade(entries),
    })
    # 米数：乘**躯干长**，不是身高（曾误乘身高放大 3.5 倍）。
    # ⚠️ 这个数已知偏保守——相机仰拍会压缩高处，IMG_6321 实测墙高 10m 只推出 4.7m。
    # 老板 2026-07-20 决定先留着，等 high wall 素材再评估算法，见 PLAN.md 待办。
    if torso_m:
        totals["total_gain_m"] = round(totals["total_gain_bl"] * torso_m, 1)

    tm = sums(month_entries)
    tm["honors"] = honors(month_entries)
    if torso_m:
        tm["total_gain_m"] = round(tm["total_gain_bl"] * torso_m, 1)

    return totals, tm


def cmd_init():
    made = []
    cfg = os.path.join(ROOT, CONFIG_PATH)
    if not os.path.exists(cfg):
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump(CONFIG_TEMPLATE, f, ensure_ascii=False, indent=2)
        made.append(CONFIG_PATH)
    mdir = os.path.join(ROOT, MATERIAL_DIR)
    for name in sorted(os.listdir(mdir)):
        folder = os.path.join(mdir, name)
        if not os.path.isdir(folder):
            continue
        if not os.path.exists(os.path.join(folder, "数据")):
            continue
        sc = os.path.join(folder, SIDECAR_NAME)
        if not os.path.exists(sc):
            with open(sc, "w", encoding="utf-8") as f:
                json.dump(SIDECAR_TEMPLATE, f, ensure_ascii=False, indent=2)
            made.append(os.path.relpath(sc, ROOT))
    print("生成模板 %d 份:" % len(made))
    for p in made:
        print("  " + p)
    if not made:
        print("  （都已存在，未覆盖）")


def main():
    if "--init" in sys.argv:
        cmd_init()
        return

    cfg_path = os.path.join(ROOT, CONFIG_PATH)
    if not os.path.exists(cfg_path):
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(CONFIG_TEMPLATE, f, ensure_ascii=False, indent=2)
        print("已生成 %s 模板（身高_m 填了才有米数）" % CONFIG_PATH)
    cfg = load_json(cfg_path)
    height_m = cfg.get("身高_m")
    torso_m = torso_len_m(cfg)

    mdir = os.path.join(ROOT, MATERIAL_DIR)
    entries = []
    skipped = []
    for name in sorted(os.listdir(mdir)):
        folder = os.path.join(mdir, name)
        if not os.path.isdir(folder):
            continue
        e = collect_entry(folder)
        if e:
            entries.append(e)
        else:
            skipped.append(name)
    entries.sort(key=lambda e: (e["date"] or "", e["base"]))

    totals, this_month = aggregate(entries, torso_m)
    journal = {
        "generated_by": "climb_journal.py",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "height_m": height_m,
        "torso_m": torso_m,
        "totals": totals,
        "this_month": this_month,
        "entries": entries,
    }
    with open(os.path.join(ROOT, OUT_PATH), "w", encoding="utf-8") as f:
        json.dump(journal, f, ensure_ascii=False, indent=2)

    print("journal.json: %d 条记录 → %s" % (len(entries), OUT_PATH))
    if skipped:
        print("跳过（无 metrics_v2）: %s" % ", ".join(skipped))
    print("累计: 爬升 %.2fbl | 在墙 %.1fs | 出手 %d 次 | 天数 %d | 最长连续 %d 周(当前 %d)"
          % (totals["total_gain_bl"], totals["total_climb_time_s"],
             totals["total_events"], totals["n_days"],
             totals["streak_weeks_best"], totals["streak_weeks_current"]))
    for e in entries:
        print("  %s  %-10s %s gain=%.2fbl climb=%.1fs events=%s card=%s"
              % (e["date"], e["base"], e["date_source"],
                 e["net_gain_bl"] or 0, e["climb_time_s"] or 0,
                 e["n_events"], "有" if e["report_card"] else "无"))


if __name__ == "__main__":
    main()
