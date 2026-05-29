# Claude Code WeChat Notify 🔔

> Never miss a Claude Code permission prompt — get push notifications on WeChat when you're AFK.
>
> Claude Code 弹出权限确认弹窗时，通过企业微信推送通知到你的手机。

```
Claude Code permission dialog
       │
       ▼
Notification Hook (settings.json)
       │
       ▼
wechat-notify.py ──HTTP──► wechat-daemon.py ──WebSocket──► 企业微信 ──► 手机微信
```

## Quick Start / 快速开始

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Configure

```bash
cp wechat-notify-config.example.json wechat-notify-config.json
```

Edit `wechat-notify-config.json` with your WeCom BotID and Secret. See [Setup](#配置步骤--setup) for details.

### 3. Run

```bash
python wechat-daemon.py
```

Then add the hook to Claude Code's `settings.json` (see [Configure Claude Code Hook](#4-配置-claude-code-hook--configure-claude-code-hook)).

---

## 工作原理 / How it works

- **wechat-daemon.py** — 后台守护进程，维护到企业微信服务器的 WebSocket 长连接 / background process maintaining a WebSocket long-connection to WeCom
- **wechat-notify.py** — 被 Claude Code hook 调用，通过本地守护进程发送通知 / called by Claude Code's hook, sends notification via the local daemon
- **智能延迟 / Smart Delay** — 权限弹窗出现后等待 8 秒，若用户在 8 秒内操作则不推送；连续弹窗会不断重置计时器，只有真正离开电脑才会收到通知。端到端延迟约 15 秒（含 hook 启动 + 8s 等待 + 网络传输）。/ After a permission dialog appears, waits 8 seconds before sending. If you respond within 8s, no notification is sent. Consecutive dialogs reset the timer — you're only notified when truly away. End-to-end latency is ~15s (hook startup + 8s wait + network).

## 环境要求 / Prerequisites

- Python 3.8+
- 企业微信账号（免费个人注册即可） / A WeCom account (free personal registration)
- Claude Code CLI

## 配置步骤 / Setup

### 1. 安装依赖 / Install dependencies

```bash
pip install -r requirements.txt
```

### 2. 创建企业微信智能机器人 / Create a WeCom AI Bot

1. 浏览器打开 [企业微信管理后台](https://work.weixin.qq.com) / Open [WeCom Admin Console](https://work.weixin.qq.com)
2. 进入「应用管理」→「智能机器人」/ Go to **App Management** → **Smart Bot (智能机器人)**
3. 手动创建机器人，选择 **API 模式** / Create a bot manually, select **API mode**
4. 连接方式选择 **长连接** / Choose **Long Connection (长连接)** as connection method
5. 复制 **BotID** 和 **Secret**（Secret 仅显示一次！）/ Copy **BotID** and **Secret** (shown only once!)

### 3. 填写配置 / Configure

```bash
cp wechat-notify-config.example.json wechat-notify-config.json
```

编辑 `wechat-notify-config.json`：

```json
{
    "bot_id": "你的BotID",
    "secret": "你的Secret"
}
```

### 4. 配置 Claude Code Hook / Configure Claude Code Hook

在 Claude Code 的 `settings.json`（`~/.claude/settings.json` 或 `.claude/settings.json`）中添加：

Add the following to your Claude Code `settings.json`:

```json
{
  "hooks": {
    "Notification": [
      {
        "matcher": "permission_prompt",
        "hooks": [
          {
            "type": "command",
            "command": "python /path/to/wechat-notify.py"
          }
        ]
      }
    ]
  }
}
```

将 `/path/to/wechat-notify.py` 替换为实际绝对路径。 / Replace `/path/to/wechat-notify.py` with the actual absolute path.

### 5. 启动守护进程 / Start the daemon

```bash
python wechat-daemon.py
```

保持终端窗口打开。首次运行时，在手机企业微信中给机器人发任意消息——这一步会捕获你的 chat ID（仅需一次）。

Keep this terminal window open. On first run, send any message to the bot from your phone's WeCom app — this captures your chat ID (one-time setup).

## 日常使用 / Usage

1. 启动守护进程：`python wechat-daemon.py` / Start the daemon
2. 正常使用 Claude Code / Use Claude Code normally
3. Claude Code 需要确认时，手机微信即收到通知 / You'll get a WeChat notification whenever approval is needed

## 常见问题 / Troubleshooting

| 问题 Problem | 解决方案 Solution |
|---------|----------|
| 未收到通知 / No notification | 检查守护进程是否运行且已认证 / Check daemon is running and authenticated |
| chatid 未捕获 / "chatid not captured" | 在手机企业微信中给机器人发一条消息 / Send any message to the bot from WeCom on your phone |
| 连接被拒绝 / Connection refused | 确保守护进程先于通知启动 / Make sure the daemon is running before the hook fires |

---

## Disclaimer / 免责声明

> 本项目由 [Claude Code](https://claude.ai/code) 构建。BotID 和 Secret 拥有通过企业微信机器人发送消息的完整权限——使用风险自负。作者对任何滥用、数据泄露或账户问题不承担责任。
>
> This project was built with [Claude Code](https://claude.ai/code). Your BotID and Secret grant full access to send messages via your WeCom bot — use at your own risk. The authors assume no liability for any misuse, data leakage, or account issues.
