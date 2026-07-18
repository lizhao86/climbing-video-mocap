#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
climb_journal_card.py —— 旅程账本·展示层（J1，2026-07-18；2026-07-19 加可编辑模式）

只读 素材/journal.json（climb_journal.py 的产出契约）→ 项目根「攀岩账本.html」。
改样式只改这里，改口径去 climb_journal.py（分层硬约定）。

两种渲染（同一套页面，账本总览与填写合一）：
- build_page(j, editable=False)：静态账本（直接双击打开、可分享）
- build_page(j, editable=True) ：每条记录行内带输入框（难度/完攀/岩馆/线路名/备注）
  + 身高框 + 保存条，由 climb_journal_edit.py 的本机服务提供，保存写回 sidecar。
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
    gym = esc(e["gym"]) if e.get("gym") else ""
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
    cells = (_row_head(e) + f'<div class="c-tags">{grade}{sent}</div>'
             + _row_stats(e, height_m))
    if e.get("report_card"):
        link = e["report_card"].replace("\\", "/")
        return (f'<a class="row" href="{esc(link)}">{cells}'
                f'<div class="c-go">看报告卡 →</div></a>')
    return f'<div class="row nolink">{cells}<div class="c-go dim">未生成报告卡</div></div>'


def entry_row_edit(e, height_m):
    sent = e.get("sent")
    sel = {True: "yes", False: "no"}.get(sent, "")
    go = (f'<div class="c-go"><a href="{esc(e["report_card"].replace(chr(92), "/"))}" '
          f'target="_blank">看报告卡 →</a></div>'
          if e.get("report_card") else '<div class="c-go dim">未生成报告卡</div>')
    inputs = f"""
  <div class="editgrid">
    <label>难度<input name="grade" value="{esc(e.get("grade"))}" placeholder="V4 / 5.10b"></label>
    <label>完攀<select name="sent">
      <option value="" {"selected" if sel == "" else ""}>未填</option>
      <option value="yes" {"selected" if sel == "yes" else ""}>完攀 ✓</option>
      <option value="no" {"selected" if sel == "no" else ""}>没完攀</option>
    </select></label>
    <label>岩馆<input name="gym" value="{esc(e.get("gym"))}" placeholder="岩馆名/野外"></label>
    <label>线路名<input name="route_name" value="{esc(e.get("route_name"))}" placeholder="选填"></label>
    <label class="wide">备注<input name="note" value="{esc(e.get("note"))}" placeholder="选填"></label>
  </div>"""
    return (f'<div class="row edit" data-base="{esc(e["base"])}">'
            + _row_head(e) + '<div class="c-tags"></div>'
            + _row_stats(e, height_m) + go + inputs + '</div>')


def build_page(j, editable=False):
    t = j["totals"]
    height_m = j.get("height_m")
    entries = j["entries"]

    gain, gain_unit = fmt_gain(t["total_gain_bl"], height_m)
    kpis = "".join([
        kpi(t["n_routes"], "条", "记录的线路"),
        kpi(gain, gain_unit, "累计爬升"),
        kpi(fmt_time(t["total_climb_time_s"]), "", "在墙时间"),
        kpi(t["total_events"], "次", "累计出手"),
        kpi(t["n_days"], "天", "攀爬日"),
    ])

    badges = [f'最长连续 {t["streak_weeks_best"]} 周']
    if t["streak_weeks_current"]:
        badges.append(f'当前连续 {t["streak_weeks_current"]} 周')
    badges.append(f'本月 {t["n_this_month"]} 条')
    for grd, n in sorted(t.get("sent_by_grade", {}).items()):
        badges.append(f'{grd} 完攀 ×{n}')
    badge_html = "".join(f'<span class="badge">{esc(b)}</span>' for b in badges)

    hint = ""
    if editable:
        hint = ('<p class="hint">直接在下面每条记录里填难度、完攀、岩馆，'
                '身高在页面底部，填完点「保存并更新账本」。不知道的留空没关系。</p>')
    elif not t.get("sent_by_grade"):
        hint = ('<p class="hint">双击项目里的 打开账本填写.bat，'
                '就能在这个页面里直接填每条线的难度和完攀'
                + ("，填了身高爬升会换算成米。" if not height_m else "。") + '</p>')

    mc = t.get("moves_collect", {})
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
    move_html = "".join(cards)

    row_fn = entry_row_edit if editable else entry_row_static
    rows = "".join(row_fn(e, height_m) for e in reversed(entries))
    n_mtime = sum(1 for e in entries if e.get("date_source") == "mtime")
    foot_note = ("日期带 ? 的按文件时间推断，可在该线的 线路.json 里填写核正。"
                 if n_mtime else "日期读自视频拍摄时间。")

    edit_css = """
label{font-size:12px;color:var(--ink2);display:flex;flex-direction:column;gap:3px}
label.wide{grid-column:1/-1}
input,select{background:var(--surface2);border:1px solid var(--line);color:var(--ink);
  padding:7px 10px;font-size:14px;font-family:var(--sans);border-radius:4px;width:100%}
input:focus,select:focus{outline:1px solid var(--accent)}
.row.edit{cursor:default}
.editgrid{grid-column:1/-1;display:grid;grid-template-columns:repeat(4,1fr);gap:10px;
  border-top:1px dashed var(--line);padding-top:12px;margin-top:4px}
.savebar{position:fixed;left:0;right:0;bottom:0;background:rgba(12,14,18,.92);
  border-top:1px solid var(--line);padding:12px 20px;display:flex;gap:16px;
  align-items:center;justify-content:center;backdrop-filter:blur(6px);z-index:9}
.savebar label{flex-direction:row;align-items:center;gap:8px;font-size:13px}
.savebar input{width:90px}
button{background:var(--accent);color:#14161b;border:0;font-weight:700;font-size:15px;
  padding:10px 26px;border-radius:4px;cursor:pointer;font-family:var(--sans)}
button:disabled{opacity:.5;cursor:wait}
#msg{font-size:13px;color:var(--ink2);max-width:340px}
.wrap{padding-bottom:140px}
@media(max-width:720px){.editgrid{grid-template-columns:1fr 1fr}}
""" if editable else ""

    save_bar = f"""
<div class="savebar">
  <label>身高（米）<input id="height" value="{esc(height_m) if height_m else ""}" placeholder="如 1.75"></label>
  <button id="save">保存并更新账本</button><span id="msg"></span>
</div>
<script>
document.getElementById('save').onclick = async () => {{
  const btn = document.getElementById('save'), msg = document.getElementById('msg');
  const entries = Array.from(document.querySelectorAll('.row[data-base]')).map(r => ({{
    base: r.dataset.base,
    grade: r.querySelector('[name=grade]').value.trim(),
    sent: r.querySelector('[name=sent]').value,
    gym: r.querySelector('[name=gym]').value.trim(),
    route_name: r.querySelector('[name=route_name]').value.trim(),
    note: r.querySelector('[name=note]').value.trim(),
  }}));
  btn.disabled = true; msg.textContent = '保存中…';
  try {{
    const r = await fetch('/save', {{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{height_m: document.getElementById('height').value.trim(), entries}})}});
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || '保存失败');
    msg.textContent = '已保存，数字更新中…';
    location.reload();
  }} catch (e) {{
    msg.textContent = e.message.includes('fetch')
      ? '连不上本机服务：这个页面要从「打开账本填写.bat」进来才能保存。'
      : '出错了：' + e.message;
    btn.disabled = false;
  }}
}};
</script>""" if editable else ""

    title = "攀岩账本 · 填写" if editable else "攀岩账本"
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root{{
  --bg:#0b0c0f; --surface:#14161b; --surface2:#1b1e25; --line:#262a33;
  --ink:#e9ecf1; --ink2:#a2a9b8; --ink3:#6b7280;
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
.badges{{margin-top:14px;display:flex;flex-wrap:wrap;gap:8px}}
.badge{{font-family:var(--mono);font-size:12px;color:var(--ink2);
  background:var(--surface2);border:1px solid var(--line);border-radius:99px;
  padding:3px 12px}}
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
{edit_css}
</style></head><body><div class="wrap">
<div class="eyebrow">CLIMBING JOURNAL · {esc(j.get("generated_at", ""))}</div>
<h1>攀岩账本</h1>
<div class="kpis">{kpis}</div>
<div class="badges">{badge_html}</div>
{hint}
<h2>动作收集</h2>
<div class="mcards">{move_html}</div>
<h2>爬升足迹</h2>
{timeline_svg(entries, height_m)}
<h2>线路记录 <span class="mono" style="font-size:11px;color:var(--ink3)">{len(entries)} 条 · 新的在前</span></h2>
<div class="rows">{rows}</div>
<p class="foot">{foot_note} 点一条记录打开它的报告卡。数字口径：爬升与出手来自骨架计量，
每条线各自的说明看报告卡。</p>
</div>{save_bar}</body></html>"""


def main():
    with open(os.path.join(ROOT, JOURNAL_PATH), encoding="utf-8") as f:
        j = json.load(f)
    with open(os.path.join(ROOT, OUT_PATH), "w", encoding="utf-8") as f:
        f.write(build_page(j, editable=False))
    print("攀岩账本.html ← %d 条记录（%s）" % (len(j["entries"]), JOURNAL_PATH))


if __name__ == "__main__":
    main()
