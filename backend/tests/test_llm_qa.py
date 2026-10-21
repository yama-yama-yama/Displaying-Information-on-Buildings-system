# -*- coding: utf-8 -*-
"""llm_qa のテスト。

Gemini / gTTS は外部通信するためモック化する。
"""

import sys
import types

import pytest

import llm_qa


# ==============================================================================
# build_prompt: geolocate_result のキー参照
# ==============================================================================

def _geolocate_result(status, **overrides):
    base = {
        "status": status,
        "found_target": {
            "name": "東京タワー",
            "latitude": 35.6586,
            "longitude": 139.7454,
            "osm_class": "man_made",
            "osm_type": "tower",
            "distance_meters": 820,
            "bearing": 18,
            "vector_name": "北",
            "display_name": "東京タワー, 港区, 東京都, 日本",
            "height": "333",
        },
        "candidates": [],
    }
    base.update(overrides)
    return base


def test_build_prompt_uses_found_target_on_geocode_success():
    """status=geocode_success でも found_target から建物情報を読むこと（バグ修正の回帰テスト）。"""
    prompt = llm_qa.build_prompt(_geolocate_result("geocode_success"), "あの塔は何？")

    assert "名称: 東京タワー" in prompt
    assert "35.6586" in prompt
    assert "約 820m" in prompt
    assert "北 (18°)" in prompt
    assert "情報が不足" not in prompt


def test_build_prompt_supports_overpass_success():
    prompt = llm_qa.build_prompt(_geolocate_result("overpass_success"), "あの塔は何？")

    assert "名称: 東京タワー" in prompt
    assert "高さ: 333" in prompt


def test_build_prompt_supports_legacy_result_key():
    """旧形式（result キー）でも後方互換で読めること。"""
    legacy = {
        "status": "geocode_success",
        "result": {"name": "旧形式ビル", "latitude": 1.0, "longitude": 2.0},
    }
    prompt = llm_qa.build_prompt(legacy, "これは？")

    assert "名称: 旧形式ビル" in prompt


def test_build_prompt_not_found():
    prompt = llm_qa.build_prompt({"status": "not_found"}, "どこ？")
    assert "情報が不足" in prompt


def test_build_prompt_includes_location_and_facing():
    prompt = llm_qa.build_prompt(
        {"status": "not_found"},
        "どこ？",
        current_location=(35.0, 139.0),
        facing="north",
    )
    assert "現在地: 緯度 35.0, 経度 139.0" in prompt
    assert "向いている方角: north" in prompt


def test_build_prompt_empty_result():
    prompt = llm_qa.build_prompt(None, "どこ？")
    assert "情報が不足" in prompt


# ==============================================================================
# load_gemini_api_key
# ==============================================================================

def test_load_gemini_api_key_prefers_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "  env-key  ")
    assert llm_qa.load_gemini_api_key() == "env-key"


def test_load_gemini_api_key_falls_back_to_file(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    key_file = tmp_path / "api_KEY.txt"
    key_file.write_text("file-key\n", encoding="utf-8")

    assert llm_qa.load_gemini_api_key(path=str(key_file)) == "file-key"


def test_load_gemini_api_key_returns_none(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert llm_qa.load_gemini_api_key(path=str(tmp_path / "missing.txt")) is None


# ==============================================================================
# ask_gemini / answer_question
# ==============================================================================

def test_ask_gemini_without_key_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(llm_qa, "DEFAULT_API_KEY_PATH", str(tmp_path / "missing.txt"))

    try:
        llm_qa.ask_gemini("hello")
    except RuntimeError as e:
        assert "API キー" in str(e)
    else:  # pragma: no cover
        raise AssertionError("RuntimeError が送出されるべき")


def test_ask_gemini_enables_google_search_grounding(monkeypatch):
    captured = {}

    class FakeResponse:
        text = "回答"

    class FakeModels:
        def generate_content(self, model, contents, config=None):
            captured.update(model=model, contents=contents, config=config)
            return FakeResponse()

    class FakeClient:
        def __init__(self, api_key):
            captured["api_key"] = api_key
            self.models = FakeModels()

    class FakeConfig:
        def __init__(self, tools=None):
            self.tools = tools

    class FakeTool:
        def __init__(self, google_search=None):
            self.google_search = google_search

    class FakeGoogleSearch:
        pass

    fake_google = types.ModuleType("google")
    fake_genai = types.ModuleType("google.genai")
    fake_types = types.ModuleType("google.genai.types")
    fake_genai.Client = FakeClient
    fake_genai.types = fake_types
    fake_google.genai = fake_genai
    fake_types.GenerateContentConfig = FakeConfig
    fake_types.Tool = FakeTool
    fake_types.GoogleSearch = FakeGoogleSearch

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)

    assert llm_qa.ask_gemini("質問", api_key="k", model="m") == "回答"
    assert captured["model"] == "m"
    assert captured["contents"] == "質問"
    assert isinstance(captured["config"], FakeConfig)
    assert len(captured["config"].tools) == 1
    assert isinstance(captured["config"].tools[0].google_search, FakeGoogleSearch)


def test_answer_question_builds_prompt_and_audio(monkeypatch):
    monkeypatch.setattr(
        llm_qa,
        "ask_llm",
        lambda prompt, api_key=None, model=None, web_search=None: "回答です",
    )
    saved = {}

    def fake_tts(text, output_path=None, lang="ja"):
        saved["text"] = text
        saved["output_path"] = output_path
        return output_path

    monkeypatch.setattr(llm_qa, "text_to_speech", fake_tts)

    result = llm_qa.answer_question(
        _geolocate_result("geocode_success"),
        "あの塔は何？",
        generate_audio=True,
        audio_path="out.mp3",
    )

    assert result["answer"] == "回答です"
    assert result["audio_path"] == "out.mp3"
    assert saved["text"] == "回答です"
    assert "東京タワー" in result["prompt"]


def test_answer_question_without_audio(monkeypatch):
    monkeypatch.setattr(
        llm_qa,
        "ask_llm",
        lambda prompt, api_key=None, model=None, web_search=None: "回答です",
    )

    def fail_tts(*args, **kwargs):  # pragma: no cover
        raise AssertionError("generate_audio=False では呼ばれない")

    monkeypatch.setattr(llm_qa, "text_to_speech", fail_tts)

    result = llm_qa.answer_question(_geolocate_result("geocode_success"), "質問")
    assert result["audio_path"] is None


# ==============================================================================
# OpenAI 互換 API
# ==============================================================================

class FakeHttpResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_load_openai_config_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm_qa.load_openai_config() is None


def test_load_openai_config_reads_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "  sk-test  ")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1/")
    monkeypatch.setenv("OPENAI_MODEL", "llama3")

    config = llm_qa.load_openai_config()

    assert config == {
        "api_key": "sk-test",
        "base_url": "http://localhost:11434/v1/",
        "model": "llama3",
    }


def test_load_openai_config_defaults(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    config = llm_qa.load_openai_config()
    assert config["base_url"] == llm_qa.DEFAULT_OPENAI_BASE_URL
    assert config["model"] == llm_qa.DEFAULT_OPENAI_MODEL


def test_load_openai_config_supports_api_base_alias(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_BASE", "http://example.test/v1")

    assert llm_qa.load_openai_config()["base_url"] == "http://example.test/v1"


def test_build_openai_endpoint():
    assert (
        llm_qa.build_openai_endpoint("http://localhost:11434/v1/")
        == "http://localhost:11434/v1/chat/completions"
    )
    # すでにフルパスの場合はそのまま使う
    assert (
        llm_qa.build_openai_endpoint("https://api.openai.com/v1/chat/completions")
        == "https://api.openai.com/v1/chat/completions"
    )
    # responses のフルパスからも chat を組み立てられる
    assert (
        llm_qa.build_openai_endpoint("https://api.openai.com/v1/responses")
        == "https://api.openai.com/v1/chat/completions"
    )


def test_build_openai_responses_endpoint():
    assert (
        llm_qa.build_openai_responses_endpoint("http://localhost:11434/v1/")
        == "http://localhost:11434/v1/responses"
    )
    assert (
        llm_qa.build_openai_responses_endpoint("https://api.openai.com/v1/responses")
        == "https://api.openai.com/v1/responses"
    )
    assert (
        llm_qa.build_openai_responses_endpoint(
            "https://api.openai.com/v1/chat/completions"
        )
        == "https://api.openai.com/v1/responses"
    )


def test_web_search_enabled_by_default(monkeypatch):
    monkeypatch.delenv("LLM_WEB_SEARCH", raising=False)
    assert llm_qa.web_search_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "off", "no", "FALSE"])
def test_web_search_can_be_disabled(monkeypatch, value):
    monkeypatch.setenv("LLM_WEB_SEARCH", value)
    assert llm_qa.web_search_enabled() is False


def _reset_responses_support(monkeypatch):
    monkeypatch.setattr(llm_qa, "_responses_supported", None)


def test_ask_openai_uses_web_search_tool_via_responses(monkeypatch):
    _reset_responses_support(monkeypatch)
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers)
        return FakeHttpResponse(
            200,
            {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "検索結果に基づく回答"}
                        ],
                    }
                ]
            },
        )

    monkeypatch.setattr(llm_qa.requests, "post", fake_post)

    answer = llm_qa.ask_openai(
        "質問です",
        api_key="sk-test",
        base_url="http://localhost:11434/v1",
        model="llama3",
    )

    assert answer == "検索結果に基づく回答"
    assert captured["url"] == "http://localhost:11434/v1/responses"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["json"] == {
        "model": "llama3",
        "input": "質問です",
        "tools": [{"type": "web_search"}],
    }


def test_ask_openai_sends_chat_completions_request(monkeypatch):
    _reset_responses_support(monkeypatch)
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return FakeHttpResponse(
            200, {"choices": [{"message": {"content": "  回答です  "}}]}
        )

    monkeypatch.setattr(llm_qa.requests, "post", fake_post)

    answer = llm_qa.ask_openai(
        "質問です",
        api_key="sk-test",
        base_url="http://localhost:11434/v1/",
        model="llama3",
        web_search=False,
    )

    assert answer == "回答です"
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["json"]["model"] == "llama3"
    assert captured["json"]["messages"] == [{"role": "user", "content": "質問です"}]
    assert "tools" not in captured["json"]


def test_ask_openai_falls_back_to_chat_when_responses_unsupported(monkeypatch):
    _reset_responses_support(monkeypatch)
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json})
        if url.endswith("/responses"):
            return FakeHttpResponse(404, {}, "not found")
        return FakeHttpResponse(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(llm_qa.requests, "post", fake_post)

    assert (
        llm_qa.ask_openai(
            "hello", api_key="sk-test", base_url="http://x/v1", model="m"
        )
        == "ok"
    )

    assert [c["url"] for c in calls] == [
        "http://x/v1/responses",
        "http://x/v1/chat/completions",
    ]
    # chat 側でも web_search ツールを付けて試す
    assert calls[1]["json"]["tools"] == [{"type": "web_search"}]


def test_ask_openai_chat_retries_without_tools(monkeypatch):
    _reset_responses_support(monkeypatch)
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json})
        if url.endswith("/responses"):
            return FakeHttpResponse(404, {}, "not found")
        if "tools" in (json or {}):
            return FakeHttpResponse(400, {}, "tools unsupported")
        return FakeHttpResponse(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(llm_qa.requests, "post", fake_post)

    assert (
        llm_qa.ask_openai(
            "hello", api_key="sk-test", base_url="http://x/v1", model="m"
        )
        == "ok"
    )

    assert len(calls) == 3
    assert calls[-1]["url"] == "http://x/v1/chat/completions"
    assert "tools" not in calls[-1]["json"]


def test_ask_openai_uses_config(monkeypatch):
    _reset_responses_support(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-config")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("OPENAI_MODEL", "model-x")

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers)
        return FakeHttpResponse(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(llm_qa.requests, "post", fake_post)

    assert llm_qa.ask_openai("hello", web_search=False) == "ok"
    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["json"]["model"] == "model-x"
    assert captured["headers"]["Authorization"] == "Bearer sk-config"


def test_ask_openai_without_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError):
        llm_qa.ask_openai("hello")


def test_ask_openai_http_error_raises(monkeypatch):
    _reset_responses_support(monkeypatch)
    monkeypatch.setattr(
        llm_qa.requests,
        "post",
        lambda *a, **k: FakeHttpResponse(401, {}, "unauthorized"),
    )

    with pytest.raises(RuntimeError, match="401"):
        llm_qa.ask_openai("hello", api_key="sk-test", web_search=False)


def test_ask_openai_malformed_response_raises(monkeypatch):
    _reset_responses_support(monkeypatch)
    monkeypatch.setattr(
        llm_qa.requests,
        "post",
        lambda *a, **k: FakeHttpResponse(200, {"choices": []}),
    )

    with pytest.raises(RuntimeError):
        llm_qa.ask_openai("hello", api_key="sk-test", web_search=False)


# ==============================================================================
# detect_provider / ask_llm
# ==============================================================================

def test_detect_provider_prefers_gemini_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    assert llm_qa.detect_provider(path=str(tmp_path / "missing.txt")) == "gemini"


def test_detect_provider_uses_openai_without_gemini(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    assert llm_qa.detect_provider(path=str(tmp_path / "missing.txt")) == "openai"


def test_detect_provider_uses_api_key_file_as_gemini(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    key_file = tmp_path / "api_KEY.txt"
    key_file.write_text("file-key", encoding="utf-8")

    assert llm_qa.detect_provider(path=str(key_file)) == "gemini"


def test_detect_provider_returns_none(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert llm_qa.detect_provider(path=str(tmp_path / "missing.txt")) is None


def test_ask_llm_dispatches_to_gemini(monkeypatch):
    monkeypatch.setattr(llm_qa, "detect_provider", lambda *a, **k: "gemini")
    captured = {}

    def fake_ask_gemini(prompt, api_key=None, model=None, web_search=None):
        captured.update(prompt=prompt, model=model, web_search=web_search)
        return f"gemini:{model}"

    monkeypatch.setattr(llm_qa, "ask_gemini", fake_ask_gemini)

    assert llm_qa.ask_llm("hello", model="m", web_search=True) == "gemini:m"
    assert captured == {"prompt": "hello", "model": "m", "web_search": True}


def test_ask_llm_dispatches_to_openai(monkeypatch):
    monkeypatch.setattr(llm_qa, "detect_provider", lambda *a, **k: "openai")
    monkeypatch.setattr(
        llm_qa,
        "load_openai_config",
        lambda: {"api_key": "k", "base_url": "http://x/v1", "model": "llama"},
    )
    captured = {}

    def fake_ask_openai(prompt, api_key=None, base_url=None, model=None, web_search=None):
        captured.update(
            prompt=prompt,
            api_key=api_key,
            base_url=base_url,
            model=model,
            web_search=web_search,
        )
        return "openai-answer"

    monkeypatch.setattr(llm_qa, "ask_openai", fake_ask_openai)

    assert llm_qa.ask_llm("hello") == "openai-answer"
    assert captured == {
        "prompt": "hello",
        "api_key": "k",
        "base_url": "http://x/v1",
        "model": "llama",
        "web_search": None,
    }


def test_ask_llm_openai_model_override(monkeypatch):
    monkeypatch.setattr(llm_qa, "detect_provider", lambda *a, **k: "openai")
    monkeypatch.setattr(
        llm_qa,
        "load_openai_config",
        lambda: {"api_key": "k", "base_url": "http://x/v1", "model": "llama"},
    )
    captured = {}
    monkeypatch.setattr(
        llm_qa,
        "ask_openai",
        lambda prompt, api_key=None, base_url=None, model=None, web_search=None: (
            captured.update(model=model) or "ok"
        ),
    )

    llm_qa.ask_llm("hello", model="override")
    assert captured["model"] == "override"


def test_ask_llm_without_provider_raises(monkeypatch):
    monkeypatch.setattr(llm_qa, "detect_provider", lambda *a, **k: None)

    with pytest.raises(RuntimeError, match="API キー"):
        llm_qa.ask_llm("hello")


def test_ask_llm_explicit_api_key_uses_gemini(monkeypatch):
    def fail_detect(*args, **kwargs):  # pragma: no cover
        raise AssertionError("api_key 明示時は detect_provider を呼ばない")

    monkeypatch.setattr(llm_qa, "detect_provider", fail_detect)
    monkeypatch.setattr(
        llm_qa,
        "ask_gemini",
        lambda prompt, api_key=None, model=None, web_search=None: f"gemini:{api_key}",
    )

    assert llm_qa.ask_llm("hello", api_key="explicit") == "gemini:explicit"
