# -*- coding: utf-8 -*-
"""FastAPI エンドポイントのテスト。

外部依存（Gemini / OpenAI 互換 API / Nominatim / 解析モジュール）はすべてモック化する。
"""

import main


# ==============================================================================
# /api/health
# ==============================================================================

def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ==============================================================================
# /api/analyze
# ==============================================================================

def test_analyze_success(client, monkeypatch, fake_analysis):
    monkeypatch.setattr(main, "analyze_and_search", lambda *a, **k: fake_analysis)

    response = client.post("/api/analyze", json={"text": "スタバはどこ？"})

    assert response.status_code == 200
    body = response.json()
    assert body["input_text"] == fake_analysis["input_text"]
    assert body["method"] == "difflib"
    assert body["analysis"]["feature_keywords"] == ["スタバ"]


def test_analyze_empty_text_returns_400(client):
    response = client.post("/api/analyze", json={"text": "   "})
    assert response.status_code == 400


def test_analyze_internal_error_returns_500(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("解析エラー")

    monkeypatch.setattr(main, "analyze_and_search", boom)

    response = client.post("/api/analyze", json={"text": "テスト"})
    assert response.status_code == 500


# ==============================================================================
# /api/ask
# ==============================================================================

def test_ask_success(client, monkeypatch, fake_analysis, fake_nominatim):
    monkeypatch.setattr(main, "analyze_and_search", lambda *a, **k: fake_analysis)
    monkeypatch.setattr(main, "nominatim_search", lambda *a, **k: fake_nominatim)

    captured = {}

    def fake_answer_question(**kwargs):
        captured.update(kwargs)
        return {"answer": "右斜め前にスターバックスがあります。", "audio_path": None, "prompt": "p"}

    monkeypatch.setattr(main, "answer_question", fake_answer_question)

    response = client.post(
        "/api/ask",
        json={
            "question": "右斜め前のスタバはどこ？",
            "latitude": 35.6812,
            "longitude": 139.7671,
            "facing": "southeast",
            "generate_audio": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "右斜め前にスターバックスがあります。"
    assert body["found_target"]["name"] == "スターバックス 渋谷店"
    assert body["found_target"]["distance_meters"] is not None
    assert body["found_target"]["vector_name"] in {"北", "北東", "東", "南東", "南", "南西", "西", "北西"}

    # build_geolocate_result が found_target を埋めた状態で LLM に渡っていること
    assert captured["geolocate_result"]["status"] == "geocode_success"
    assert captured["geolocate_result"]["found_target"]["name"] == "スターバックス 渋谷店"


def test_ask_without_location_has_no_distance(client, monkeypatch, fake_analysis, fake_nominatim):
    monkeypatch.setattr(main, "analyze_and_search", lambda *a, **k: fake_analysis)
    monkeypatch.setattr(main, "nominatim_search", lambda *a, **k: fake_nominatim)
    monkeypatch.setattr(
        main,
        "answer_question",
        lambda **kwargs: {"answer": "回答", "audio_path": None, "prompt": "p"},
    )

    response = client.post("/api/ask", json={"question": "スタバはどこ？"})

    assert response.status_code == 200
    found = response.json()["found_target"]
    assert found["distance_meters"] is None
    assert found["vector_name"] is None


def test_ask_empty_question_returns_400(client):
    response = client.post("/api/ask", json={"question": "  "})
    assert response.status_code == 400


def test_ask_gemini_error_returns_500(client, monkeypatch, fake_analysis, fake_nominatim):
    monkeypatch.setattr(main, "analyze_and_search", lambda *a, **k: fake_analysis)
    monkeypatch.setattr(main, "nominatim_search", lambda *a, **k: fake_nominatim)

    def boom(**kwargs):
        raise RuntimeError("Gemini API キーが見つかりません。")

    monkeypatch.setattr(main, "answer_question", boom)

    response = client.post("/api/ask", json={"question": "スタバはどこ？"})
    assert response.status_code == 500


def test_ask_not_found_status(client, monkeypatch, fake_analysis):
    """Nominatim が何も返さない場合は status=not_found になる。"""
    monkeypatch.setattr(main, "analyze_and_search", lambda *a, **k: fake_analysis)
    monkeypatch.setattr(main, "nominatim_search", lambda *a, **k: None)

    captured = {}

    def fake_answer_question(**kwargs):
        captured.update(kwargs)
        return {"answer": "見つかりませんでした。", "audio_path": None, "prompt": "p"}

    monkeypatch.setattr(main, "answer_question", fake_answer_question)

    response = client.post("/api/ask", json={"question": "スタバはどこ？"})
    assert response.status_code == 200
    assert captured["geolocate_result"]["status"] == "not_found"
    assert response.json()["found_target"] is None


# ==============================================================================
# /api/ask-llm-only
# ==============================================================================

def test_ask_llm_only_missing_key_returns_500(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError(
            "LLM API キーが見つかりません。環境変数 GEMINI_API_KEY または OPENAI_API_KEY を設定してください。"
        )

    monkeypatch.setattr(main, "ask_llm", boom)

    response = client.post("/api/ask-llm-only", json={"prompt": "こんにちは"})
    assert response.status_code == 500


def test_ask_llm_only_empty_prompt_returns_400(client):
    response = client.post("/api/ask-llm-only", json={"prompt": "  "})
    assert response.status_code == 400


def test_ask_llm_only_success(client, monkeypatch):
    """共通ディスパッチャ（Gemini / OpenAI 互換の自動選択）をモックして正常系を検証する。"""
    captured = {}

    def fake_ask_llm(prompt, model=None):
        captured["prompt"] = prompt
        captured["model"] = model
        return "こんにちは！"

    monkeypatch.setattr(main, "ask_llm", fake_ask_llm)

    response = client.post("/api/ask-llm-only", json={"prompt": "こんにちは"})

    assert response.status_code == 200
    assert response.json() == {"prompt": "こんにちは", "answer": "こんにちは！"}
    assert captured == {"prompt": "こんにちは", "model": None}
