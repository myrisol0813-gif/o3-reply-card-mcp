#!/usr/bin/env python3
"""o3 Reply Card MCP.

A dependency-free Streamable HTTP MCP server that gives an o3 reply a visible
MCP Apps card and returns the same reply in model-visible tool-result text.

Run directly:
    python3 server.py [port]

The v0.1 server keeps at most ten records per session in process memory. It
does not write reply content to disk and does not call external services.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


SERVICE_NAME = "o3-reply-card-mcp"
SERVICE_VERSION = "0.1.0"
PROTOCOL_FALLBACK = "2025-06-18"
WIDGET_URI = "ui://widget/o3-reply-card-v1.html"
WIDGET_MIME = "text/html;profile=mcp-app"

DEFAULT_SESSION_ID = "o3-default"
DEFAULT_TITLE = "o3 回复"
DEFAULT_FOOTER = "本轮结束"
DEFAULT_SKIN = "winter"
DEFAULT_HISTORY_LIMIT = 10

MAX_HISTORY = 10
MAX_BODY_CHARS = 8000
MAX_CONTINUITY_CHARS = 1500
MAX_USER_ANCHOR_CHARS = 1000
MAX_SESSION_ID_CHARS = 200
MAX_TITLE_CHARS = 200
MAX_FOOTER_CHARS = 300
MAX_REQUEST_BYTES = 1_000_000

# Loopback by default. TLS, authentication, and public exposure belong to the
# deployment rather than this intentionally small reference server.
BIND_HOST = os.environ.get("MCP_BIND", "127.0.0.1")

_HISTORY: dict[str, deque[dict[str, str]]] = {}
_HISTORY_LOCK = threading.RLock()


WIDGET_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {
      color-scheme: light dark;
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --paper: #f7fafc;
      --paper-soft: #edf3f7;
      --ink: #23313d;
      --muted: #657889;
      --faint: #8b9aa7;
      --line: rgba(91, 116, 137, .34);
      --line-soft: rgba(91, 116, 137, .16);
      --accent: #7898b3;
      --accent-soft: #dce8f1;
      --accent-ink: #38566d;
      --shadow: rgba(45, 68, 87, .12);
      --glow: rgba(255, 255, 255, .66);
    }

    :root[data-skin="paper"] {
      --paper: #fffaf0;
      --paper-soft: #f8eddc;
      --ink: #3f3429;
      --muted: #796a5a;
      --faint: #998b7c;
      --line: rgba(145, 111, 73, .32);
      --line-soft: rgba(145, 111, 73, .15);
      --accent: #b88755;
      --accent-soft: #f0dfc8;
      --accent-ink: #6d4c2e;
      --shadow: rgba(96, 66, 35, .12);
      --glow: rgba(255, 255, 255, .58);
    }

    :root[data-skin="coast"] {
      --paper: #102a3b;
      --paper-soft: #17394d;
      --ink: #f0eadb;
      --muted: #b9c6cb;
      --faint: #8fa4ad;
      --line: rgba(205, 173, 103, .44);
      --line-soft: rgba(205, 173, 103, .20);
      --accent: #c7a45c;
      --accent-soft: #294b59;
      --accent-ink: #f0d995;
      --shadow: rgba(3, 16, 26, .28);
      --glow: rgba(232, 206, 145, .09);
    }

    :root[data-theme="dark"]:not([data-skin="coast"]) {
      --paper: #1e2932;
      --paper-soft: #263640;
      --ink: #edf3f6;
      --muted: #bac8d0;
      --faint: #91a3ad;
      --line: rgba(151, 179, 199, .40);
      --line-soft: rgba(151, 179, 199, .18);
      --accent: #9dbbd0;
      --accent-soft: #304651;
      --accent-ink: #dcecf6;
      --shadow: rgba(0, 0, 0, .28);
      --glow: rgba(255, 255, 255, .05);
    }

    :root[data-theme="dark"][data-skin="paper"] {
      --paper: #302920;
      --paper-soft: #3c3227;
      --ink: #f7eee1;
      --muted: #d3c2ae;
      --faint: #ac9a86;
      --line: rgba(207, 172, 128, .38);
      --line-soft: rgba(207, 172, 128, .17);
      --accent: #d1a572;
      --accent-soft: #4b3d2e;
      --accent-ink: #f4d6af;
    }

    @media (prefers-color-scheme: dark) {
      :root:not([data-theme="light"]):not([data-skin="coast"]) {
        --paper: #1e2932;
        --paper-soft: #263640;
        --ink: #edf3f6;
        --muted: #bac8d0;
        --faint: #91a3ad;
        --line: rgba(151, 179, 199, .40);
        --line-soft: rgba(151, 179, 199, .18);
        --accent: #9dbbd0;
        --accent-soft: #304651;
        --accent-ink: #dcecf6;
        --shadow: rgba(0, 0, 0, .28);
        --glow: rgba(255, 255, 255, .05);
      }
      :root:not([data-theme="light"])[data-skin="paper"] {
        --paper: #302920;
        --paper-soft: #3c3227;
        --ink: #f7eee1;
        --muted: #d3c2ae;
        --faint: #ac9a86;
        --line: rgba(207, 172, 128, .38);
        --line-soft: rgba(207, 172, 128, .17);
        --accent: #d1a572;
        --accent-soft: #4b3d2e;
        --accent-ink: #f4d6af;
      }
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      padding: 2px;
      background: transparent;
      color: var(--ink);
    }

    .card {
      position: relative;
      isolation: isolate;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 16px;
      background:
        radial-gradient(circle at 8% -14%, var(--glow), transparent 42%),
        linear-gradient(145deg, var(--paper), var(--paper-soft));
      box-shadow: 0 9px 26px var(--shadow);
      padding: 17px 18px 15px;
    }

    .card::before {
      content: "";
      position: absolute;
      inset: 0 0 auto;
      height: 3px;
      background: linear-gradient(90deg, transparent, var(--accent), transparent);
      pointer-events: none;
    }

    .topline {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--line-soft);
    }

    .identity {
      display: inline-flex;
      align-items: center;
      gap: 9px;
      min-width: 0;
    }

    .mark {
      width: 9px;
      height: 9px;
      flex: 0 0 auto;
      border: 1px solid var(--accent);
      border-radius: 50%;
      background: var(--accent-soft);
      box-shadow: 4px 0 0 -2px var(--accent);
    }

    .product-label {
      color: var(--muted);
      font-size: 11px;
      font-weight: 760;
      letter-spacing: .11em;
      line-height: 1.3;
      text-transform: uppercase;
    }

    .skin-badge {
      flex: 0 0 auto;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent-ink);
      font-size: 9px;
      font-weight: 760;
      letter-spacing: .08em;
      line-height: 1.2;
      padding: 4px 8px;
      text-transform: uppercase;
    }

    .content { padding-top: 14px; }

    .content[data-scrollable="true"] {
      overflow-y: auto;
      overscroll-behavior: contain;
      -webkit-overflow-scrolling: touch;
    }

    h1 {
      margin: 0 0 12px;
      color: var(--ink);
      font-size: 17px;
      font-weight: 720;
      letter-spacing: -.012em;
      line-height: 1.42;
    }

    .anchor {
      margin: 0 0 13px;
      border-left: 2px solid var(--accent);
      border-radius: 0 8px 8px 0;
      background: var(--accent-soft);
      color: var(--muted);
      font-size: 12px;
      line-height: 1.62;
      padding: 8px 10px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }

    .anchor[hidden], .continuity[hidden], .footer[hidden] { display: none; }

    .body-copy {
      margin: 0;
      color: var(--ink);
      font-family: inherit;
      font-size: 14px;
      font-weight: 420;
      letter-spacing: .002em;
      line-height: 1.76;
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }

    .continuity {
      margin-top: 15px;
      border-top: 1px solid var(--line-soft);
      color: var(--muted);
      padding-top: 10px;
    }

    .continuity summary {
      cursor: pointer;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .06em;
      list-style-position: outside;
      padding-left: 2px;
      text-transform: uppercase;
      user-select: none;
    }

    .continuity-copy {
      margin: 9px 0 0;
      border-radius: 9px;
      background: var(--accent-soft);
      color: var(--muted);
      font: 12px/1.62 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      overflow-wrap: anywhere;
      padding: 9px 10px;
      white-space: pre-wrap;
    }

    .footer {
      margin: 13px 0 0;
      color: var(--faint);
      font-size: 10px;
      letter-spacing: .08em;
      line-height: 1.4;
      text-align: right;
    }

    .card[data-action="read_context"] .body-copy {
      color: var(--muted);
      font-size: 13px;
    }

    .card[data-action="error"] {
      --accent: #b66767;
      --accent-soft: rgba(182, 103, 103, .14);
      --accent-ink: #914747;
    }
  </style>
</head>
<body>
  <article class="card" id="card" data-action="write_reply" aria-label="o3 reply card">
    <header class="topline">
      <span class="identity">
        <span class="mark" aria-hidden="true"></span>
        <span class="product-label" id="product-label">o3 回复用</span>
      </span>
      <span class="skin-badge" id="skin-badge">WINTER</span>
    </header>
    <main class="content" id="content">
      <h1 id="title">o3 回复</h1>
      <blockquote class="anchor" id="anchor" hidden></blockquote>
      <p class="body-copy" id="body-copy">正在准备回复卡片。</p>
      <details class="continuity" id="continuity" hidden>
        <summary>Continuity state</summary>
        <pre class="continuity-copy" id="continuity-copy"></pre>
      </details>
      <p class="footer" id="footer">本轮结束</p>
    </main>
  </article>

  <script>
    const card = document.getElementById("card");
    const content = document.getElementById("content");
    const productLabel = document.getElementById("product-label");
    const skinBadge = document.getElementById("skin-badge");
    const title = document.getElementById("title");
    const anchor = document.getElementById("anchor");
    const bodyCopy = document.getElementById("body-copy");
    const continuity = document.getElementById("continuity");
    const continuityCopy = document.getElementById("continuity-copy");
    const footer = document.getElementById("footer");
    let standardInput = {};
    let standardOutput = {};
    let standardMeta = {};
    let heightFrame = 0;
    let lastMeasuredHeight = -1;

    function asObject(value) {
      return value && typeof value === "object" ? value : {};
    }

    function resultMetaFrom(responseMeta) {
      const meta = asObject(responseMeta);
      return asObject(
        (meta.mcp_tool_result && meta.mcp_tool_result._meta) ||
        (meta.call_tool_result && meta.call_tool_result._meta) ||
        meta._meta || meta
      );
    }

    function requestIntrinsicHeight(force = false) {
      const host = window.openai || {};
      if (typeof host.notifyIntrinsicHeight !== "function") return;
      cancelAnimationFrame(heightFrame);
      heightFrame = requestAnimationFrame(() => {
        const measuredHeight = Math.ceil(document.documentElement.scrollHeight);
        if (!force && measuredHeight === lastMeasuredHeight) return;
        lastMeasuredHeight = measuredHeight;
        try { host.notifyIntrinsicHeight(); } catch (_) {}
      });
    }

    function applyHostHeightLimit(api) {
      const maxHeight = Number(api.maxHeight);
      if (!Number.isFinite(maxHeight) || maxHeight <= 0) {
        content.style.maxHeight = "";
        delete content.dataset.scrollable;
        return;
      }
      content.style.maxHeight = Math.max(210, Math.floor(maxHeight - 32)) + "px";
      content.dataset.scrollable = "true";
    }

    function setOptionalText(element, value) {
      const text = typeof value === "string" ? value : "";
      element.textContent = text;
      element.hidden = !text;
    }

    function applyData(data, api) {
      const action = data.action || "write_reply";
      const skin = ["winter", "paper", "coast"].includes(data.skin) ? data.skin : "winter";
      const isRead = action === "read_context";
      const isError = action === "error";
      document.documentElement.dataset.skin = skin;
      if (api.theme) document.documentElement.dataset.theme = api.theme;
      card.dataset.action = action;
      productLabel.textContent = isRead ? "o3 上下文读取" : (isError ? "o3 回复卡错误" : "o3 回复用");
      skinBadge.textContent = skin.toUpperCase();
      title.textContent = data.title || (isRead ? "Context Read" : "o3 回复");
      setOptionalText(anchor, data.user_anchor);
      bodyCopy.textContent = data.body || (isRead ? "本次读取没有找到记录。" : "回复正文为空。");
      const continuityText = typeof data.continuity_state === "string" ? data.continuity_state : "";
      continuityCopy.textContent = continuityText;
      continuity.hidden = !continuityText;
      setOptionalText(footer, data.footer === undefined ? "本轮结束" : data.footer);
      applyHostHeightLimit(api);
      requestIntrinsicHeight(true);
    }

    function render(event) {
      const bridge = window.openai || {};
      const eventGlobals = event && event.detail && event.detail.globals;
      const api = Object.assign({}, bridge, asObject(eventGlobals));
      const input = Object.assign({}, asObject(api.toolInput), standardInput);
      const output = Object.assign({}, asObject(api.toolOutput), standardOutput);
      const meta = Object.assign({}, resultMetaFrom(api.toolResponseMetadata), standardMeta);
      applyData(Object.assign({}, input, output, meta), api);
    }

    window.addEventListener("message", (event) => {
      if (event.source !== window.parent) return;
      const message = event.data;
      if (!message || message.jsonrpc !== "2.0") return;
      if (message.method === "ui/notifications/tool-input") {
        standardInput = asObject(message.params);
        render();
      }
      if (message.method === "ui/notifications/tool-result") {
        standardOutput = asObject(message.params && message.params.structuredContent);
        standardMeta = resultMetaFrom(message.params);
        render();
      }
    }, { passive: true });

    window.addEventListener("openai:set_globals", render);
    continuity.addEventListener("toggle", () => requestIntrinsicHeight(true));
    if (typeof ResizeObserver === "function") {
      new ResizeObserver(() => requestIntrinsicHeight()).observe(document.body);
    }
    render();
  </script>
</body>
</html>"""


TOOL_DESCRIPTION = (
    "Use this tool when the user asks you to put your main o3 reply into a visible "
    "reply card instead of the ordinary assistant message. For action=write_reply, "
    "the `body` field is the final natural-language reply itself. It is not a "
    "summary, not a task record, not a log, not reasoning notes, and not an archive "
    "entry. Preserve your normal o3 voice. Do not shorten, formalize, classify, or "
    "convert the reply into a report. After calling write_reply, the ordinary "
    "assistant message should contain at most one short sentence such as: \"请看 o3 "
    "回复卡。\" For action=read_context, read the recent rolling context for this "
    "session before writing the next reply."
)

BODY_DESCRIPTION = (
    "Required for write_reply. This is the complete natural-language reply itself, "
    "not a summary, not a log, not notes, and not a task report. Preserve the "
    "model's normal o3 voice. body 就是 o3 真正想对用户说的完整正文。调用工具只是让"
    "原本会消失的正文换一张纸留下来。"
)

TOOL = {
    "name": "o3_reply_card",
    "title": "o3 回复用",
    "description": TOOL_DESCRIPTION,
    "inputSchema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read_context", "write_reply"],
                "description": "Choose read_context to read recent o3 reply-card context before replying, or write_reply to render and store this turn's reply card.",
            },
            "session_id": {
                "type": "string",
                "maxLength": MAX_SESSION_ID_CHARS,
                "default": DEFAULT_SESSION_ID,
                "description": "Conversation/session key for the rolling in-memory context. Default: o3-default.",
            },
            "title": {
                "type": "string",
                "maxLength": MAX_TITLE_CHARS,
                "default": DEFAULT_TITLE,
                "description": "Optional card title. Default: o3 回复.",
            },
            "user_anchor": {
                "type": "string",
                "maxLength": MAX_USER_ANCHOR_CHARS,
                "description": "Optional short quote or summary of the user's current message.",
            },
            "body": {
                "type": "string",
                "maxLength": MAX_BODY_CHARS,
                "description": BODY_DESCRIPTION,
            },
            "continuity_state": {
                "type": "string",
                "maxLength": MAX_CONTINUITY_CHARS,
                "description": "Optional compact state for continuing the next turn. Keep it short and practical.",
            },
            "footer": {
                "type": "string",
                "maxLength": MAX_FOOTER_CHARS,
                "default": DEFAULT_FOOTER,
                "description": "Optional footer. Default: 本轮结束.",
            },
            "skin": {
                "type": "string",
                "enum": ["winter", "paper", "coast"],
                "default": DEFAULT_SKIN,
                "description": "Visual skin for the card. Default: winter.",
            },
            "history_limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_HISTORY,
                "default": DEFAULT_HISTORY_LIMIT,
                "description": "Maximum number of recent context records to return. Default: 10. Hard max: 10.",
            },
        },
        "required": ["action"],
    },
    "securitySchemes": [{"type": "noauth"}],
    "annotations": {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
    "_meta": {
        "securitySchemes": [{"type": "noauth"}],
        "ui": {"resourceUri": WIDGET_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": WIDGET_URI,
        "openai/toolInvocation/invoking": "Preparing o3 reply card…",
        "openai/toolInvocation/invoked": "o3 reply card ready",
    },
}


class InputError(ValueError):
    """A clear, model-correctable tool-input error."""


def _string_arg(args: dict[str, Any], name: str, default: str = "", *, max_chars: int, required: bool = False) -> str:
    value = args[name] if name in args else default
    if value is None and not required:
        value = default
    if not isinstance(value, str):
        raise InputError(f"{name} must be a string.")
    if required and not value.strip():
        raise InputError(f"{name} is required and must not be empty.")
    if len(value) > max_chars:
        next_step = (
            "Shorten body and keep only compact next-turn facts in continuity_state."
            if name == "body"
            else f"Shorten {name} and try again."
        )
        raise InputError(
            f"{name} is {len(value)} characters; the hard maximum is {max_chars}. "
            f"{next_step} The server did not truncate or store it."
        )
    return value


def validate_arguments(raw_args: Any) -> dict[str, Any]:
    """Apply defaults and enforce all v0.1 input limits without truncation."""
    if not isinstance(raw_args, dict):
        raise InputError("Tool arguments must be a JSON object.")
    unknown = sorted(set(raw_args) - set(TOOL["inputSchema"]["properties"]))
    if unknown:
        raise InputError(f"Unknown tool argument(s): {', '.join(unknown)}.")
    action = raw_args.get("action")
    if action not in {"read_context", "write_reply"}:
        raise InputError("action must be either read_context or write_reply.")

    session_id = _string_arg(
        raw_args, "session_id", DEFAULT_SESSION_ID,
        max_chars=MAX_SESSION_ID_CHARS, required=True,
    ).strip()
    if not session_id:
        raise InputError("session_id must not be empty.")
    title = _string_arg(raw_args, "title", DEFAULT_TITLE, max_chars=MAX_TITLE_CHARS)
    user_anchor = _string_arg(raw_args, "user_anchor", "", max_chars=MAX_USER_ANCHOR_CHARS)
    body = _string_arg(
        raw_args, "body", "", max_chars=MAX_BODY_CHARS,
        required=action == "write_reply",
    )
    continuity_state = _string_arg(
        raw_args, "continuity_state", "", max_chars=MAX_CONTINUITY_CHARS,
    )
    footer = _string_arg(raw_args, "footer", DEFAULT_FOOTER, max_chars=MAX_FOOTER_CHARS)
    skin = raw_args.get("skin", DEFAULT_SKIN)
    if skin not in {"winter", "paper", "coast"}:
        raise InputError("skin must be one of: winter, paper, coast.")
    history_limit = raw_args.get("history_limit", DEFAULT_HISTORY_LIMIT)
    if isinstance(history_limit, bool) or not isinstance(history_limit, int):
        raise InputError("history_limit must be an integer from 1 to 10.")
    if not 1 <= history_limit <= MAX_HISTORY:
        raise InputError("history_limit must be from 1 to 10. The hard maximum is 10.")

    return {
        "action": action,
        "session_id": session_id,
        "title": title,
        "user_anchor": user_anchor,
        "body": body,
        "continuity_state": continuity_state,
        "footer": footer,
        "skin": skin,
        "history_limit": history_limit,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_records(session_id: str, history_limit: int) -> tuple[list[dict[str, str]], int]:
    with _HISTORY_LOCK:
        records = list(_HISTORY.get(session_id, ()))
        return [dict(record) for record in records[-history_limit:]], len(records)


def _append_and_read(session_id: str, record: dict[str, str], history_limit: int) -> tuple[list[dict[str, str]], int]:
    with _HISTORY_LOCK:
        history = _HISTORY.setdefault(session_id, deque(maxlen=MAX_HISTORY))
        history.append(dict(record))
        records = list(history)
        return [dict(item) for item in records[-history_limit:]], len(records)


def clear_memory() -> None:
    """Clear in-memory records. Intended for tests and process-local maintenance."""
    with _HISTORY_LOCK:
        _HISTORY.clear()


def _display(value: str) -> str:
    return value if value else "(empty)"


def _format_full_records(records: list[dict[str, str]]) -> str:
    if not records:
        return "(none)"
    blocks = []
    for index, record in enumerate(records, 1):
        blocks.append("\n".join([
            f"[{index}]",
            f"created_at: {_display(record.get('created_at', ''))}",
            f"title: {_display(record.get('title', ''))}",
            "user_anchor:", _display(record.get("user_anchor", "")),
            "body:", _display(record.get("body", "")),
            "continuity_state:", _display(record.get("continuity_state", "")),
        ]))
    return "\n\n".join(blocks)


def _format_continuity(records: list[dict[str, str]]) -> str:
    if not records:
        return "(none)"
    blocks = []
    for index, record in enumerate(records, 1):
        blocks.append("\n".join([
            f"[{index}]",
            f"created_at: {_display(record.get('created_at', ''))}",
            f"title: {_display(record.get('title', ''))}",
            "continuity_state:", _display(record.get("continuity_state", "")),
        ]))
    return "\n\n".join(blocks)


def format_context_text(*, action: str, session_id: str, history_limit: int,
                        records: list[dict[str, str]],
                        current: dict[str, str] | None = None) -> str:
    """Build the complete model-visible tool-result context."""
    recent_full = records[-3:]
    lines = [
        "O3_REPLY_CARD_CONTEXT_BEGIN",
        f"action: {action}",
        f"session_id: {session_id}",
        f"history_limit: {history_limit}",
        "",
    ]
    if current is not None:
        lines.extend([
            "CURRENT_REPLY:",
            f"created_at: {_display(current.get('created_at', ''))}",
            f"title: {_display(current.get('title', ''))}",
            "user_anchor:", _display(current.get("user_anchor", "")),
            "body:", _display(current.get("body", "")),
            "continuity_state:", _display(current.get("continuity_state", "")),
            f"footer: {_display(current.get('footer', ''))}",
            f"skin: {_display(current.get('skin', ''))}",
            "", "RECENT_FULL_BODIES_LAST_3:",
        ])
    else:
        lines.append("recent_full_bodies_last_3:")
    lines.extend([_format_full_records(recent_full), ""])
    lines.append("RECENT_CONTINUITY_LAST_10:" if current is not None else "recent_continuity_last_10:")
    lines.extend([_format_continuity(records), "", "O3_REPLY_CARD_CONTEXT_END"])
    return "\n".join(lines)


def _tool_error(message: str) -> dict[str, Any]:
    text = "\n".join([
        "O3_REPLY_CARD_ERROR", message,
        "No reply-card context was written for this failed call.",
    ])
    data = {
        "action": "error",
        "title": "o3 Reply Card Error",
        "body": message,
        "footer": "Nothing was stored.",
        "skin": DEFAULT_SKIN,
        "error": True,
    }
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": data,
        "_meta": data,
        "isError": True,
    }


def call_tool(raw_args: Any) -> dict[str, Any]:
    try:
        args = validate_arguments(raw_args)
    except InputError as exc:
        return _tool_error(str(exc))

    action = args["action"]
    session_id = args["session_id"]
    history_limit = args["history_limit"]
    if action == "read_context":
        records, record_count = _read_records(session_id, history_limit)
        context_text = format_context_text(
            action=action, session_id=session_id,
            history_limit=history_limit, records=records,
        )
        status_body = (
            f"已读取 session {session_id} 的 {len(records)} 条最近记录。"
            if records else f"session {session_id} 目前没有回复卡记录。"
        )
        data = {
            "action": action,
            "session_id": session_id,
            "title": "Context Read",
            "user_anchor": "",
            "body": status_body,
            "continuity_state": "",
            "footer": f"内存中共 {record_count} 条；本次返回 {len(records)} 条。",
            "skin": args["skin"],
            "record_count": record_count,
            "returned_count": len(records),
        }
        return {
            "content": [{"type": "text", "text": context_text}],
            "structuredContent": data,
            "_meta": data,
            "isError": False,
        }

    record = {
        "created_at": _utc_now(),
        "title": args["title"],
        "user_anchor": args["user_anchor"],
        "body": args["body"],
        "continuity_state": args["continuity_state"],
        "footer": args["footer"],
        "skin": args["skin"],
    }
    records, record_count = _append_and_read(session_id, record, history_limit)
    context_text = format_context_text(
        action=action, session_id=session_id,
        history_limit=history_limit, records=records, current=record,
    )
    data: dict[str, Any] = {
        "action": action,
        "session_id": session_id,
        **record,
        "record_count": record_count,
        "returned_count": len(records),
    }
    return {
        "content": [{"type": "text", "text": context_text}],
        "structuredContent": data,
        "_meta": data,
        "isError": False,
    }


def handle(req: Any) -> dict[str, Any] | None:
    """Return one JSON-RPC response, or None for a notification."""
    if not isinstance(req, dict):
        return {"jsonrpc": "2.0", "id": None,
                "error": {"code": -32600, "message": "invalid request"}}
    method, request_id = req.get("method"), req.get("id")
    if request_id is None:
        return None
    if method == "initialize":
        version = (req.get("params") or {}).get("protocolVersion") or PROTOCOL_FALLBACK
        return {
            "jsonrpc": "2.0", "id": request_id,
            "result": {
                "protocolVersion": version,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"listChanged": False},
                },
                "serverInfo": {"name": SERVICE_NAME, "version": SERVICE_VERSION},
                "instructions": (
                    "o3_reply_card preserves the model's actual natural-language reply. "
                    "Use read_context before a continuation when needed, then put the "
                    "complete user-facing reply in write_reply.body without turning it "
                    "into a summary, log, or report."
                ),
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [TOOL]}}
    if method == "tools/call":
        params = req.get("params") or {}
        if params.get("name") != TOOL["name"]:
            return {
                "jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32602, "message": f"unknown tool: {params.get('name')!r}"},
            }
        return {
            "jsonrpc": "2.0", "id": request_id,
            "result": call_tool(params.get("arguments") or {}),
        }
    if method == "resources/list":
        return {
            "jsonrpc": "2.0", "id": request_id,
            "result": {"resources": [{
                "uri": WIDGET_URI,
                "name": "o3-reply-card",
                "title": "o3 Reply Card",
                "description": "Displays one complete o3 reply in a readable card.",
                "mimeType": WIDGET_MIME,
            }]},
        }
    if method == "resources/read":
        uri = (req.get("params") or {}).get("uri")
        if uri != WIDGET_URI:
            return {
                "jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32002, "message": f"resource not found: {uri}"},
            }
        return {
            "jsonrpc": "2.0", "id": request_id,
            "result": {"contents": [{
                "uri": WIDGET_URI,
                "mimeType": WIDGET_MIME,
                "text": WIDGET_HTML,
                "_meta": {
                    "ui": {"prefersBorder": True},
                    "openai/widgetPrefersBorder": True,
                    "openai/widgetDescription": "A readable card showing the complete o3 reply, optional user anchor, compact continuity state, and footer.",
                },
            }]},
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    return {
        "jsonrpc": "2.0", "id": request_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("  · %s\n" % (fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type, accept, mcp-session-id, mcp-protocol-version")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Expose-Headers", "mcp-session-id")

    def _path(self) -> str:
        return self.path.split("?", 1)[0]

    def _json(self, code: int, obj: Any) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        if self._path() == "/health":
            self._json(200, {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION})
            return
        if self._path() != "/mcp":
            self._json(404, {"error": "not found"})
            return
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", "9")
        self.end_headers()
        try:
            self.wfile.write(b": ready\n\n")
            self.wfile.flush()
        except BrokenPipeError:
            pass

    def do_DELETE(self) -> None:
        if self._path() != "/mcp":
            self._json(404, {"error": "not found"})
            return
        self.send_response(200)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, {"error": "invalid content-length"})
            return
        if length < 0 or length > MAX_REQUEST_BYTES:
            self._json(413, {"error": "request body too large"})
            return
        raw_body = self.rfile.read(length)
        if self._path() != "/mcp":
            self._json(404, {"error": "not found"})
            return
        try:
            payload = json.loads(raw_body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "invalid json"})
            return
        batch = payload if isinstance(payload, list) else [payload]
        if not batch:
            self._json(400, {"jsonrpc": "2.0", "id": None,
                             "error": {"code": -32600, "message": "invalid request"}})
            return
        try:
            results = [response for response in (handle(item) for item in batch) if response is not None]
        except Exception as exc:  # pragma: no cover
            import traceback
            traceback.print_exc()
            request_id = batch[0].get("id") if isinstance(batch[0], dict) else None
            results = [{
                "jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"},
            }]
        if not results:
            self.send_response(202)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body_obj = results if isinstance(payload, list) else results[0]
        body = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
        wants_sse = "text/event-stream" in (self.headers.get("Accept") or "")
        self.send_response(200)
        self._cors()
        if any((result.get("result") or {}).get("serverInfo") for result in results):
            self.send_header("Mcp-Session-Id", uuid.uuid4().hex)
        if wants_sse:
            frame = b"event: message\ndata: " + body + b"\n\n"
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(frame)))
            self.end_headers()
            self.wfile.write(frame)
            return
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    print(f"o3 Reply Card MCP listening on http://{BIND_HOST}:{port}/mcp")
    print("Storage: in-memory only (cleared on restart)")
    ThreadingHTTPServer((BIND_HOST, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
