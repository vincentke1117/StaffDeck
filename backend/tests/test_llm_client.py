from app.llm.client import LLMClient


class _ForbiddenResponses:
    def create(self, **_kwargs):  # noqa: ANN003
        raise AssertionError("responses.create must not be called for OpenAI-compatible models")


class _FakeChatCompletions:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)
        message = type("Message", (), {"content": "ok"})()
        choice = type("Choice", (), {"message": message})()
        return type("Completion", (), {"choices": [choice]})()


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeChatCompletions()


class _FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = _ForbiddenResponses()
        self.chat = _FakeChat()


def test_generate_text_uses_chat_completions_only():
    client = object.__new__(LLMClient)
    client.client = _FakeOpenAIClient()
    client.model = "demo-model"
    client.temperature = 0.2
    client.max_output_tokens = 256

    output = client.generate_text("system prompt", {"hello": "world"})

    assert output == "ok"
    call = client.client.chat.completions.calls[0]
    assert call["model"] == "demo-model"
    assert call["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": '{"hello": "world"}'},
    ]
    assert call["max_tokens"] == 256


def test_generate_text_projects_conversation_context_messages():
    client = object.__new__(LLMClient)
    client.client = _FakeOpenAIClient()
    client.model = "demo-model"
    client.temperature = 0.2
    client.max_output_tokens = 256

    output = client.generate_text(
        "system prompt",
        {
            "user_message": "买两个",
            "conversation_context": {
                "messages": [
                    {"role": "user", "content": "我是 hx，我要买 A2"},
                    {"role": "assistant", "content": "请问买几个？"},
                    {"role": "user", "content": "买两个"},
                ],
                "metadata": {"total_messages": 3},
            },
        },
    )

    assert output == "ok"
    call = client.client.chat.completions.calls[0]
    assert call["messages"][:4] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "我是 hx，我要买 A2"},
        {"role": "assistant", "content": "请问买几个？"},
        {"role": "user", "content": "买两个"},
    ]
    assert '"messages":' not in call["messages"][-1]["content"]
    assert '"metadata": {"total_messages": 3}' in call["messages"][-1]["content"]


def test_generate_json_extracts_fenced_json(monkeypatch):
    client = object.__new__(LLMClient)

    def fake_generate_text(_system_prompt, _payload):
        return '```json\n{"decision": "continue_current_skill"}\n```'

    monkeypatch.setattr(client, "generate_text", fake_generate_text)

    assert client.generate_json("prompt", {}) == {"decision": "continue_current_skill"}


def test_generate_json_requests_json_object_mode():
    client = object.__new__(LLMClient)
    client.client = _FakeOpenAIClient()
    client.model = "demo-model"
    client.temperature = 0.2
    client.max_output_tokens = 256
    client.client.chat.completions.create = lambda **kwargs: (  # noqa: E731
        client.client.chat.completions.calls.append(kwargs)
        or type(
            "Completion",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {"message": type("Message", (), {"content": '{"ok": true}'})()},
                    )()
                ]
            },
        )()
    )

    assert client.generate_json("prompt", {}) == {"ok": True}
    assert client.client.chat.completions.calls[0]["response_format"] == {"type": "json_object"}


def test_generate_json_falls_back_when_json_object_mode_is_unsupported():
    client = object.__new__(LLMClient)
    client.client = _FakeOpenAIClient()
    client.model = "demo-model"
    client.temperature = 0.2
    client.max_output_tokens = 256

    def fake_create(**kwargs):  # noqa: ANN003
        client.client.chat.completions.calls.append(kwargs)
        if "response_format" in kwargs:
            raise ValueError("Unsupported parameter: response_format")
        return type(
            "Completion",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {"message": type("Message", (), {"content": '{"ok": true}'})()},
                    )()
                ]
            },
        )()

    client.client.chat.completions.create = fake_create

    assert client.generate_json("prompt", {}) == {"ok": True}
    assert "response_format" in client.client.chat.completions.calls[0]
    assert "response_format" not in client.client.chat.completions.calls[1]


def test_generate_json_retries_invalid_json(monkeypatch):
    client = object.__new__(LLMClient)
    calls = iter(["not json", '{"ok": true}'])

    def fake_generate_text(_system_prompt, _payload):
        return next(calls)

    monkeypatch.setattr(client, "generate_text", fake_generate_text)

    assert client.generate_json("prompt", {}) == {"ok": True}


def test_generate_json_retry_keeps_original_payload(monkeypatch):
    client = object.__new__(LLMClient)
    payloads = []
    calls = iter(["not json", '{"ok": true}'])

    def fake_generate_text(_system_prompt, payload):
        payloads.append(payload)
        return next(calls)

    monkeypatch.setattr(client, "generate_text", fake_generate_text)

    assert client.generate_json("prompt", {"query": "廊坊天气", "skill": {"slug": "weather-zh"}}) == {"ok": True}
    assert payloads[1]["query"] == "廊坊天气"
    assert payloads[1]["skill"]["slug"] == "weather-zh"
    assert payloads[1]["_json_repair"]["previous_output"] == "not json"


def test_generate_json_allows_multiple_repair_attempts(monkeypatch):
    client = object.__new__(LLMClient)
    payloads = []
    calls = iter(["not json", '{"reason": "用户称呼为"hm""}', '{"ok": true}'])

    def fake_generate_text(_system_prompt, payload):
        payloads.append(payload)
        return next(calls)

    monkeypatch.setattr(client, "generate_text", fake_generate_text)

    assert client.generate_json("prompt", {"query": "你好"}) == {"ok": True}
    assert payloads[1]["_json_repair"]["attempt"] == 1
    assert payloads[2]["_json_repair"]["attempt"] == 2
    assert "parser_error" in payloads[2]["_json_repair"]
