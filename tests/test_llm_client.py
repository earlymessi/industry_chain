"""llm_client 测试。"""

from unittest.mock import MagicMock, patch

import pytest

from metaforge.orchestrator.llm.client import LlmClient, LlmClientError


def test_invoke_json_parses_message_content():
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "choices": [{"message": {"content": '{"solvers":["spt"]}'}}]
    }
    client = LlmClient(api_key="test-key", model="glm-4.5-air", timeout_sec=5)
    with patch("metaforge.orchestrator.llm.client.requests.post", return_value=fake_resp) as post:
        out = client.invoke_json(system="sys", user="user", temperature=0.1)
    assert out == {"solvers": ["spt"]}
    assert post.call_args.kwargs["json"]["temperature"] == 0.1


def test_invoke_json_raises_on_http_error():
    fake_resp = MagicMock()
    fake_resp.status_code = 401
    fake_resp.text = "unauthorized"
    client = LlmClient(api_key="k", model="glm-4.5-air", timeout_sec=5)
    with patch("metaforge.orchestrator.llm.client.requests.post", return_value=fake_resp):
        with pytest.raises(LlmClientError):
            client.invoke_json(system="s", user="u")


def test_operations_can_request_short_non_thinking_answer_without_changing_defaults():
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"choices": [{"message": {"content": '{"summary":"ok"}'}}]}
    client = LlmClient(api_key="fixture", model="deepseek-v4-pro", timeout_sec=5)
    with patch("metaforge.orchestrator.llm.client.requests.post", return_value=fake_resp) as post:
        client.invoke_json(system="s", user="u")
        default = post.call_args.kwargs["json"]
        assert "thinking" not in default and "max_tokens" not in default
        client.invoke_json(system="s", user="u", thinking=False, max_tokens=1400)
        options = post.call_args.kwargs["json"]
        assert options["thinking"] == {"type": "disabled"}
        assert options["max_tokens"] == 1400
