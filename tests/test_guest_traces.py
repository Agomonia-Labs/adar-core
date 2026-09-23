import unittest
from datetime import datetime, timedelta, timezone

from api.routes.guest_traces import build_public_trace_projection


class GuestTraceProjectionTests(unittest.TestCase):
    def test_projection_preserves_stages_and_removes_sensitive_payloads(self):
        started = datetime.now(timezone.utc)
        ended = started + timedelta(milliseconds=820)
        projection = build_public_trace_projection(
            {
                "trace_id": "trace-123",
                "domain": "geetabitan",
                "status": "success",
                "input_text_preview": "একলা চলো রে গানের অর্থ কী?",
                "started_at": started,
                "ended_at": ended,
                "metadata": {"secret": "must-not-leak"},
            },
            [
                {
                    "span_id": "agent-1",
                    "name": "agent_run",
                    "status": "success",
                    "duration_ms": 700,
                    "started_at": started,
                    "metadata": {"args": {"api_key": "secret"}},
                },
                {
                    "span_id": "tool-1",
                    "name": "tool:get_song_by_title",
                    "status": "success",
                    "duration_ms": 45,
                    "started_at": started + timedelta(milliseconds=100),
                    "metadata": {"result_preview": "private raw lyrics"},
                },
            ],
            [
                {
                    "event_id": "llm-1",
                    "model": "gemini-test",
                    "operation": "generate",
                    "input_tokens": 120,
                    "output_tokens": 80,
                    "latency_ms": 300,
                    "created_at": started + timedelta(milliseconds=200),
                    "system_prompt": "private system prompt",
                    "llm_response": "private raw response",
                    "error": None,
                }
            ],
        )

        self.assertTrue(projection["ready"])
        self.assertEqual(projection["trace"]["duration_ms"], 820)
        self.assertEqual(projection["steps"][0]["name"], "Question received")
        self.assertEqual(projection["steps"][-1]["name"], "Grounded answer delivered")
        self.assertIn("Get Song By Title", [step["name"] for step in projection["steps"]])
        serialized = str(projection)
        self.assertNotIn("must-not-leak", serialized)
        self.assertNotIn("private system prompt", serialized)
        self.assertNotIn("private raw lyrics", serialized)
        self.assertNotIn("private raw response", serialized)


if __name__ == "__main__":
    unittest.main()
