#!/usr/bin/env python3
"""把 knowledge_base/moves.json 渲染成可浏览的单文件 HTML（moves_viewer.html）。
用法：python3 knowledge_base/kb_render.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
MOVES_JSON = HERE / "moves.json"
OUT_HTML = HERE / "moves_viewer.html"

DETECT_LABEL = {
    "rule": "规则可判",
    "rule_weak": "规则弱（需视觉确认）",
    "vision": "视觉判定",
    "manual": "人工标注",
}
KIND_LABEL = {"posture": "静态姿势", "action": "动态动作"}

TEMPLATE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>攀岩动作知识库 · moves.json 浏览器</title>
<style>
  :root {{
    --bg: #f7f7f5; --panel: #ffffff; --text: #1f2328; --muted: #6b7280;
    --border: #e5e7eb; --accent: #2563eb;
    --rule: #16a34a; --rule-bg: #dcfce7;
    --rule_weak: #d97706; --rule_weak-bg: #fef3c7;
    --vision: #2563eb; --vision-bg: #dbeafe;
    --manual: #6b7280; --manual-bg: #e5e7eb;
    --posture-bg: #f3e8ff; --posture: #7e22ce;
    --action-bg: #ffe4e6; --action: #be123c;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #16181d; --panel: #1e2128; --text: #e6e8eb; --muted: #9aa2ad;
      --border: #2c3038; --accent: #60a5fa;
      --rule-bg: #14351f; --rule_weak-bg: #3a2a0c; --vision-bg: #10243f; --manual-bg: #2c3038;
      --posture-bg: #2c1f3a; --action-bg: #3a1420;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #16181d; --panel: #1e2128; --text: #e6e8eb; --muted: #9aa2ad;
    --border: #2c3038; --accent: #60a5fa;
    --rule-bg: #14351f; --rule_weak-bg: #3a2a0c; --vision-bg: #10243f; --manual-bg: #2c3038;
    --posture-bg: #2c1f3a; --action-bg: #3a1420;
  }}
  :root[data-theme="light"] {{
    --bg: #f7f7f5; --panel: #ffffff; --text: #1f2328; --muted: #6b7280;
    --border: #e5e7eb; --accent: #2563eb;
    --rule-bg: #dcfce7; --rule_weak-bg: #fef3c7; --vision-bg: #dbeafe; --manual-bg: #e5e7eb;
    --posture-bg: #f3e8ff; --action-bg: #ffe4e6;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    line-height: 1.55;
  }}
  header {{
    position: sticky; top: 0; z-index: 10;
    background: var(--panel); border-bottom: 1px solid var(--border);
    padding: 14px 20px;
  }}
  header h1 {{ margin: 0 0 2px; font-size: 18px; }}
  header .stats {{ color: var(--muted); font-size: 13px; margin-bottom: 10px; }}
  .controls {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
  #search {{
    flex: 1 1 220px; padding: 7px 10px; border-radius: 8px;
    border: 1px solid var(--border); background: var(--bg); color: var(--text); font-size: 14px;
  }}
  .chip {{
    padding: 4px 10px; border-radius: 999px; border: 1px solid var(--border);
    background: var(--bg); color: var(--muted); font-size: 12.5px; cursor: pointer; user-select: none;
    white-space: nowrap;
  }}
  .chip.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
  main {{ max-width: 980px; margin: 0 auto; padding: 16px 20px 60px; }}
  .cat-heading {{
    margin: 26px 0 10px; font-size: 15px; font-weight: 700; color: var(--muted);
    display: flex; align-items: center; gap: 8px;
  }}
  .cat-heading .n {{ font-weight: 400; font-size: 12.5px; }}
  .card {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
    padding: 14px 16px; margin-bottom: 10px; scroll-margin-top: 130px;
  }}
  .card.dim {{ display: none; }}
  .card-top {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 10px; }}
  .card-top .name {{ font-size: 16px; font-weight: 700; }}
  .card-top .id {{ color: var(--muted); font-size: 12px; font-family: ui-monospace, Menlo, monospace; }}
  .badge {{ font-size: 11.5px; padding: 2px 8px; border-radius: 6px; font-weight: 600; }}
  .badge.rule {{ background: var(--rule-bg); color: var(--rule); }}
  .badge.rule_weak {{ background: var(--rule_weak-bg); color: var(--rule_weak); }}
  .badge.vision {{ background: var(--vision-bg); color: var(--vision); }}
  .badge.manual {{ background: var(--manual-bg); color: var(--manual); }}
  .badge.posture {{ background: var(--posture-bg); color: var(--posture); }}
  .badge.action {{ background: var(--action-bg); color: var(--action); }}
  .badge.ref {{ background: var(--bg); color: var(--muted); border: 1px solid var(--border); }}
  .aliases {{ color: var(--muted); font-size: 12.5px; margin-top: 2px; }}
  .section {{ margin-top: 10px; font-size: 13.5px; }}
  .section .label {{ color: var(--muted); font-size: 11.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; margin-bottom: 3px; }}
  ul.errs {{ margin: 4px 0 0; padding-left: 18px; }}
  .rules-table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; margin-top: 4px; }}
  .rules-table th, .rules-table td {{ text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--border); }}
  .rules-table th {{ color: var(--muted); font-weight: 600; }}
  .rules-table .note {{ color: var(--muted); font-style: italic; }}
  .confusable {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }}
  .confusable a {{
    font-size: 12px; padding: 2px 8px; border-radius: 6px; background: var(--bg);
    border: 1px solid var(--border); color: var(--accent); text-decoration: none;
  }}
  .confusable a:hover {{ border-color: var(--accent); }}
  .empty-hint {{ color: var(--muted); text-align: center; padding: 40px 0; }}
</style>
</head>
<body>
<header>
  <h1>攀岩动作知识库</h1>
  <div class="stats">{stats}</div>
  <div class="controls">
    <input id="search" type="text" placeholder="搜索 id / 中文名 / 别名…">
    <span class="chip active" data-group="cat" data-val="__all__">全部分类</span>
    {cat_chips}
  </div>
  <div class="controls" style="margin-top:6px">
    <span class="chip active" data-group="det" data-val="__all__">全部可判性</span>
    {det_chips}
    <span class="chip active" data-group="kind" data-val="__all__">全部类型</span>
    {kind_chips}
  </div>
</header>
<main id="main">
{body}
<div class="empty-hint" id="empty-hint" style="display:none">没有匹配的动作</div>
</main>
<script>
const search = document.getElementById('search');
const cards = Array.from(document.querySelectorAll('.card'));
const state = {{ cat: '__all__', det: '__all__', kind: '__all__', q: '' }};

document.querySelectorAll('.chip').forEach(chip => {{
  chip.addEventListener('click', () => {{
    const group = chip.dataset.group;
    document.querySelectorAll('.chip[data-group="' + group + '"]').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    state[group] = chip.dataset.val;
    applyFilter();
  }});
}});
search.addEventListener('input', () => {{ state.q = search.value.trim().toLowerCase(); applyFilter(); }});

function applyFilter() {{
  let visible = 0;
  cards.forEach(card => {{
    const matchCat = state.cat === '__all__' || card.dataset.cat === state.cat;
    const matchDet = state.det === '__all__' || card.dataset.det === state.det;
    const matchKind = state.kind === '__all__' || card.dataset.kind === state.kind;
    const matchQ = !state.q || card.dataset.search.includes(state.q);
    const show = matchCat && matchDet && matchKind && matchQ;
    card.classList.toggle('dim', !show);
    if (show) visible++;
  }});
  document.querySelectorAll('.cat-heading').forEach(h => {{
    const cat = h.dataset.cat;
    const anyVisible = cards.some(c => c.dataset.cat === cat && !c.classList.contains('dim'));
    h.style.display = anyVisible ? '' : 'none';
  }});
  document.getElementById('empty-hint').style.display = visible === 0 ? '' : 'none';
}}

document.querySelectorAll('.confusable a').forEach(a => {{
  a.addEventListener('click', e => {{
    e.preventDefault();
    const target = document.getElementById(a.getAttribute('href').slice(1));
    if (target) {{
      document.querySelectorAll('.chip[data-group="cat"]').forEach(c => c.classList.remove('active'));
      document.querySelector('.chip[data-group="cat"][data-val="__all__"]').classList.add('active');
      document.querySelectorAll('.chip[data-group="det"]').forEach(c => c.classList.remove('active'));
      document.querySelector('.chip[data-group="det"][data-val="__all__"]').classList.add('active');
      document.querySelectorAll('.chip[data-group="kind"]').forEach(c => c.classList.remove('active'));
      document.querySelector('.chip[data-group="kind"][data-val="__all__"]').classList.add('active');
      state.cat = '__all__'; state.det = '__all__'; state.kind = '__all__';
      applyFilter();
      target.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
      target.style.outline = '2px solid var(--accent)';
      setTimeout(() => target.style.outline = '', 1500);
    }}
  }});
}});
</script>
</body>
</html>
"""


def esc(s):
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_rules_table(rules):
    if not rules:
        return ""
    rows = []
    for r in rules:
        feature = esc(r.get("feature", ""))
        rng = r.get("range")
        rng_s = f"[{rng[0]}, {rng[1]}]" if isinstance(rng, list) and len(rng) == 2 else ""
        side = esc(r.get("side", ""))
        soft = r.get("soft", "")
        weight = r.get("weight", "")
        gate = "是" if r.get("gate") else ""
        note = esc(r.get("note", ""))
        rows.append(
            f"<tr><td>{feature}</td><td>{rng_s}</td><td>{side}</td><td>{soft}</td>"
            f"<td>{weight}</td><td>{gate}</td><td class='note'>{note}</td></tr>"
        )
    return (
        "<div class='section'><div class='label'>Pose Rules</div>"
        "<table class='rules-table'><thead><tr>"
        "<th>feature</th><th>range</th><th>side</th><th>soft</th><th>weight</th><th>gate</th><th>note</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def render_card(m):
    mid = esc(m["id"])
    name = esc(m.get("name_zh", ""))
    aliases = m.get("aliases") or []
    kind = m.get("kind", "")
    det = m.get("detectability", "")
    book_ref = esc(m.get("book_ref", ""))
    desc = esc(m.get("description", ""))
    when = esc(m.get("when_to_use", ""))
    cues = esc(m.get("visual_cues_for_claude", ""))
    errs = m.get("common_errors") or []
    confusable = m.get("confusable_with") or []
    min_hold = m.get("min_hold_s")

    errs_html = ""
    if errs:
        items = "".join(f"<li>{esc(e)}</li>" for e in errs)
        errs_html = f"<div class='section'><div class='label'>常见错误</div><ul class='errs'>{items}</ul></div>"

    confusable_html = ""
    if confusable:
        links = "".join(f"<a href='#{esc(c)}'>{esc(c)}</a>" for c in confusable)
        confusable_html = f"<div class='section'><div class='label'>易混淆</div><div class='confusable'>{links}</div></div>"

    hold_html = ""
    if min_hold is not None:
        hold_html = f"<span class='badge ref'>min_hold {min_hold}s</span>"

    search_blob = esc(
        " ".join([mid, name, " ".join(aliases), m.get("category", ""), book_ref])
    ).lower()

    return f"""
<div class="card" id="{mid}" data-cat="{esc(m.get('category',''))}" data-det="{esc(det)}" data-kind="{esc(kind)}" data-search="{search_blob}">
  <div class="card-top">
    <span class="name">{name}</span>
    <span class="id">{mid}</span>
    <span class="badge {esc(kind)}">{KIND_LABEL.get(kind, kind)}</span>
    <span class="badge {esc(det)}">{DETECT_LABEL.get(det, det)}</span>
    <span class="badge ref">{book_ref}</span>
    {hold_html}
  </div>
  {"<div class='aliases'>别名：" + esc('、'.join(aliases)) + "</div>" if aliases else ""}
  <div class="section">{desc}</div>
  {"<div class='section'><div class='label'>适用情境</div>" + when + "</div>" if when else ""}
  {"<div class='section'><div class='label'>视觉线索</div>" + cues + "</div>" if cues else ""}
  {render_rules_table(m.get("pose_rules"))}
  {errs_html}
  {confusable_html}
</div>
"""


def main():
    moves = json.loads(MOVES_JSON.read_text(encoding="utf-8"))

    categories = sorted({m.get("category", "") for m in moves})
    by_cat = {}
    for m in moves:
        by_cat.setdefault(m.get("category", ""), []).append(m)

    cat_counts = {c: len(v) for c, v in by_cat.items()}
    det_counts = {}
    kind_counts = {}
    for m in moves:
        det_counts[m.get("detectability", "")] = det_counts.get(m.get("detectability", ""), 0) + 1
        kind_counts[m.get("kind", "")] = kind_counts.get(m.get("kind", ""), 0) + 1

    cat_chips = "".join(
        f'<span class="chip" data-group="cat" data-val="{esc(c)}">{esc(c)} ({cat_counts[c]})</span>'
        for c in categories
    )
    det_chips = "".join(
        f'<span class="chip" data-group="det" data-val="{esc(d)}">{DETECT_LABEL.get(d,d)} ({det_counts[d]})</span>'
        for d in ["rule", "rule_weak", "vision", "manual"] if d in det_counts
    )
    kind_chips = "".join(
        f'<span class="chip" data-group="kind" data-val="{esc(k)}">{KIND_LABEL.get(k,k)} ({kind_counts[k]})</span>'
        for k in ["posture", "action"] if k in kind_counts
    )

    body_parts = []
    for cat in categories:
        items = by_cat[cat]
        body_parts.append(
            f"<div class='cat-heading' data-cat='{esc(cat)}'>{esc(cat)} "
            f"<span class='n'>({len(items)})</span></div>"
        )
        for m in items:
            body_parts.append(render_card(m))

    stats = (
        f"共 {len(moves)} 个动作 · "
        + " / ".join(f"{c} {n}" for c, n in cat_counts.items())
    )

    html = TEMPLATE.format(
        stats=esc(stats),
        cat_chips=cat_chips,
        det_chips=det_chips,
        kind_chips=kind_chips,
        body="".join(body_parts),
    )
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"✅ 已生成 {OUT_HTML}（{len(moves)} 个动作）")


if __name__ == "__main__":
    main()
