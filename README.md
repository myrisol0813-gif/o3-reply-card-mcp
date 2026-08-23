# o3 Reply Card MCP

A tiny self-hosted MCP Apps card for keeping o3 replies visible when ordinary ChatGPT assistant messages fail to persist.

When o3's ordinary reply bubble disappears, give it another piece of paper inside the chat.

当 o3 的普通回复气泡消失时，给它一张还留在聊天里的纸。

## What it does

- Provides one tool: `o3_reply_card`
- Supports two actions: `read_context` and `write_reply`
- Renders o3's main reply into a visible MCP Apps card
- Writes the same body into model-visible `content.text`
- Also includes the card fields in `structuredContent` and widget `_meta`
- Keeps a small in-memory rolling context by `session_id`
- Keeps full bodies for the latest 3 records and compact continuity state for up to 10
- Does not use Notion, databases, external APIs, private memory, or disk capture

## What it does not do

- It is not an official OpenAI fix.
- It does not guarantee that ChatGPT will preserve every card or every turn.
- It is not a reasoning or chain-of-thought tool.
- It does not store data after the server restarts.
- It does not provide authentication, rate limiting, TLS, or a hosted public endpoint.

## Quick start

Requires Python 3.10 or newer. There are no third-party Python dependencies.

```bash
git clone https://github.com/myrisol0813-gif/o3-reply-card-mcp.git
cd o3-reply-card-mcp
python3 server.py
```

MCP endpoint:

```text
http://127.0.0.1:8787/mcp
```

Health check:

```bash
curl -s http://127.0.0.1:8787/health
```

Expected response:

```json
{"status":"ok","service":"o3-reply-card-mcp","version":"0.1.0"}
```

For ChatGPT, expose the server through an HTTPS endpoint or temporary tunnel that you control, then add the HTTPS URL ending in `/mcp` in developer mode. Refresh the connection after changing the tool schema or widget. See the official [MCP server and UI quickstart](https://developers.openai.com/plugins/build/app-quickstart) and [MCP Apps UI guide](https://developers.openai.com/plugins/build/chatgpt-ui).

### Cloudflare Worker

The repository also includes a dependency-free Cloudflare Worker entry point:

```bash
node cloudflare/test_worker.mjs
npx wrangler deploy
```

The included `wrangler.jsonc` targets the maintainer's custom domain,
`o3-mcp.elementeracoast.com`. Change or remove that route before deploying
under a different Cloudflare account or domain. The Worker serves:

- `GET /health`
- `GET|POST|DELETE /mcp`
- the same endpoints under `/o3/health` and `/o3/mcp` for an isolated
  path mounted inside an existing Cloudflare Pages project

The Worker imports only its bundled reply-card widget. It has no environment
bindings, secrets, database access, external requests, Notion integration, or
Elementera Coast memory imports.

## Prompt

Paste this at the end of your o3 message:

> （请使用 `o3_reply_card`。如果需要上一轮上下文，先用 action=`read_context` 读取 session_id=`"o3-default"` 的最近 10 轮；然后用 action=`write_reply`，把你本轮真正想说的完整正文写进 `body`。`body` 是正文，不是摘要、日志或思考链。普通聊天气泡只写：请看 o3 回复卡。）

### 中文极简版

> （请使用 `o3_reply_card`。如果需要上一轮上下文，先用 action=`read_context` 读取 session_id=`"o3-default"` 的最近 10 轮；然后用 action=`write_reply`，把你本轮真正想说的完整正文写进 `body`。`body` 是正文，不是摘要、不是日志、不是任务记录、不是思考链。普通聊天气泡只写：请看 o3 回复卡。）

### 中文更强防办事员版

> （请调用 `o3_reply_card` 回复。不要调用 Notion、Python 或其他工具。不要把回答写成摘要、归档、任务记录或报告。请保持你平常的 o3 语气，把你真正想对我说的完整自然语言正文写进 `body`。若需要连续上下文，先用 action=`read_context` 读取 session_id=`"o3-default"` 最近 10 轮，再用 action=`write_reply` 写本轮卡片。普通聊天气泡最多只写一句：请看 o3 回复卡。）

### English version

> (Please use `o3_reply_card`. If you need previous context, first call action=`read_context` with session_id=`"o3-default"` and history_limit=`10`. Then call action=`write_reply` and put your full natural-language reply in `body`. `body` is the actual reply, not a summary, log, task record, or reasoning notes. The ordinary assistant message should only say: Please read the o3 reply card.)

Use a different stable `session_id` for each conversation that should have its own rolling context.

## Tool input

`o3_reply_card` accepts:

| Field | Default | Limit | Purpose |
| --- | --- | --- | --- |
| `action` | required | `read_context` or `write_reply` | Read recent context or write this turn's card |
| `session_id` | `o3-default` | 200 characters | In-memory conversation key |
| `title` | `o3 回复` | 200 characters | Card title |
| `user_anchor` | empty | 1,000 characters | Optional quote or short summary of the current user message |
| `body` | required for write | 8,000 characters | The complete natural-language reply |
| `continuity_state` | empty | 1,500 characters | Compact state for the next turn |
| `footer` | `本轮结束` | 300 characters | Card footer |
| `skin` | `winter` | `winter`, `paper`, or `coast` | Visual skin |
| `history_limit` | `10` | 1–10 | Maximum recent records returned |

The server never silently clips an over-limit field. It returns a clear tool error and stores nothing from that failed call.

## Context behavior

Every successful `write_reply` call stores one process-memory record:

```json
{
  "created_at": "...",
  "title": "...",
  "user_anchor": "...",
  "body": "...",
  "continuity_state": "...",
  "footer": "...",
  "skin": "..."
}
```

Each `session_id` has a ring buffer of at most 10 records. Returned records are ordered from older to newer within the selected window.

- The latest 3 selected records include full `body` text.
- Up to 10 selected records include `continuity_state`.
- `history_limit` limits both sections.
- Restarting the process clears every session.
- Separate server processes or replicas do not share memory.

The model-visible result is bounded by:

```text
O3_REPLY_CARD_CONTEXT_BEGIN
...
O3_REPLY_CARD_CONTEXT_END
```

It contains `CURRENT_REPLY`, `RECENT_FULL_BODIES_LAST_3`, and `RECENT_CONTINUITY_LAST_10` for `write_reply`. `read_context` returns the same rolling information without creating a record.

## Manual MCP checks

List tools:

```bash
curl -s -X POST http://127.0.0.1:8787/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Write a card:

```bash
curl -s -X POST http://127.0.0.1:8787/mcp \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":2,
    "method":"tools/call",
    "params":{
      "name":"o3_reply_card",
      "arguments":{
        "action":"write_reply",
        "session_id":"test",
        "title":"o3 回复测试",
        "user_anchor":"测试卡片是否显示",
        "body":"如果你能看到这段话，说明 o3 回复卡已经可以显示正文。",
        "continuity_state":"本轮测试卡片显示。",
        "footer":"本轮结束",
        "skin":"winter"
      }
    }
  }'
```

Read it back:

```bash
curl -s -X POST http://127.0.0.1:8787/mcp \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":3,
    "method":"tools/call",
    "params":{
      "name":"o3_reply_card",
      "arguments":{
        "action":"read_context",
        "session_id":"test",
        "history_limit":10
      }
    }
  }'
```

The first text item in each successful tool result must contain the complete `O3_REPLY_CARD_CONTEXT`, never only `rendered`.

## Test

Run the automated protocol, validation, ring-buffer, concurrency, widget, and HTTP tests:

```bash
python3 -m unittest discover -v
node cloudflare/test_worker.mjs
```

Then test in ChatGPT:

1. Connect your HTTPS `/mcp` endpoint.
2. Confirm `tools/list` exposes only `o3_reply_card`.
3. Call `write_reply` with the sample above and confirm the card shows `body`.
4. Inspect the tool result/source and confirm `content.text` contains the full `O3_REPLY_CARD_CONTEXT` rather than only `rendered`.
5. Call `read_context` for the same `session_id` and confirm the prior body and continuity state are returned.
6. Refresh the ChatGPT page and check whether the card remains visible.
7. Ask o3 to read the context and continue with another `write_reply` card.

The refresh and model-continuation checks must be performed in the actual ChatGPT host; local unit tests cannot guarantee host persistence behavior.

## Security and privacy

- This is self-hosted software, not an official OpenAI repair or hosted service.
- Do not put passwords, tokens, credentials, private keys, or sensitive personal data into a public MCP endpoint.
- If you expose the server through public HTTPS, add authentication, a protected reverse proxy, and rate limiting, or keep the tunnel open only for a short test.
- The server does not write replies to disk, but ChatGPT or another MCP host may retain tool inputs, tool results, and card content.
- Card bodies can enter later model context. Treat every card as model-readable and do not put secrets in it.
- In-memory sessions are keyed only by the caller-provided `session_id`; v0.1 has no user authentication or tenant isolation.
- Cloudflare isolate memory is best-effort process memory. A cold start, isolate
  eviction, deployment, or request reaching a different isolate can clear the
  rolling context even while the public endpoint remains healthy.

See [SECURITY.md](SECURITY.md) before exposing an endpoint beyond loopback.

## Origin

This project is based on and inspired by [sibylsea-hub/gpt-thinking-block-mcp](https://github.com/sibylsea-hub/gpt-thinking-block-mcp), whose original purpose is rendering a Thinking Block as an MCP Apps card. `o3-reply-card-mcp` reworks that minimal server and card into an o3 main-reply surface with model-visible rolling context.

The upstream MIT license and copyright notice are preserved. See [NOTICE.md](NOTICE.md).

## License

MIT. Based on / inspired by `gpt-thinking-block-mcp`.
