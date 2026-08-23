import http.client
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer

import server


def rpc(method, request_id=1, params=None):
    request = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        request["params"] = params
    return server.handle(request)


def tool_call(arguments, request_id=1, name="o3_reply_card"):
    return rpc(
        "tools/call",
        request_id,
        {"name": name, "arguments": arguments},
    )


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        server.clear_memory()

    def test_initialize_uses_requested_identity_and_version(self):
        response = rpc(
            "initialize",
            params={"protocolVersion": "2025-06-18"},
        )
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["serverInfo"], {
            "name": "o3-reply-card-mcp",
            "version": "0.1.0",
        })
        self.assertIn("actual natural-language reply", result["instructions"])

    def test_tools_list_contains_exactly_one_reply_tool(self):
        response = rpc("tools/list")
        tools = response["result"]["tools"]
        self.assertEqual(len(tools), 1)
        tool = tools[0]
        self.assertEqual(tool["name"], "o3_reply_card")
        self.assertEqual(tool["title"], "o3 回复用")
        self.assertIn("final natural-language reply itself", tool["description"])
        self.assertIn("Do not shorten, formalize, classify", tool["description"])
        self.assertEqual(tool["inputSchema"]["required"], ["action"])
        self.assertEqual(
            tool["inputSchema"]["properties"]["action"]["enum"],
            ["read_context", "write_reply"],
        )
        self.assertEqual(
            tool["inputSchema"]["properties"]["skin"]["enum"],
            ["winter", "paper", "coast"],
        )
        self.assertEqual(
            tool["inputSchema"]["properties"]["history_limit"]["maximum"],
            10,
        )
        self.assertNotIn("thinking", tool["inputSchema"]["properties"])
        self.assertNotIn("style", tool["inputSchema"]["properties"])
        self.assertNotIn("effort", tool["inputSchema"]["properties"])

    def test_write_reply_puts_same_body_in_text_structured_content_and_meta(self):
        body = "如果你能看到这段话，说明 o3 回复卡已经可以显示正文。"
        response = tool_call({
            "action": "write_reply",
            "session_id": "test",
            "title": "o3 回复测试",
            "user_anchor": "测试卡片是否显示",
            "body": body,
            "continuity_state": "本轮测试卡片显示。",
            "footer": "本轮结束",
            "skin": "winter",
        })
        result = response["result"]
        text = result["content"][0]["text"]
        self.assertFalse(result["isError"])
        self.assertNotEqual(text, "rendered")
        self.assertTrue(text.startswith("O3_REPLY_CARD_CONTEXT_BEGIN"))
        self.assertIn("action: write_reply", text)
        self.assertIn("CURRENT_REPLY:", text)
        self.assertIn(body, text)
        self.assertIn("RECENT_FULL_BODIES_LAST_3:", text)
        self.assertIn("RECENT_CONTINUITY_LAST_10:", text)
        self.assertTrue(text.endswith("O3_REPLY_CARD_CONTEXT_END"))
        self.assertEqual(result["structuredContent"]["body"], body)
        self.assertEqual(result["_meta"]["body"], body)
        self.assertEqual(result["_meta"]["continuity_state"], "本轮测试卡片显示。")
        self.assertEqual(result["_meta"]["record_count"], 1)

    def test_write_reply_applies_all_defaults(self):
        result = tool_call({
            "action": "write_reply",
            "body": "default check",
        })["result"]
        meta = result["_meta"]
        self.assertEqual(meta["session_id"], "o3-default")
        self.assertEqual(meta["title"], "o3 回复")
        self.assertEqual(meta["footer"], "本轮结束")
        self.assertEqual(meta["skin"], "winter")

    def test_read_context_returns_written_body_and_continuity(self):
        tool_call({
            "action": "write_reply",
            "session_id": "test",
            "body": "上一轮完整正文",
            "continuity_state": "上一轮连续状态",
        })
        result = tool_call({
            "action": "read_context",
            "session_id": "test",
            "history_limit": 10,
        }, request_id=2)["result"]
        text = result["content"][0]["text"]
        self.assertFalse(result["isError"])
        self.assertIn("action: read_context", text)
        self.assertIn("recent_full_bodies_last_3:", text)
        self.assertIn("上一轮完整正文", text)
        self.assertIn("recent_continuity_last_10:", text)
        self.assertIn("上一轮连续状态", text)
        self.assertEqual(result["_meta"]["record_count"], 1)
        self.assertEqual(result["_meta"]["returned_count"], 1)

    def test_reading_unknown_session_is_empty_and_does_not_create_it(self):
        first = tool_call({"action": "read_context", "session_id": "missing"})["result"]
        second = tool_call({"action": "read_context", "session_id": "missing"})["result"]
        self.assertIn("(none)", first["content"][0]["text"])
        self.assertEqual(first["_meta"]["record_count"], 0)
        self.assertEqual(second["_meta"]["record_count"], 0)

    def test_missing_body_returns_clear_error_and_stores_nothing(self):
        failed = tool_call({
            "action": "write_reply",
            "session_id": "test",
        })["result"]
        self.assertTrue(failed["isError"])
        self.assertIn("body is required", failed["content"][0]["text"])
        read = tool_call({"action": "read_context", "session_id": "test"})["result"]
        self.assertEqual(read["_meta"]["record_count"], 0)

    def test_body_limit_is_hard_and_never_silently_truncates(self):
        accepted_body = "x" * server.MAX_BODY_CHARS
        accepted = tool_call({
            "action": "write_reply",
            "session_id": "limit",
            "body": accepted_body,
        })["result"]
        self.assertFalse(accepted["isError"])
        self.assertEqual(accepted["_meta"]["body"], accepted_body)

        rejected = tool_call({
            "action": "write_reply",
            "session_id": "limit",
            "body": "y" * (server.MAX_BODY_CHARS + 1),
        })["result"]
        self.assertTrue(rejected["isError"])
        self.assertIn("The server did not truncate or store it", rejected["content"][0]["text"])
        read = tool_call({"action": "read_context", "session_id": "limit"})["result"]
        self.assertEqual(read["_meta"]["record_count"], 1)

    def test_other_text_limits_and_history_limit_are_enforced(self):
        cases = [
            ("user_anchor", server.MAX_USER_ANCHOR_CHARS + 1),
            ("continuity_state", server.MAX_CONTINUITY_CHARS + 1),
            ("title", server.MAX_TITLE_CHARS + 1),
            ("footer", server.MAX_FOOTER_CHARS + 1),
        ]
        for field, length in cases:
            with self.subTest(field=field):
                args = {"action": "write_reply", "body": "ok", field: "z" * length}
                self.assertTrue(tool_call(args)["result"]["isError"])
        for value in (0, 11, 1.5, True):
            with self.subTest(history_limit=value):
                result = tool_call({
                    "action": "read_context",
                    "history_limit": value,
                })["result"]
                self.assertTrue(result["isError"])

        legacy = tool_call({
            "action": "write_reply",
            "body": "ok",
            "thinking": "legacy field",
        })["result"]
        self.assertTrue(legacy["isError"])
        self.assertIn("Unknown tool argument", legacy["content"][0]["text"])

    def test_ring_buffer_keeps_last_ten_and_only_last_three_full_bodies(self):
        for index in range(12):
            tool_call({
                "action": "write_reply",
                "session_id": "rolling",
                "title": f"turn-{index}",
                "body": f"full-body-{index}",
                "continuity_state": f"state-{index}",
            }, request_id=index + 1)

        result = tool_call({
            "action": "read_context",
            "session_id": "rolling",
            "history_limit": 10,
        })["result"]
        text = result["content"][0]["text"]
        full_section, continuity_section = text.split("recent_continuity_last_10:", 1)
        self.assertEqual(result["_meta"]["record_count"], 10)
        self.assertEqual(result["_meta"]["returned_count"], 10)
        self.assertNotIn("full-body-8\n", full_section)
        for index in (9, 10, 11):
            self.assertIn(f"full-body-{index}", full_section)
        self.assertNotIn("state-1\n", continuity_section)
        for index in range(2, 12):
            self.assertIn(f"state-{index}", continuity_section)

    def test_history_limit_restricts_both_context_sections(self):
        for index in range(4):
            tool_call({
                "action": "write_reply",
                "session_id": "short",
                "body": f"body-{index}",
                "continuity_state": f"continuity-{index}",
            })
        result = tool_call({
            "action": "read_context",
            "session_id": "short",
            "history_limit": 2,
        })["result"]
        text = result["content"][0]["text"]
        self.assertNotIn("body-1", text)
        self.assertIn("body-2", text)
        self.assertIn("body-3", text)
        self.assertNotIn("continuity-1", text)
        self.assertIn("continuity-2", text)
        self.assertIn("continuity-3", text)
        self.assertEqual(result["_meta"]["returned_count"], 2)

    def test_sessions_are_isolated(self):
        tool_call({"action": "write_reply", "session_id": "a", "body": "alpha"})
        tool_call({"action": "write_reply", "session_id": "b", "body": "beta"})
        a_text = tool_call({"action": "read_context", "session_id": "a"})["result"]["content"][0]["text"]
        b_text = tool_call({"action": "read_context", "session_id": "b"})["result"]["content"][0]["text"]
        self.assertIn("alpha", a_text)
        self.assertNotIn("beta", a_text)
        self.assertIn("beta", b_text)
        self.assertNotIn("alpha", b_text)

    def test_concurrent_writes_do_not_corrupt_the_ring_buffer(self):
        def write(index):
            return tool_call({
                "action": "write_reply",
                "session_id": "concurrent",
                "body": f"parallel-{index}",
                "continuity_state": f"p-{index}",
            })["result"]["isError"]

        with ThreadPoolExecutor(max_workers=8) as pool:
            errors = list(pool.map(write, range(40)))
        self.assertFalse(any(errors))
        result = tool_call({
            "action": "read_context",
            "session_id": "concurrent",
        })["result"]
        self.assertEqual(result["_meta"]["record_count"], 10)

    def test_widget_resource_is_cache_versioned_and_reply_focused(self):
        response = rpc(
            "resources/read",
            params={"uri": server.WIDGET_URI},
        )
        content = response["result"]["contents"][0]
        html = content["text"]
        self.assertEqual(server.WIDGET_URI, "ui://widget/o3-reply-card-v1.html")
        self.assertEqual(content["mimeType"], "text/html;profile=mcp-app")
        self.assertIn("o3 回复用", html)
        self.assertIn('id="body-copy"', html)
        self.assertIn('id="continuity"', html)
        self.assertIn('data-skin="paper"', html)
        self.assertIn('data-skin="coast"', html)
        self.assertIn("bodyCopy.textContent", html)
        self.assertNotIn("innerHTML", html)
        self.assertIn("ui/notifications/tool-result", html)
        self.assertIn("openai:set_globals", html)
        self.assertIn("toolResponseMetadata", html)
        self.assertIn("notifyIntrinsicHeight", html)
        self.assertIn("ResizeObserver", html)
        self.assertIn("api.maxHeight", html)
        self.assertNotIn("render_thinking_block", html)
        self.assertNotIn("deep_think", html)
        self.assertNotIn("relational", html)
        self.assertNotIn("EFFORT", html)

    def test_resources_list_and_unknown_resource(self):
        listed = rpc("resources/list")["result"]["resources"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["uri"], server.WIDGET_URI)
        missing = rpc("resources/read", params={"uri": "ui://widget/missing.html"})
        self.assertEqual(missing["error"]["code"], -32002)

    def test_ping_unknown_tool_and_notification(self):
        self.assertEqual(rpc("ping")["result"], {})
        unknown = tool_call({"action": "read_context"}, name="something_else")
        self.assertEqual(unknown["error"]["code"], -32602)
        self.assertIsNone(server.handle({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }))


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        server.clear_memory()

    def request(self, method, path, payload=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(headers or {})
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        data = response.read()
        response_headers = dict(response.getheaders())
        connection.close()
        return response.status, response_headers, data

    def test_health_is_exact(self):
        status, _, body = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {
            "status": "ok",
            "service": "o3-reply-card-mcp",
            "version": "0.1.0",
        })

    def test_http_initialize_sets_session_header(self):
        status, headers, body = self.request("POST", "/mcp", {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        })
        self.assertEqual(status, 200)
        self.assertIn("Mcp-Session-Id", headers)
        self.assertEqual(json.loads(body)["result"]["serverInfo"]["name"], "o3-reply-card-mcp")

    def test_http_write_then_read_keeps_model_visible_body(self):
        write_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "o3_reply_card",
                "arguments": {
                    "action": "write_reply",
                    "session_id": "http-test",
                    "body": "body through HTTP",
                    "continuity_state": "continue through HTTP",
                },
            },
        }
        status, _, body = self.request("POST", "/mcp", write_payload)
        self.assertEqual(status, 200)
        result = json.loads(body)["result"]
        self.assertIn("body through HTTP", result["content"][0]["text"])
        self.assertEqual(result["_meta"]["body"], "body through HTTP")

        read_payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "o3_reply_card",
                "arguments": {"action": "read_context", "session_id": "http-test"},
            },
        }
        _, _, read_body = self.request("POST", "/mcp", read_payload)
        read_text = json.loads(read_body)["result"]["content"][0]["text"]
        self.assertIn("body through HTTP", read_text)
        self.assertIn("continue through HTTP", read_text)

    def test_http_sse_and_unknown_path(self):
        payload = {"jsonrpc": "2.0", "id": 3, "method": "ping"}
        status, headers, body = self.request(
            "POST", "/mcp", payload,
            headers={"Accept": "application/json, text/event-stream"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/event-stream")
        self.assertTrue(body.startswith(b"event: message\ndata: "))
        missing_status, _, _ = self.request("POST", "/not-mcp", payload)
        self.assertEqual(missing_status, 404)


if __name__ == "__main__":
    unittest.main()
