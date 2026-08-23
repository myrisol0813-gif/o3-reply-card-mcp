# Contributing

Small, reviewable pull requests are welcome.

1. Keep the server dependency-free and self-hosted.
2. Keep reply storage in memory only for v0.1.
3. Preserve the full reply in both model-visible `content.text` and the card
   payload; never replace it with a generic status such as `rendered`.
4. Never silently truncate `body`, `user_anchor`, or `continuity_state`.
5. If the card changes materially, bump `WIDGET_URI` to avoid stale host caches.
6. Run `python3 -m unittest discover -v` before opening a pull request.

Do not include conversation captures, credentials, or private endpoint URLs in
commits, issues, or pull requests.
