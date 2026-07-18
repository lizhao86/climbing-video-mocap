#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
climb_journal_edit.py —— 旅程账本·填写服务（J1 补充，2026-07-19）

起一个只监听本机的小服务，浏览器里直接填每条线的元数据（难度/完攀/岩馆…）和身高。
点「保存」→ 写 素材/<片名>/线路.json + 账本配置.json → 自动重跑聚合与账本页 → 跳到账本。

用法（或双击 打开账本填写.bat）:
    python climb_journal_edit.py          # 起服务并自动开浏览器 http://127.0.0.1:8765/

账本页/报告卡也经由本服务打开（同端口静态文件），报告卡链接可直接点。
分层不破：本文件只是录入 UI + 写 sidecar，口径仍在 climb_journal.py。
"""
import html
import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

PORT = 8765
MATERIAL_DIR = "素材"
SIDECAR_NAME = "线路.json"
CONFIG_PATH = "账本配置.json"
LEDGER_HTML = "攀岩账本.html"

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_bases():
    """有 数据/ 的素材文件夹名（= 账本记录），按 journal 日期序，journal 缺失按名称。"""
    j = load_json(os.path.join(ROOT, MATERIAL_DIR, "journal.json"))
    order = {e["base"]: i for i, e in enumerate(j.get("entries", []))}
    dates = {e["base"]: e.get("date") or "" for e in j.get("entries", [])}
    bases = []
    mdir = os.path.join(ROOT, MATERIAL_DIR)
    for name in sorted(os.listdir(mdir)):
        if os.path.isdir(os.path.join(mdir, name, "数据")):
            bases.append(name)
    bases.sort(key=lambda b: (-order.get(b, -1), b), reverse=False)
    # 新的在前（journal entries 按日期升序 → 反过来）
    bases.sort(key=lambda b: order.get(b, -1), reverse=True)
    return bases, dates


def edit_page():
    bases, dates = list_bases()
    height = load_json(os.path.join(ROOT, CONFIG_PATH)).get("身高_m")
    cards = []
    for b in bases:
        sc = load_json(os.path.join(ROOT, MATERIAL_DIR, b, SIDECAR_NAME))
        sent = sc.get("完攀")
        sel = {"": "", True: "yes", False: "no"}.get(sent, "")
        cards.append(f"""
<div class="card" data-base="{esc(b)}">
  <div class="head"><b>{esc(b)}</b><span class="mono date">{esc(dates.get(b, ""))}</span></div>
  <div class="grid">
    <label>难度<input name="grade" value="{esc(sc.get("难度"))}" placeholder="V4 / 5.10b"></label>
    <label>完攀<select name="sent">
      <option value="" {"selected" if sel == "" else ""}>未填</option>
      <option value="yes" {"selected" if sel == "yes" else ""}>完攀 ✓</option>
      <option value="no" {"selected" if sel == "no" else ""}>没完攀</option>
    </select></label>
    <label>岩馆<input name="gym" value="{esc(sc.get("岩馆"))}" placeholder="岩馆名/野外"></label>
    <label>线路名<input name="route_name" value="{esc(sc.get("线路名"))}" placeholder="选填，同一条线重复爬时用"></label>
    <label class="wide">备注<input name="note" value="{esc(sc.get("备注"))}" placeholder="选填"></label>
  </div>
</div>""")
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>账本填写</title>
<style>
:root{{--bg:#0b0c0f;--surface:#14161b;--surface2:#1b1e25;--line:#262a33;
--ink:#e9ecf1;--ink2:#a2a9b8;--ink3:#6b7280;--accent:#e08a42;--rest:#5fa07a;
--sans:"Space Grotesk","Microsoft YaHei","PingFang SC",sans-serif;
--mono:"Space Mono",ui-monospace,monospace}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.6}}
.wrap{{max-width:760px;margin:0 auto;padding:40px 20px 120px}}
.mono{{font-family:var(--mono)}}
h1{{font-size:26px;margin:0}}
.sub{{color:var(--ink3);font-size:13px;margin-top:4px}}
.card{{background:var(--surface);border:1px solid var(--line);padding:16px;margin-top:14px}}
.head{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px}}
.head b{{font-size:16px}} .date{{font-size:12px;color:var(--ink3)}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
label{{font-size:12px;color:var(--ink2);display:flex;flex-direction:column;gap:4px}}
label.wide{{grid-column:1/-1}}
input,select{{background:var(--surface2);border:1px solid var(--line);color:var(--ink);
padding:8px 10px;font-size:14px;font-family:var(--sans);border-radius:4px}}
input:focus,select:focus{{outline:1px solid var(--accent)}}
.hcard{{background:var(--surface);border:1px solid var(--line);padding:16px;margin-top:20px;
display:flex;align-items:center;gap:14px}}
.hcard input{{width:110px}}
.bar{{position:fixed;left:0;right:0;bottom:0;background:rgba(12,14,18,.92);
border-top:1px solid var(--line);padding:12px 20px;display:flex;gap:14px;
align-items:center;justify-content:center;backdrop-filter:blur(6px)}}
button{{background:var(--accent);color:#14161b;border:0;font-weight:700;font-size:15px;
padding:10px 26px;border-radius:4px;cursor:pointer;font-family:var(--sans)}}
button:disabled{{opacity:.5;cursor:wait}}
#msg{{font-size:13px;color:var(--ink2)}}
a{{color:var(--accent)}}
@media(max-width:560px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">
<h1>账本填写</h1>
<div class="sub">填完点底下「保存并更新账本」，自动写回并刷新账本页。不知道的留空没关系。</div>
<div class="hcard"><label>身高（米）<input id="height" value="{esc(height) if height else ""}"
 placeholder="如 1.75"></label>
<span class="sub">填了身高，账本的爬升就从「身长」换算成米。</span></div>
{"".join(cards)}
</div>
<div class="bar"><button id="save">保存并更新账本</button><span id="msg"></span></div>
<script>
document.getElementById('save').onclick = async () => {{
  const btn = document.getElementById('save'), msg = document.getElementById('msg');
  const entries = Array.from(document.querySelectorAll('.card')).map(c => ({{
    base: c.dataset.base,
    grade: c.querySelector('[name=grade]').value.trim(),
    sent: c.querySelector('[name=sent]').value,
    gym: c.querySelector('[name=gym]').value.trim(),
    route_name: c.querySelector('[name=route_name]').value.trim(),
    note: c.querySelector('[name=note]').value.trim(),
  }}));
  const height = document.getElementById('height').value.trim();
  btn.disabled = true; msg.textContent = '保存中…';
  try {{
    const r = await fetch('/save', {{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{height_m: height, entries}})}});
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || '保存失败');
    msg.textContent = '已保存，正在打开账本…';
    location.href = '/{LEDGER_HTML}';
  }} catch (e) {{
    msg.textContent = '出错了：' + e.message; btn.disabled = false;
  }}
}};
</script></body></html>"""


def do_save(payload):
    # 身高
    h_raw = str(payload.get("height_m") or "").strip()
    height = None
    if h_raw:
        height = float(h_raw)
        if not (1.0 <= height <= 2.5):
            raise ValueError("身高要填米，例如 1.75")
    with open(os.path.join(ROOT, CONFIG_PATH), "w", encoding="utf-8") as f:
        json.dump({"身高_m": height}, f, ensure_ascii=False, indent=2)

    # 各线路 sidecar（保留 日期 等未上表单的字段）
    for e in payload.get("entries", []):
        base = e.get("base", "")
        if not base or any(c in base for c in "/\\.."):
            raise ValueError("非法片名: %r" % base)
        folder = os.path.join(ROOT, MATERIAL_DIR, base)
        if not os.path.isdir(folder):
            raise ValueError("素材不存在: %s" % base)
        sc_path = os.path.join(folder, SIDECAR_NAME)
        sc = load_json(sc_path)
        sc["线路名"] = e.get("route_name", "")
        sc["岩馆"] = e.get("gym", "")
        sc["难度"] = e.get("grade", "")
        sc["完攀"] = {"yes": True, "no": False}.get(e.get("sent"), None)
        sc.setdefault("日期", "")
        sc["备注"] = e.get("note", "")
        with open(sc_path, "w", encoding="utf-8") as f:
            json.dump(sc, f, ensure_ascii=False, indent=2)

    # 重跑聚合 + 账本页
    for script in ("climb_journal.py", "climb_journal_card.py"):
        r = subprocess.run([PY, script], cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", timeout=300,
                           env={**os.environ, "PYTHONUTF8": "1",
                                "PYTHONIOENCODING": "utf-8"})
        if r.returncode != 0:
            raise RuntimeError("%s 失败: %s" % (script, (r.stderr or "")[-400:]))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def do_GET(self):
        if self.path in ("/", "/edit"):
            body = edit_page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self):
        if self.path != "/save":
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n).decode("utf-8"))
            do_save(payload)
            body = json.dumps({"ok": True}).encode("utf-8")
        except Exception as exc:
            body = json.dumps({"ok": False, "error": str(exc)},
                              ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # 静默，别刷老板的控制台


def main():
    addr = ("127.0.0.1", PORT)
    srv = ThreadingHTTPServer(addr, Handler)
    url = "http://127.0.0.1:%d/" % PORT
    print("账本填写服务: %s  （填完保存会自动更新账本页；关掉这个窗口即停止）" % url)
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
