# Security

This repository contains self-hosted reference software. It does not operate a
shared MCP service and is provided as-is under the MIT license.

## v0.1 security boundary

- The server binds to `127.0.0.1` by default.
- Reply records stay in process memory and are cleared on restart.
- The server does not write replies to disk or call external services.
- The server has no authentication, authorization, tenant isolation, TLS, rate
  limiting, or hardened production deployment configuration.
- Anyone who can reach the endpoint can choose a `session_id`, read its recent
  context, and write to it.

Do not expose the bundled server directly to the public internet. Put a public
HTTPS endpoint behind authentication, a protected reverse proxy, request-size
controls, and rate limiting, or use a temporary tunnel only while testing.

## Sensitive content

Do not place passwords, tokens, credentials, private keys, or other secrets in
tool inputs or reply cards. Even though this server does not persist content,
the MCP host may retain tool calls and tool results. The reply body and rolling
context are deliberately model-visible.

## Reporting

Security observations are welcome as GitHub issues, but never include private
conversation text, credentials, tunnel tokens, or non-public endpoint URLs.
