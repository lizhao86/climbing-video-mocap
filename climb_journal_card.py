#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
climb_journal_card.py —— 旅程账本·展示层（J1 2026-07-18；2026-07-20 视觉重做）

只读 素材/journal.json（climb_journal.py 的产出契约）→ 项目根「攀岩账本.html」。
改样式只改这里，改口径去 climb_journal.py（分层硬约定）。

页面是**纯只读**的：荣誉 / 里程 / 足迹 三段总览 + 爬升足迹 + 按月分组的线路目录，
点一条进它的报告卡。元数据（难度/地点/类型）由老板在对话里跟 Claude 说，不在页面填。

视觉：深炭底 + 单一酸绿强调，排印靠字号阶梯做对比（数字是主角）。
页面要能离线双击打开，所以不外链字体，用系统栈。
"""
import html
import json
import os

JOURNAL_PATH = os.path.join("素材", "journal.json")
OUT_PATH = "攀岩账本.html"

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


# ---------------- 总览三段 ----------------

def honor_block(j):
    """荣誉：两套刻度各一个巨型数字 + 完攀分布。抱石 V 级与绳索 YDS 不混榜。"""
    h = j["totals"].get("honors") or {}
    hm = j.get("this_month", {}).get("honors") or {}

    big = []
    for scale, label, sub in (("V", "抱石", "BOULDER"), ("YDS", "绳索", "ROPE")):
        s = h.get(scale)
        val = s["best_sent"] if s and s["best_sent"] else "—"
        if s and s["best_sent"]:
            meta = f'{s["n_sent"]} 条完攀'
            if s["n_attempt"] > s["n_sent"]:
                meta += f' · {s["n_attempt"] - s["n_sent"]} 条在练'
        else:
            meta = "还没有记录"
        big.append(f'<div class="hero-stat">'
                   f'<div class="hero-eyebrow mono">{sub}</div>'
                   f'<div class="hero-num">{esc(val)}</div>'
                   f'<div class="hero-label">{label}最高</div>'
                   f'<div class="hero-meta">{esc(meta)}</div></div>')

    bars = []
    for scale, label in (("V", "抱石"), ("YDS", "绳索")):
        s = h.get(scale)
        if not s or not s["by_grade"]:
            continue
        items = sorted(s["by_grade"].items(), key=lambda kv: kv[0])
        top = max(n for _, n in items)
        segs = "".join(
            f'<div class="gbar" title="{esc(g)} 完攀 {n} 条">'
            f'<div class="gcount mono">{n}</div>'
            f'<div class="gtrack"><div class="gfill" style="height:{max(8, 100 * n // top)}%"></div></div>'
            f'<div class="glbl mono">{esc(g)}</div></div>'
            for g, n in items)
        bars.append(f'<div class="gblock"><div class="gcap">{label}完攀分布</div>'
                    f'<div class="gbars">{segs}</div></div>')

    month_best = [s["best_sent"] for s in hm.values() if s.get("best_sent")]
    month = (f'<div class="sideline"><span class="sl-k mono">本月最难</span>'
             f'<span class="sl-v">{esc(" / ".join(month_best)) if month_best else "本月还没上墙"}</span></div>')

    unknown = j["totals"].get("n_unknown_grade") or 0
    warn = (f'<p class="note-warn">有 {unknown} 条难度认不出格式，没进榜单。'
            f'抱石写成 V4，绳索写成 5.10b。</p>') if unknown else ""

    return (f'<div class="hero-stats">{"".join(big)}</div>'
            f'{month}<div class="gblocks">{"".join(bars)}</div>{warn}')


def mileage_block(j):
    """里程：累计爬升 / 在墙时长 / 出手次数 / 爬岩天数。"""
    t = j["totals"]
    gain, gunit = fmt_gain(t.get("total_gain_bl"), j.get("height_m"))
    secs = t.get("total_climb_time_s") or 0
    if secs >= 3600:
        tval, tunit = f"{secs / 3600:.1f}", "小时"
    else:
        tval, tunit = f"{secs / 60:.0f}", "分钟"
    cells = [(gain, gunit, "累计爬升"),
             (tval, tunit, "在墙时长"),
             (f'{t.get("total_events") or 0}', "次", "累计出手"),
             (f'{t.get("n_days") or 0}', "天", "爬岩天数")]
    inner = "".join(
        f'<div class="stat"><div class="stat-num">{esc(v)}'
        f'<span class="stat-unit">{esc(u)}</span></div>'
        f'<div class="stat-lbl">{esc(l)}</div></div>' for v, u, l in cells)
    hint = ('<p class="note">爬升按身长算。想看米数，把身高告诉 Claude。</p>'
            if not j.get("height_m") else "")
    return f'<div class="stats">{inner}</div>{hint}'


def footprint_block(j):
    """足迹：地点 + 连续周 + 动作收集册（含待解锁）。"""
    t = j["totals"]
    p = t.get("places") or {"n": 0, "list": []}
    cells = [(f'{p["n"]}', "个", "去过的地点"),
             (f'{t.get("streak_weeks_best") or 0}', "周", "最长连续"),
             (f'{t.get("streak_weeks_current") or 0}', "周", "当前连续")]
    inner = "".join(
        f'<div class="stat"><div class="stat-num">{esc(v)}'
        f'<span class="stat-unit">{esc(u)}</span></div>'
        f'<div class="stat-lbl">{esc(l)}</div></div>' for v, u, l in cells)

    places = ("".join(f'<span class="place">{esc(x)}</span>' for x in p["list"])
              if p["list"] else '<span class="place dim">还没记地点</span>')

    mc = t.get("moves_collect") or {}
    cards, seen = [], set()
    for mid, name, ref in COLLECT_SET:
        seen.add(mid)
        got = (mc.get(mid) or {}).get("n", 0)
        cls = "mcard" if got else "mcard locked"
        cnt = f"{got}" if got else "—"
        cards.append(f'<div class="{cls}"><div class="mcnt mono">{cnt}</div>'
                     f'<div class="mname">{esc(name)}</div>'
                     f'<div class="mref mono">{esc(ref)}</div></div>')
    for mid, m in sorted(mc.items(), key=lambda kv: -kv[1]["n"]):
        if mid in seen:
            continue
        cards.append(f'<div class="mcard"><div class="mcnt mono">{m["n"]}</div>'
                     f'<div class="mname">{esc(m["name_zh"])}</div>'
                     f'<div class="mref mono">{esc(m.get("book_ref") or "")}</div></div>')

    return (f'<div class="stats">{inner}</div>'
            f'<div class="places">{places}</div>'
            f'<div class="mcap">动作收集册</div>'
            f'<div class="mcards">{"".join(cards)}</div>')


# ---------------- 爬升足迹 ----------------

def timeline_svg(entries, height_m):
    """一条线一根柱，高=净爬升，柱顶标数值。少量数据下就是成长条。"""
    es = [e for e in entries if e.get("date")]
    es.sort(key=lambda e: e["date"])
    if not es:
        return ""
    W, H, PAD_B, PAD_T = 760, 210, 46, 40
    n = len(es)
    slot = W / n
    bw = min(56, slot * 0.46)
    mx = max(e.get("net_gain_bl") or 0 for e in es) or 1
    parts = [f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet" '
             f'style="width:100%;display:block" role="img">']
    for i, e in enumerate(es):
        g = e.get("net_gain_bl") or 0
        bh = max(3, (H - PAD_B - PAD_T) * g / mx)
        cx = slot * i + slot / 2
        x = cx - bw / 2
        y = H - PAD_B - bh
        name = e.get("route_name") or e["base"]
        val, unit = fmt_gain(g, height_m)
        parts.append(
            f'<g class="tlbar">'
            f'<title>{esc(name)} · {esc(e["date"])} · 爬升 {val} {unit}</title>'
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="2"/>'
            f'<text class="tlval" x="{cx:.1f}" y="{y - 11:.1f}" text-anchor="middle">{val}</text>'
            f'<text class="tlunit" x="{cx:.1f}" y="{y - 25:.1f}" text-anchor="middle">{esc(unit)}</text>'
            f'<text class="tldate" x="{cx:.1f}" y="{H - PAD_B + 19:.1f}" '
            f'text-anchor="middle">{esc(e["date"][5:])}</text>'
            f'<text class="tlname" x="{cx:.1f}" y="{H - PAD_B + 34:.1f}" '
            f'text-anchor="middle">{esc((e.get("grade") or "").strip() or "—")}</text>'
            f'</g>')
    parts.append(f'<line x1="0" y1="{H - PAD_B}" x2="{W}" y2="{H - PAD_B}" '
                 f'stroke="var(--line)" stroke-width="1"/></svg>')
    return "".join(parts)


# ---------------- 线路目录 ----------------

def entry_row(e, height_m):
    name = e.get("route_name") or e["base"]
    date = esc(e.get("date") or "—")
    if e.get("date_source") == "mtime":
        date += '<span class="qmark" title="按文件时间推断，跟 Claude 说一声就能改">?</span>'
    g, gu = fmt_gain(e.get("net_gain_bl"), height_m)

    tags = []
    if e.get("type"):
        tags.append(f'<span class="tag">{esc(e["type"])}</span>')
    if e.get("grade"):
        tags.append(f'<span class="tag grade">{esc(e["grade"])}</span>')
    if e.get("sent") is True:
        tags.append('<span class="tag sent">完攀</span>')
    elif e.get("sent") is False:
        tags.append('<span class="tag unsent">未完攀</span>')

    cells = (
        f'<div class="c-date mono">{date}</div>'
        f'<div class="c-name"><b>{esc(name)}</b>'
        f'<span class="c-place">{esc(e.get("place") or "")}</span></div>'
        f'<div class="c-tags">{"".join(tags)}</div>'
        f'<div class="c-num mono">{g}<span class="cu">{gu}</span></div>'
        f'<div class="c-num mono">{fmt_time(e.get("climb_time_s"))}</div>'
        f'<div class="c-num mono">{e.get("n_crux") if e.get("n_crux") is not None else "—"}'
        f'<span class="cu">卡点</span></div>')

    if e.get("report_card"):
        link = e["report_card"].replace("\\", "/")
        return (f'<a class="row" href="{esc(link)}">{cells}'
                f'<div class="c-go" aria-hidden="true">→</div></a>')
    return (f'<div class="row nolink">{cells}'
            f'<div class="c-go dim" title="这条还没跑报告卡">·</div></div>')


def catalog(entries, height_m):
    """按月分组、日期倒序。月份用超大数字做背景。"""
    by_month = {}
    for e in sorted(entries, key=lambda x: (x.get("date") or ""), reverse=True):
        by_month.setdefault((e.get("date") or "未知日期")[:7], []).append(e)
    out = []
    for month, es in by_month.items():
        rows = "".join(entry_row(e, height_m) for e in es)
        mm = month[5:] if len(month) == 7 else ""
        yy = month[:4] if len(month) == 7 else month
        out.append(f'<section class="month">'
                   f'<div class="mhead"><div class="mbig mono" aria-hidden="true">{esc(mm)}</div>'
                   f'<div class="mtxt"><div class="myear mono">{esc(yy)}</div>'
                   f'<div class="mcount">{len(es)} 条</div></div></div>'
                   f'<div class="rows">{rows}</div></section>')
    return "".join(out)


# ---------------- 页面 ----------------

def build_page(j):
    entries = j.get("entries", [])
    height_m = j.get("height_m")
    t = j["totals"]

    secs = t.get("total_climb_time_s") or 0
    tsum = f"{secs / 3600:.1f} 小时" if secs >= 3600 else f"{secs / 60:.0f} 分钟"
    lede = (f'{t.get("n_routes") or 0} 条线 · '
            f'{(t.get("places") or {}).get("n", 0)} 个地点 · '
            f'在墙 {tsum}')

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>攀岩账本</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
:root{{
  --bg:#0B0C0E; --surface:#131519; --surface2:#191C22; --line:#232733;
  --ink:#F2F4F7; --ink2:#9AA3B2; --ink3:#5D6675;
  --acc:#AFD639; --acc-dim:#7E9B24;
  --sent:#4E9E6A; --warn:#D8A13C;
  /* 与报告卡同一套字：Space Grotesk / Space Mono，断网时退回系统栈 */
  --sans:"Space Grotesk","Segoe UI Variable Display","Segoe UI","Microsoft YaHei",
         "PingFang SC",sans-serif;
  --mono:"Space Mono","Cascadia Mono",Consolas,ui-monospace,monospace;
  --ease:cubic-bezier(.2,.8,.2,1);
}}
*{{box-sizing:border-box}}
em,i,cite{{font-style:normal}}
html{{-webkit-text-size-adjust:100%}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
     font-size:15px;line-height:1.55;text-wrap:pretty;
     background-image:radial-gradient(120% 80% at 82% -8%,rgba(175,214,57,.07),transparent 60%);
     background-attachment:fixed}}
.mono{{font-family:var(--mono);font-variant-numeric:tabular-nums}}
.wrap{{max-width:1120px;margin:0 auto;padding:clamp(28px,5vw,64px) clamp(18px,4vw,40px) 96px}}

/* ---- 页头 ---- */
.eyebrow{{font-family:var(--mono);font-size:11px;letter-spacing:.34em;
         color:var(--ink3);text-transform:uppercase}}
h1{{font-size:clamp(38px,7vw,76px);line-height:.94;letter-spacing:-.035em;
    font-weight:700;margin:14px 0 12px}}
.lede{{color:var(--ink2);font-size:clamp(14px,1.6vw,17px);margin:0 0 clamp(34px,5vw,60px)}}

/* ---- 区块 ---- */
.sec{{margin:0 0 clamp(42px,6vw,72px)}}
.sec-head{{display:flex;align-items:baseline;gap:14px;
          padding-bottom:12px;margin-bottom:clamp(20px,3vw,30px);
          border-bottom:1px solid var(--line)}}
.sec-t{{font-size:13px;letter-spacing:.22em;text-transform:uppercase;
       font-family:var(--mono);color:var(--acc)}}
.sec-sub{{font-size:12px;color:var(--ink3)}}

/* ---- 荣誉巨型数字 ---- */
.hero-stats{{display:grid;grid-template-columns:1fr 1fr;gap:clamp(16px,3vw,34px)}}
.hero-stat{{background:var(--surface);border:1px solid var(--line);border-radius:4px;
           padding:clamp(18px,2.6vw,30px);min-width:0;position:relative;overflow:hidden}}
.hero-stat::after{{content:"";position:absolute;left:0;top:0;width:3px;height:100%;
                  background:var(--acc);opacity:.55}}
.hero-eyebrow{{font-size:10px;letter-spacing:.3em;color:var(--ink3)}}
.hero-num{{font-family:var(--mono);font-variant-numeric:tabular-nums;
          font-size:clamp(52px,9vw,112px);line-height:.92;letter-spacing:-.045em;
          font-weight:700;color:var(--acc);margin:10px 0 6px;word-break:break-all}}
.hero-label{{font-size:15px;font-weight:600}}
.hero-meta{{font-size:12px;color:var(--ink3);margin-top:3px}}

.sideline{{display:flex;align-items:baseline;gap:14px;margin:22px 0 0;
          padding:13px 16px;background:var(--surface2);border-radius:4px}}
.sl-k{{font-size:10px;letter-spacing:.24em;text-transform:uppercase;color:var(--ink3)}}
.sl-v{{font-size:17px;font-weight:600}}

.gblocks{{display:flex;gap:clamp(20px,4vw,48px);flex-wrap:wrap;margin-top:26px}}
.gblock{{min-width:180px}}
.gcap{{font-size:11px;letter-spacing:.16em;text-transform:uppercase;
      color:var(--ink3);margin-bottom:12px}}
.gbars{{display:flex;gap:12px;align-items:flex-end}}
.gbar{{display:flex;flex-direction:column;align-items:center;gap:5px;width:46px}}
.gcount{{font-size:13px;color:var(--ink)}}
.gtrack{{width:100%;height:64px;display:flex;align-items:flex-end;
        background:var(--surface2);border-radius:2px}}
.gfill{{width:100%;background:var(--acc);border-radius:2px}}
.glbl{{font-size:11px;color:var(--ink2)}}

/* ---- 数字条 ---- */
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;
       background:var(--line);border:1px solid var(--line);border-radius:4px;overflow:hidden}}
.stat{{background:var(--surface);padding:clamp(16px,2.4vw,26px)}}
.stat-num{{font-family:var(--mono);font-variant-numeric:tabular-nums;
          font-size:clamp(28px,4.4vw,46px);line-height:1;letter-spacing:-.035em;
          font-weight:700}}
.stat-unit{{font-size:.36em;font-weight:500;color:var(--ink3);margin-left:.32em;
           letter-spacing:0}}
.stat-lbl{{font-size:12px;color:var(--ink3);margin-top:9px}}

.places{{display:flex;flex-wrap:wrap;gap:8px;margin-top:20px}}
.place{{font-size:12px;padding:5px 12px;border:1px solid var(--line);
       border-radius:2px;color:var(--ink2)}}
.place.dim{{color:var(--ink3)}}

.mcap{{font-size:11px;letter-spacing:.16em;text-transform:uppercase;
      color:var(--ink3);margin:28px 0 12px}}
.mcards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(148px,1fr));gap:10px}}
.mcard{{background:var(--surface);border:1px solid var(--line);border-radius:4px;
       padding:15px 16px}}
.mcard.locked{{opacity:.34}}
.mcnt{{font-size:26px;font-weight:700;line-height:1;color:var(--acc)}}
.mcard.locked .mcnt{{color:var(--ink3)}}
.mname{{font-size:13px;margin-top:7px}}
.mref{{font-size:10px;color:var(--ink3);margin-top:2px}}

/* ---- 爬升足迹 ---- */
.tl{{background:var(--surface);border:1px solid var(--line);border-radius:4px;
    padding:clamp(14px,2.4vw,26px)}}
.tlbar rect{{fill:var(--acc);opacity:.78;transition:opacity .15s var(--ease)}}
.tlbar:hover rect{{opacity:1}}
.tlval{{font-family:var(--mono);font-size:15px;font-weight:700;fill:var(--ink)}}
.tlunit{{font-family:var(--mono);font-size:9px;fill:var(--ink3);
        letter-spacing:.1em}}
.tldate{{font-family:var(--mono);font-size:10px;fill:var(--ink3)}}
.tlname{{font-family:var(--mono);font-size:11px;fill:var(--ink2)}}

/* ---- 目录 ---- */
.month{{margin-bottom:clamp(26px,4vw,44px)}}
.mhead{{display:flex;align-items:center;gap:16px;margin-bottom:10px}}
.mbig{{font-size:clamp(40px,7vw,72px);font-weight:700;line-height:.8;
      letter-spacing:-.05em;color:var(--surface2);user-select:none}}
.mtxt{{padding-bottom:4px}}
.myear{{font-size:12px;color:var(--ink3);letter-spacing:.14em}}
.mcount{{font-size:12px;color:var(--ink2)}}

.rows{{border-top:1px solid var(--line)}}
.row{{display:grid;
     grid-template-columns:100px minmax(160px,1.5fr) minmax(150px,1fr) 96px 96px 84px 34px;
     gap:14px;align-items:center;padding:17px 14px 17px 4px;
     border-bottom:1px solid var(--line);text-decoration:none;color:inherit;
     transition:background .15s var(--ease),transform .15s var(--ease),
                padding-left .15s var(--ease)}}
a.row:hover{{background:var(--surface);padding-left:14px}}
a.row:hover .c-go{{color:var(--acc);transform:translateX(3px)}}
a.row:focus-visible{{outline:2px solid var(--acc);outline-offset:-2px}}
.row.nolink{{opacity:.62}}
.c-date{{font-size:12px;color:var(--ink3)}}
.qmark{{color:var(--warn);margin-left:4px;cursor:help}}
.c-name b{{font-size:15px;font-weight:600;display:block}}
.c-place{{font-size:12px;color:var(--ink3);display:block;margin-top:2px}}
.c-tags{{display:flex;gap:6px;flex-wrap:wrap}}
.tag{{font-size:11px;padding:2px 9px;border-radius:2px;
     background:var(--surface2);color:var(--ink2);white-space:nowrap}}
.tag.grade{{background:var(--acc);color:#12160A;font-weight:700;
           font-family:var(--mono)}}
.tag.sent{{background:transparent;border:1px solid var(--sent);color:var(--sent)}}
.tag.unsent{{background:transparent;border:1px solid var(--line);color:var(--ink3)}}
.c-num{{font-size:14px;text-align:right}}
.cu{{font-size:10px;color:var(--ink3);margin-left:4px}}
.c-go{{font-size:17px;color:var(--ink3);text-align:right;
      transition:color .15s var(--ease),transform .15s var(--ease)}}
.c-go.dim{{opacity:.4}}

.note{{font-size:12px;color:var(--ink3);margin:16px 0 0}}
.note-warn{{font-size:12px;color:var(--warn);margin:16px 0 0}}
.foot{{margin-top:clamp(40px,6vw,72px);padding-top:22px;
      border-top:1px solid var(--line);font-size:11px;color:var(--ink3);line-height:1.8}}

@media(max-width:900px){{
  .hero-stats{{grid-template-columns:1fr}}
  .stats{{grid-template-columns:repeat(2,1fr)}}
  .row{{grid-template-columns:88px 1fr 76px;gap:10px;
       grid-template-areas:"date name go" "tags tags tags" "n1 n2 n3";
       padding:16px 10px}}
  .c-date{{grid-area:date}} .c-name{{grid-area:name}} .c-go{{grid-area:go}}
  .c-tags{{grid-area:tags;margin-top:8px}}
  .c-num{{text-align:left}}
  .c-num:nth-of-type(4){{grid-area:n1}}
  .c-num:nth-of-type(5){{grid-area:n2}}
  .c-num:nth-of-type(6){{grid-area:n3}}
  .c-num{{margin-top:8px;font-size:13px}}
}}
@media(prefers-reduced-motion:reduce){{
  *{{transition:none!important;animation:none!important}}
}}
</style></head>
<body><div class="wrap">

<div class="eyebrow">CLIMBING LOG · {esc(j.get("generated_at", ""))}</div>
<h1>攀岩账本</h1>
<p class="lede">{esc(lede)}</p>

<section class="sec">
  <div class="sec-head"><div class="sec-t">荣誉</div>
    <div class="sec-sub">抱石与绳索两套刻度，分开排</div></div>
  {honor_block(j)}
</section>

<section class="sec">
  <div class="sec-head"><div class="sec-t">里程</div>
    <div class="sec-sub">只增不减</div></div>
  {mileage_block(j)}
</section>

<section class="sec">
  <div class="sec-head"><div class="sec-t">足迹</div>
    <div class="sec-sub">去过哪、收集到什么</div></div>
  {footprint_block(j)}
</section>

<section class="sec">
  <div class="sec-head"><div class="sec-t">爬升足迹</div>
    <div class="sec-sub">每条线的净爬升</div></div>
  <div class="tl">{timeline_svg(entries, height_m)}</div>
</section>

<section class="sec">
  <div class="sec-head"><div class="sec-t">线路目录</div>
    <div class="sec-sub">{len(entries)} 条 · 新的在前 · 点开看单条报告</div></div>
  {catalog(entries, height_m)}
</section>

<p class="foot">爬升与出手次数由骨架计量得出，难度与完攀是手记。<br>
数字口径见 PLAN.md；这一页只读，改内容跟 Claude 说。</p>

</div></body></html>"""


def main():
    path = os.path.join(ROOT, JOURNAL_PATH)
    if not os.path.exists(path):
        print("找不到 %s，先跑 python climb_journal.py" % JOURNAL_PATH)
        return
    with open(path, encoding="utf-8") as f:
        j = json.load(f)
    out = os.path.join(ROOT, OUT_PATH)
    with open(out, "w", encoding="utf-8") as f:
        f.write(build_page(j))
    print("%s ← %d 条记录（%s）" % (OUT_PATH, len(j.get("entries", [])), JOURNAL_PATH))


if __name__ == "__main__":
    main()
