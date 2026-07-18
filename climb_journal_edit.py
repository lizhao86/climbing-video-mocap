#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
climb_journal_edit.py —— 旅程账本·填写服务（2026-07-19；同日改为账本页合一）

起一个只监听本机的小服务，打开的就是账本页本身（可编辑版）：每条记录行内直接填
难度/完攀/岩馆/线路名/备注，底部保存条填身高。点「保存并更新账本」→ 写
素材/<片名>/线路.json + 账本配置.json → 重跑聚合 + 重新生成静态账本页 → 页面刷新。

用法（或双击 打开账本填写.bat）:
    python climb_journal_edit.py     # 起服务并自动开浏览器；已在运行则直接打开浏览器

报告卡也经由本服务打开（同端口静态文件），记录行的「看报告卡 →」可直接点。
分层不破：页面渲染在 climb_journal_card.py（editable=True），口径在 climb_journal.py，
本文件只管 HTTP 与写 sidecar。
"""
import json
import os
import socket
import sys
import threading
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import climb_journal
import climb_journal_card as card

PORT_RANGE = range(8765, 8776)
MATERIAL_DIR = "素材"
SIDECAR_NAME = "线路.json"
CONFIG_PATH = "账本配置.json"
PING_TOKEN = "climb-journal-edit"

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def rebuild():
    """重跑聚合 + 重新生成静态账本页（直接函数调用，避免子进程编码坑）。"""
    climb_journal.main()
    card.main()


def do_save(payload):
    h_raw = str(payload.get("height_m") or "").strip()
    height = None
    if h_raw:
        try:
            height = float(h_raw)
        except ValueError:
            raise ValueError("身高要填数字（米），例如 1.75")
        if not (1.0 <= height <= 2.5):
            raise ValueError("身高要填米，例如 1.75")
    with open(os.path.join(ROOT, CONFIG_PATH), "w", encoding="utf-8") as f:
        json.dump({"身高_m": height}, f, ensure_ascii=False, indent=2)

    for e in payload.get("entries", []):
        base = e.get("base", "")
        if not base or any(c in base for c in "/\\..") :
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

    rebuild()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def _send(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/edit"):
            j = load_json(os.path.join(ROOT, MATERIAL_DIR, "journal.json"))
            if not j:
                rebuild()
                j = load_json(os.path.join(ROOT, MATERIAL_DIR, "journal.json"))
            self._send(card.build_page(j, editable=True).encode("utf-8"),
                       "text/html; charset=utf-8")
            return
        if self.path == "/ping":
            self._send(PING_TOKEN.encode(), "text/plain; charset=utf-8")
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
        self._send(body, "application/json; charset=utf-8")

    def log_message(self, fmt, *args):
        pass  # 静默，别刷老板的控制台


def existing_instance():
    """探测端口段里是否已有本服务在跑，有则返回其 URL。"""
    for port in PORT_RANGE:
        try:
            r = urllib.request.urlopen("http://127.0.0.1:%d/ping" % port, timeout=0.5)
            if r.read().decode() == PING_TOKEN:
                return "http://127.0.0.1:%d/" % port
        except Exception:
            continue
    return None


def main():
    url = existing_instance()
    if url:
        print("账本填写已经在运行：%s（直接打开浏览器）" % url)
        webbrowser.open(url)
        return

    srv = None
    for port in PORT_RANGE:
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if srv is None:
        print("8765-8775 端口都被占了，关掉占用的程序再试。")
        sys.exit(1)

    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    print("账本填写: %s  （在页面里填完点保存；关掉这个窗口即停止）" % url)
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
