# -*- coding: utf-8 -*-
"""FastAPI エンドポイントのテスト。

外部依存（Gemini / OpenAI 互換 API / Nominatim / 解析モジュール）はすべてモック化する。
"""

import pytest
from fastapi import HTTPException

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


def test_ask_supports_blob_audio_url(client, monkeypatch, fake_analysis, fake_nominatim):
    """/api/ask は private Blob の音声をバックエンド経由の URL で返す。"""
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_test")
    monkeypatch.setattr(main, "analyze_and_search", lambda *a, **k: fake_analysis)
    monkeypatch.setattr(main, "nominatim_search", lambda *a, **k: fake_nominatim)

    blob_url = "https://store.private.blob.vercel-storage.com/audio/answer_x.mp3"
    monkeypatch.setattr(
        main,
        "answer_question",
        lambda **kwargs: {"answer": "回答", "audio_path": blob_url, "prompt": "p"},
    )

    response = client.post("/api/ask", json={"question": "スタバはどこ？"})

    assert response.status_code == 200
    assert response.json()["audio_path"] == "/api/audio/answer_x.mp3"


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


# ==============================================================================
# /api/tts
# ==============================================================================

def test_tts_returns_backend_proxy_url_for_private_blob(client, monkeypatch):
    """private Blob に保存した音声は /api/audio 経由の URL を返す。"""
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_test")
    blob_url = "https://store.private.blob.vercel-storage.com/audio/answer_x.mp3"
    monkeypatch.setattr(main, "text_to_speech", lambda *a, **k: blob_url)

    response = client.post("/api/tts", json={"text": "こんにちは", "lang": "ja"})

    assert response.status_code == 200
    assert response.json()["audio_path"] == "/api/audio/answer_x.mp3"


def test_tts_success(client, monkeypatch, tmp_path):
    audio_file = tmp_path / "answer_test.mp3"
    audio_file.write_bytes(b"ID3fake")
    captured = {}

    def fake_tts(text, output_path=None, lang="ja"):
        captured.update(text=text, lang=lang, output_path=output_path)
        return str(audio_file)

    monkeypatch.setattr(main, "text_to_speech", fake_tts)

    response = client.post("/api/tts", json={"text": "  こんにちは  ", "lang": "ja"})

    assert response.status_code == 200
    assert response.json() == {
        "text": "こんにちは",
        "lang": "ja",
        "audio_path": "/api/audio/answer_test.mp3",
    }
    assert captured == {"text": "こんにちは", "lang": "ja", "output_path": None}


def test_tts_defaults_to_japanese(client, monkeypatch, tmp_path):
    audio_file = tmp_path / "answer_default.mp3"
    audio_file.write_bytes(b"ID3fake")
    captured = {}

    def fake_tts(text, output_path=None, lang="ja"):
        captured.update(text=text, lang=lang)
        return str(audio_file)

    monkeypatch.setattr(main, "text_to_speech", fake_tts)

    response = client.post("/api/tts", json={"text": "hello"})

    assert response.status_code == 200
    assert response.json()["lang"] == "ja"
    assert captured["lang"] == "ja"


def test_tts_empty_text_returns_400(client):
    response = client.post("/api/tts", json={"text": "   "})
    assert response.status_code == 400


def test_tts_too_long_text_returns_400(client):
    response = client.post(
        "/api/tts", json={"text": "あ" * (main.MAX_TTS_TEXT_CHARS + 1)}
    )
    assert response.status_code == 400


def test_tts_synthesis_error_returns_502(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("gTTS に接続できません")

    monkeypatch.setattr(main, "text_to_speech", boom)

    response = client.post("/api/tts", json={"text": "こんにちは"})
    assert response.status_code == 502


def test_tts_missing_output_file_returns_500(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        main, "text_to_speech", lambda *a, **k: str(tmp_path / "missing.mp3")
    )

    response = client.post("/api/tts", json={"text": "こんにちは"})
    assert response.status_code == 500


# ==============================================================================
# /api/audio/{filename}
# ==============================================================================

def test_get_audio_serves_mp3(client, monkeypatch, tmp_path):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.setattr(main, "AUDIO_DIR", str(tmp_path))
    (tmp_path / "answer_abc.mp3").write_bytes(b"ID3fakecontent")

    response = client.get("/api/audio/answer_abc.mp3")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.content == b"ID3fakecontent"


def test_get_audio_missing_returns_404(client, monkeypatch, tmp_path):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.setattr(main, "AUDIO_DIR", str(tmp_path))

    response = client.get("/api/audio/not_found.mp3")

    assert response.status_code == 404


def test_get_audio_rejects_path_traversal(monkeypatch, tmp_path):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.setattr(main, "AUDIO_DIR", str(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        main.get_audio("..\\secret.mp3")

    assert exc_info.value.status_code == 400


def test_get_audio_streams_from_private_blob(client, monkeypatch):
    """private Blob の音声をバックエンド経由で配信する。"""
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_test")
    captured = {}

    def fake_get(filename):
        captured["filename"] = filename
        return b"ID3blobcontent", "audio/mpeg"

    monkeypatch.setattr(main, "get_audio_from_blob", fake_get)

    response = client.get("/api/audio/answer_blob.mp3")

    assert response.status_code == 200
    assert captured["filename"] == "answer_blob.mp3"
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.content == b"ID3blobcontent"


def test_get_audio_blob_not_found_returns_404(client, monkeypatch):
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_test")

    def fake_get(filename):
        raise FileNotFoundError(filename)

    monkeypatch.setattr(main, "get_audio_from_blob", fake_get)

    response = client.get("/api/audio/missing.mp3")

    assert response.status_code == 404


def test_get_audio_blob_error_returns_502(client, monkeypatch):
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_test")

    def fake_get(filename):
        raise RuntimeError("blob unavailable")

    monkeypatch.setattr(main, "get_audio_from_blob", fake_get)

    response = client.get("/api/audio/answer.mp3")

    assert response.status_code == 502
