"""企业微信智能机器人长连接守护进程
维护 ws://openws.work.weixin.qq.com 连接，接收本地 hook 请求并推送微信通知。
"""
import json
import os
import sys
import time
import uuid
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import websocket

DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(DIR, "wechat-notify-config.json")
PORT_FILE = os.path.join(DIR, ".wecom-port")
WS_URL = "wss://openws.work.weixin.qq.com"
HTTP_PORT = 19800


class Daemon:
    def __init__(self, bot_id, secret):
        self.bot_id = bot_id
        self.secret = secret
        self.ws_app = None
        self.ws = None
        self.auth_req_id = None
        self.authenticated = threading.Event()
        self.chatid = self._load_chatid()
        self.running = True
        self._pending_msg = set()
        self._delay_timer = None
        self._delay_lock = threading.RLock()

    # ── config ──────────────────────────────────────────────
    def _load_config(self):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_chatid(self, chatid):
        config = self._load_config()
        config["chatid"] = chatid
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def _load_chatid(self):
        try:
            return self._load_config().get("chatid", "")
        except Exception:
            return ""

    # ── websocket ───────────────────────────────────────────
    def start_ws(self):
        self.ws_app = websocket.WebSocketApp(
            WS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self.ws_app.run_forever(ping_interval=30)

    def _on_open(self, ws):
        self.ws = ws
        self.auth_req_id = str(uuid.uuid4())
        ws.send(json.dumps({
            "cmd": "aibot_subscribe",
            "headers": {"req_id": self.auth_req_id},
            "body": {"bot_id": self.bot_id, "secret": self.secret},
        }, ensure_ascii=False))

    def _on_message(self, ws, raw):
        data = json.loads(raw)
        headers = data.get("headers", {})
        body = data.get("body", {})
        cmd = data.get("cmd", "")
        errcode = data.get("errcode", -1)
        req_id = headers.get("req_id", "")

        # 认证响应（无 cmd 字段，通过 req_id 匹配）
        if req_id == self.auth_req_id:
            if errcode == 0:
                self.authenticated.set()
                self._log(f"认证成功。chatid={'已有' if self.chatid else '等待首次消息'}")
            else:
                self._log(f"认证失败: {data.get('errmsg')}")

        # 用户发消息过来 → 记录 chatid
        if cmd in ("aibot_msg_callback", "aibot_event_callback"):
            chattype = body.get("chattype", "single")
            if chattype == "single":
                new_chatid = body.get("from", {}).get("userid", "")
            else:
                new_chatid = body.get("chatid", "")
            if new_chatid:
                self.chatid = new_chatid
                self._save_chatid(new_chatid)
                self._log(f"捕获 chatid: {new_chatid}")

        # send_msg 响应
        if req_id and req_id in self._pending_msg:
            self._pending_msg.discard(req_id)
            if errcode == 0:
                self._log("推送成功")
            else:
                self._log(f"推送失败: {data.get('errmsg')}")

    def _on_error(self, ws, error):
        self._log(f"WS 错误: {error}")

    def _on_close(self, ws, status, msg):
        self.authenticated.clear()
        self._log(f"连接断开 (status={status})，5秒后重连...")
        time.sleep(5)
        if self.running:
            self.start_ws()

    def send_delayed(self, content, delay=8):
        """取消上一个待推送，启动新的 delay 秒定时器。用户连续操作时不断重置计时。"""
        with self._delay_lock:
            self.cancel_pending()
            self._delay_timer = threading.Timer(delay, self._do_delayed_send, args=[content])
            self._delay_timer.start()
            return True, f"将在 {delay}s 后推送"

    def cancel_pending(self):
        """取消待推送的定时器（用户已操作，无需提醒）。"""
        with self._delay_lock:
            if self._delay_timer is not None:
                self._delay_timer.cancel()
                self._delay_timer = None
                return True, "已取消"
            return False, "无待推送"

    def _do_delayed_send(self, content):
        with self._delay_lock:
            self._delay_timer = None
        ok, msg = self.send_msg(content)
        if ok:
            self._log("延迟推送成功")
        else:
            self._log(f"延迟推送失败: {msg}")

    def send_msg(self, content):
        if not self.ws or not self.authenticated.is_set():
            return False, "未连接"
        if not self.chatid:
            return False, "未获取 chatid，请先在手机企业微信给机器人发一条消息（如 hello）"
        req_id = str(uuid.uuid4())
        self._pending_msg.add(req_id)
        self.ws.send(json.dumps({
            "cmd": "aibot_send_msg",
            "headers": {"req_id": req_id},
            "body": {
                "chatid": self.chatid,
                "chat_type": 1,
                "msgtype": "markdown",
                "markdown": {"content": content},
            },
        }))
        return True, "ok"

    def _log(self, msg):
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] {msg}", file=sys.stderr)


# ── HTTP server ────────────────────────────────────────────────
_daemon = None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            ok = _daemon.authenticated.is_set()
            has_pending = _daemon._delay_timer is not None
            self._respond(200, {"ok": ok, "chatid": bool(_daemon.chatid), "pending": has_pending})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/send":
            self._handle_send()
        elif self.path == "/send-delayed":
            self._handle_send_delayed()
        elif self.path == "/cancel-pending":
            self._handle_cancel_pending()
        else:
            self._respond(404, {"error": "not found"})

    def _handle_send(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length > 0 else {}
        content = body.get("content", "Claude Code needs your approval")
        ok, msg = _daemon.send_msg(content)
        self._respond(200 if ok else 503, {"ok": ok, "message": msg})

    def _handle_send_delayed(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length > 0 else {}
        content = body.get("content", "Claude Code needs your approval")
        delay = int(body.get("delay", 8))
        ok, msg = _daemon.send_delayed(content, delay)
        self._respond(200 if ok else 503, {"ok": ok, "message": msg})

    def _handle_cancel_pending(self):
        ok, msg = _daemon.cancel_pending()
        self._respond(200, {"ok": ok, "message": msg})

    def _respond(self, code, data):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass  # suppress default logging


def find_port(start=19800):
    for p in range(start, start + 100):
        try:
            s = socket.socket()
            s.bind(("127.0.0.1", p))
            s.close()
            return p
        except OSError:
            continue
    return start


def main():
    global _daemon

    try:
        config = json.load(open(CONFIG_PATH, "r", encoding="utf-8"))
    except Exception:
        print("无法读取 wechat-notify-config.json", file=sys.stderr)
        sys.exit(1)

    bot_id = config.get("bot_id", "")
    secret = config.get("secret", "")
    if not bot_id or not secret or "你的BotID" in bot_id:
        print("请先在 wechat-notify-config.json 中填写 bot_id 和 secret", file=sys.stderr)
        sys.exit(1)

    port = find_port(HTTP_PORT)
    with open(PORT_FILE, "w") as f:
        f.write(str(port))

    _daemon = Daemon(bot_id, secret)

    # WebSocket 在后台线程
    ws_thread = threading.Thread(target=_daemon.start_ws, daemon=True)
    ws_thread.start()

    # HTTP server 在主线程
    httpd = HTTPServer(("127.0.0.1", port), Handler)
    print(f"[daemon] HTTP 服务运行在 http://127.0.0.1:{port}", file=sys.stderr)
    print(f"[daemon] 等待 WebSocket 认证...", file=sys.stderr)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        _daemon.running = False
        print("\n[daemon] 已退出", file=sys.stderr)


if __name__ == "__main__":
    main()
