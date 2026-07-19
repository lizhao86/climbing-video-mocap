#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
climb_journal_card.py —— 旅程账本·展示层（J1，2026-07-18；2026-07-19 首页重做）

只读 素材/journal.json（climb_journal.py 的产出契约）→ 项目根「攀岩账本.html」。
改样式只改这里，改口径去 climb_journal.py（分层硬约定）。

页面是**纯只读**的：上面三行并列（荣誉 / 里程 / 足迹），下面按月分组的线路目录，
点一条进它的报告卡。元数据（难度/地点/类型）由老板在对话里跟 Claude 说，不在页面填。
"""
import html
import json
import os

JOURNAL_PATH = os.path.join("素材", "journal.json")
OUT_PATH = "攀岩账本.html"

# 与 climb_report_card.py 同一套色
C_MOVE = "#e08a42"
C_REST = "#5fa07a"
C_STUCK = "#45a8c4"

# 收集册全集 = 规则识别里 conf 能达 medium 的动作（与报告卡「动作记录」同口径）
COLLECT_SET = [
    ("high_step", "高跨步", "3-4-1 p.93-95"),
    ("match", "同點（Match）", "3-7-3 p.130"),
    ("hand_change", "換手（Change）", "3-7-3 p.130-131"),
]

ROOT = os.path.dirname(os.path.abspath(__file__))


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def fmt_time(sec):
    if sec is None:
        return "—"
    sec = int(round(sec))
    if sec < 60:
        return f"{sec} 秒"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{m} 分 {s:02d} 秒" if s else f"{m} 分钟"
    h, m = divmod(m, 60)
    return f"{h} 小时 {m:02d} 分"


def fmt_gain(bl, height_m):
    if bl is None:
        return "—", ""
    if height_m:
        return f"{bl * height_m:.1f}", "米"
    return f"{bl:.1f}", "身长"


def kpi(num, unit, label):
    u = f'<span class="unit">{esc(unit)}</span>' if unit else ""
    return (f'<div class="kpi"><div class="num">{esc(num)}{u}</div>'
            f'<div class="lbl">{esc(label)}</div></div>')


def timeline_svg(entries, height_m):
    """按日期一根柱，高=净爬升。少量数据下就是简单的成长条。"""
    es = [e for e in entries if e.get("date")]
    if not es:
        return ""
    W, H, PAD_B, PAD_T = 720, 150, 34, 14
    n = len(es)
    slot = W / n
    bw = min(44, slot * 0.5)
    mx = max(e.get("net_gain_bl") or 0 for e in es) or 1
    parts = [f'<svg viewBox="0 0 {W} {H}" style="width:100%;max-width:{W}px;display:block">']
    for i, e in enumerate(es):
        g = e.get("net_gain_bl") or 0
        bh = (H - PAD_B - PAD_T) * g / mx
        x = slot * i + (slot - bw) / 2
        y = H - PAD_B - bh
        name = e.get("route_name") or e["base"]
        val = fmt_gain(g, height_m)
        parts.append(
            f'<g><title>{esc(name)} · {esc(e["date"])} · 爬升 {val[0]} {val[1]}</title>'
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}"'
            f' rx="3" fill="{C_MOVE}" opacity="0.85"/>'
            f'<text x="{slot * i + slot / 2:.1f}" y="{H - PAD_B + 16}" font-size="10"'
            f' text-anchor="middle" fill="#6b7280" font-family="Space Mono,monospace">'
            f'{esc(e["date"][5:])}</text></g>')
    parts.append(f'<line x1="0" y1="{H - PAD_B}" x2="{W}" y2="{H - PAD_B}" '
                 f'stroke="#262a33" stroke-width="1"/></svg>')
    return "".join(parts)


def _row_stats(e, height_m):
    g, gu = fmt_gain(e.get("net_gain_bl"), height_m)
    return (
        f'<div class="c-num mono">{g}<span class="cu">{gu}</span></div>'
        f'<div class="c-num mono">{fmt_time(e.get("climb_time_s"))}</div>'
        f'<div class="c-num mono">{e.get("n_crux") if e.get("n_crux") is not None else "—"}'
        f'<span class="cu">卡点</span></div>')


def _row_head(e):
    name = e.get("route_name") or e["base"]
    date = e.get("date") or "—"
    if e.get("date_source") == "mtime":
        date += '<span class="warn" title="按文件时间推断，可在 线路.json 填写核正">?</span>'
    gym = esc(e.get("place") or "")
    return (f'<div class="c-date mono">{date}</div>'
            f'<div class="c-name"><b>{esc(name)}</b>'
            f'<span class="sub">{gym}</span></div>')


def entry_row_static(e, height_m):
    grade = f'<span class="grade">{esc(e["grade"])}</span>' if e.get("grade") else ""
    sent = ""
    if e.get("sent") is True:
        sent = '<span class="sent">完攀 ✓</span>'
    elif e.get("sent") is False:
        sent = '<span class="unsent">未完攀</span>'
    typ = f'<span class="type">{esc(e["type"])}</span>' if e.get("type") else ""
    cells = (_row_head(e) + f'<div class="c-tags">{typ}{grade}{sent}</div>'
             + _row_stats(e, height_m))
    if e.get("report_card"):
        link = e["report_card"].replace("\\", "/")
        return (f'<a class="row" href="{esc(link)}">{cells}'
                f'<div class="c-go">看报告卡 →</div></a>')
    return f'<div class="row nolink">{cells}<div class="c-go dim">未生成报告卡</div></div>'


def catalog(entries, height_m):
    """按月分组、日期倒序的记录目录。"""
    by_month = {}
    for e in sorted(entries, key=lambda x: (x.get("date") or ""), reverse=True):
        by_month.setdefault((e.get("date") or "未知日期")[:7], []).append(e)
    out = []
    for month, es in by_month.items():
        rows = "".join(entry_row_static(e, height_m) for e in es)
        out.append(f'<div class="month"><div class="mhead mono">{esc(month)}'
                   f'<span class="mcount">{len(es)} 条</span></div>'
                   f'<div class="rows">{rows}</div></div>')
    return "".join(out)


def honor_row(j):
    """荣誉行：双刻度最高难度 + 各难度完攀数分布 + 本月最难。"""
    h = j["totals"].get("honors") or {}
    hm = j.get("this_month", {}).get("honors") or {}
    cells = []
    for scale, label in (("V", "抱石最高"), ("YDS", "绳索最高")):
        s = h.get(scale)
        cells.append(kpi(s["best_sent"] if s and s["best_sent"] else "—", "", label))
    month_best = [s["best_sent"] for s in hm.values() if s.get("best_sent")]
    cells.append(kpi(" / ".join(month_best) if month_best else "—", "", "本月最难"))

    bars = []
    for scale, label in (("V", "抱石"), ("YDS", "绳索")):
        s = h.get(scale)
        if not s or not s["by_grade"]:
            continue
        items = sorted(s["by_grade"].items(), key=lambda kv: kv[0])
        top = max(n for _, n in items)
        segs = "".join(
            f'<div class="gbar"><div class="gfill" style="height:{100*n//top}%"></div>'
            f'<div class="gnum mono">{n}</div><div class="glbl mono">{esc(g)}</div></div>'
            for g, n in items)
        bars.append(f'<div class="gblock"><div class="glabel">{label}完攀分布</div>'
                    f'<div class="gbars">{segs}</div></div>')

    unknown = j["totals"].get("n_unknown_grade") or 0
    warn = (f'<p class="gwarn">有 {unknown} 条填了难度但认不出格式，未计入榜单。'
            f'抱石写成 V4，绳索写成 5.10b。</p>') if unknown else ""
    return (f'<div class="kpis">{"".join(cells)}</div>'
            f'<div class="gblocks">{"".join(bars)}</div>{warn}')


def mileage_row(j):
    """里程行：累计爬升 / 在墙时长 / 出手次数 / 爬岩天数。"""
    t = j["totals"]
    gain, gunit = fmt_gain(t.get("total_gain_bl"), j.get("height_m"))
    hours = round((t.get("total_climb_time_s") or 0) / 3600, 1)
    return ('<div class="kpis">'
            + kpi(gain, gunit, "累计爬升")
            + kpi(f"{hours}", "小时", "在墙时长")
            + kpi(f'{t.get("total_events") or 0}', "次", "累计出手")
            + kpi(f'{t.get("n_days") or 0}', "天", "爬岩天数")
            + '</div>')


def footprint_row(j):
    """足迹行：去过几个地点 + 连续周 + 动作收集。"""
    t = j["totals"]
    p = t.get("places") or {"n": 0, "list": []}
    cells = (kpi(f'{p["n"]}', "个", "去过的地点")
             + kpi(f'{t.get("streak_weeks_best") or 0}', "周", "最长连续")
             + kpi(f'{t.get("streak_weeks_current") or 0}', "周", "当前连续"))
    mc = t.get("moves_collect") or {}
    cards = []
    for mid, name, ref in COLLECT_SET:
        got = mc.get(mid, {}).get("n", 0)
        cls = "mcard" if got else "mcard locked"
        cnt = f'×{got}' if got else "待解锁"
        cards.append(f'<div class="{cls}"><div class="mname">{esc(name)}</div>'
                     f'<div class="mcnt mono">{cnt}</div>'
                     f'<div class="mref mono">{esc(ref)}</div></div>')
    for mid in sorted(set(mc) - {m[0] for m in COLLECT_SET}):
        m = mc[mid]
        cards.append(f'<div class="mcard"><div class="mname">{esc(m["name_zh"])}</div>'
                     f'<div class="mcnt mono">×{m["n"]}</div>'
                     f'<div class="mref mono">{esc(m.get("book_ref") or "")}</div></div>')
    mcards = "".join(cards)
    place_list = ('<p class="plist">' + esc(" · ".join(p["list"])) + '</p>') if p["list"] else ""
    return f'<div class="kpis">{cells}</div>{place_list}<div class="mcards">{mcards}</div>'


def build_page(j):
    height_m = j.get("height_m")
    entries = j["entries"]

    hint = ('<p class="hint">难度、地点这些信息在对话里跟 Claude 说一句就记上了，'
            '不用在这个页面填。</p>')

    honor_html = honor_row(j)
    mileage_html = mileage_row(j)
    footprint_html = footprint_row(j)
    timeline_html = timeline_svg(entries, height_m)
    catalog_html = catalog(entries, height_m)

    n_mtime = sum(1 for e in entries if e.get("date_source") == "mtime")
    foot_note = ("日期带 ? 的按文件时间推断，可在该线的 线路.json 里填写核正。"
                 if n_mtime else "日期读自视频拍摄时间。")

    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>攀岩账本</title>
<style>
:root{{
  --bg:#0b0c0f; --surface:#14161b; --surface2:#1b1e25; --line:#262a33;
  --ink:#e9ecf1; --ink2:#a2a9b8; --ink3:#6b7280;
  --warn:#d9a441;
  --accent:{C_MOVE}; --rest:{C_REST}; --stuck:{C_STUCK};
  --sans:"Space Grotesk","Microsoft YaHei","PingFang SC",sans-serif;
  --mono:"Space Mono",ui-monospace,monospace;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  line-height:1.6;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:860px;margin:0 auto;padding:48px 20px 80px}}
.mono{{font-family:var(--mono)}}
.eyebrow{{font-family:var(--mono);font-size:11px;color:var(--ink3);letter-spacing:.14em}}
h1{{font-size:34px;margin:6px 0 0;letter-spacing:-.01em}}
h2{{font-size:14px;font-weight:700;color:var(--ink2);margin:56px 0 16px;
  padding-bottom:10px;border-bottom:1px solid var(--line)}}
.kpis{{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--line);
  border:1px solid var(--line);margin-top:34px}}
.kpi{{background:var(--surface);padding:16px 14px}}
.kpi .num{{font-family:var(--mono);font-size:24px;font-weight:700}}
.kpi .unit{{font-size:12px;color:var(--ink3);margin-left:3px;font-weight:400}}
.kpi .lbl{{font-size:12px;color:var(--ink3);margin-top:2px}}
.hint{{font-size:13px;color:var(--ink3);background:var(--surface);
  border:1px dashed var(--line);padding:10px 14px;margin-top:16px}}
.mcards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}}
.mcard{{background:var(--surface);border:1px solid var(--line);padding:14px}}
.mcard .mname{{font-size:14px;font-weight:700}}
.mcard .mcnt{{font-size:20px;color:var(--accent);margin-top:4px}}
.mcard .mref{{font-size:10px;color:var(--ink3);margin-top:6px}}
.mcard.locked{{opacity:.45}}
.mcard.locked .mcnt{{color:var(--ink3);font-size:13px}}
.rows{{display:flex;flex-direction:column;gap:8px}}
.row{{display:grid;grid-template-columns:96px 1fr auto 90px 110px 74px 110px;
  gap:10px;align-items:center;background:var(--surface);border:1px solid var(--line);
  padding:13px 16px;text-decoration:none;color:var(--ink)}}
a.row:hover{{background:var(--surface2);border-color:var(--ink3)}}
.row .c-date{{font-size:12px;color:var(--ink2)}}
.row .c-name b{{font-size:15px}}
.row .c-name .sub{{display:block;font-size:12px;color:var(--ink3)}}
.row .c-tags{{display:flex;gap:6px}}
.grade{{font-family:var(--mono);font-size:12px;color:var(--ink);
  background:var(--surface2);border:1px solid var(--line);padding:1px 8px}}
.sent{{font-size:12px;color:var(--rest)}}
.unsent{{font-size:12px;color:var(--ink3)}}
.row .c-num{{font-size:13px;text-align:right}}
.row .cu{{font-size:10px;color:var(--ink3);margin-left:3px}}
.row .c-go{{font-size:12px;text-align:right;white-space:nowrap}}
.row .c-go,.row .c-go a{{color:var(--accent);text-decoration:none}}
.row .c-go.dim{{color:var(--ink3)}}
.warn{{color:var(--stuck);margin-left:2px;cursor:help}}
.foot{{margin-top:40px;font-size:12px;color:var(--ink3)}}
@media(max-width:720px){{
  .kpis{{grid-template-columns:repeat(2,1fr)}}
  .row{{grid-template-columns:80px 1fr auto;grid-auto-rows:auto}}
  .row .c-num,.row .c-go{{text-align:left}}
}}
.secrow{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin:18px 0 28px}}
.sec{{background:var(--surface);border-radius:12px;padding:16px 18px;min-width:0}}
.sec h2{{margin:0 0 12px;font-size:12px;letter-spacing:.14em;color:var(--ink3)}}
.sec .kpis{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;
  background:none;border:0;margin-top:0}}
.sec .kpi{{background:none;padding:0}}
.gblocks{{margin-top:14px}}
.gblock{{margin-top:10px}}
.glabel{{font-size:11px;color:var(--ink3);margin-bottom:6px}}
.gbars{{display:flex;gap:6px;align-items:flex-end;height:56px}}
.gbar{{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%}}
.gfill{{width:100%;background:var(--accent);border-radius:3px 3px 0 0;min-height:3px}}
.gnum{{font-size:11px;margin-top:2px}}
.glbl{{font-size:10px;color:var(--ink3)}}
.gwarn{{font-size:11px;color:var(--warn);margin:10px 0 0}}
.plist{{font-size:11px;color:var(--ink3);margin:10px 0 0}}
.month{{margin-bottom:22px}}
.mhead{{font-size:12px;color:var(--ink3);padding:0 0 8px;border-bottom:1px solid var(--line)}}
.mcount{{float:right}}
.type{{display:inline-block;padding:1px 7px;border-radius:9px;font-size:11px;
      background:var(--surface2);color:var(--ink2);margin-right:5px}}
@media(max-width:900px){{.secrow{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">
<div class="eyebrow">CLIMBING JOURNAL · {esc(j.get("generated_at", ""))}</div>
<h1>攀岩账本</h1>
<div class="secrow">
  <section class="sec"><h2>荣誉</h2>{honor_html}</section>
  <section class="sec"><h2>里程</h2>{mileage_html}</section>
  <section class="sec"><h2>足迹</h2>{footprint_html}</section>
</div>
<h2>爬升足迹</h2>
{timeline_html}
{hint}
<h2>线路目录 <span class="mono" style="font-size:11px;color:var(--ink3)">{len(entries)} 条 · 新的在前</span></h2>
{catalog_html}
<p class="foot">{foot_note} 点一条记录打开它的报告卡。数字口径：爬升与出手来自骨架计量，
每条线各自的说明看报告卡。</p>
</div></body></html>"""


def main():
    with open(os.path.join(ROOT, JOURNAL_PATH), encoding="utf-8") as f:
        j = json.load(f)
    with open(os.path.join(ROOT, OUT_PATH), "w", encoding="utf-8") as f:
        f.write(build_page(j))
    print("攀岩账本.html ← %d 条记录（%s）" % (len(j["entries"]), JOURNAL_PATH))


if __name__ == "__main__":
    main()
