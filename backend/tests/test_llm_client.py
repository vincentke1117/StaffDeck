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


def test_generate_json_retries_invalid_json(monkeypatch):
    client = object.__new__(LLMClient)
    calls = iter(["not json", '{"ok": true}'])

    def fake_generate_text(_system_prompt, _payload):
        return next(calls)

    monkeypatch.setattr(client, "generate_text", fake_generate_text)

    assert client.generate_json("prompt", {}) == {"ok": True}
