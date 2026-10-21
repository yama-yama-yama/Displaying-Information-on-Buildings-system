# -*- coding: utf-8 -*-
"""音声文字起こしモジュールと /api/transcribe, /api/audio のテスト。"""

import io
import struct
import wave

import pytest

import main
import transcribe


# ==============================================================================
# ヘルパー
# ==============================================================================

def make_wav_bytes(seconds=0.1, rate=16000):
    """テスト用の無音 WAV バイト列を生成する。"""
    frame_count = int(rate * seconds)
    frames = struct.pack("<" + "h" * frame_count, *([0] * frame_count))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(frames)
    return buf.getvalue()


class FakeRecognizer:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.seen = None

    def recognize_google(self, audio_data, language=None):
        self.seen = {"audio_data": audio_data, "language": language}
        if self.error:
            raise self.error
        return self.result


# ==============================================================================
# transcribe モジュール
# ==============================================================================

def test_transcribe_wav_returns_text():
    recognizer = FakeRecognizer(result="こんにちは")
    text = transcribe.transcribe_bytes(
        make_wav_bytes(), filename="sample.wav", recognizer=recognizer
    )

    assert text == "こんにちは"
    assert recognizer.seen["language"] == "ja-JP"
    assert recognizer.seen["audio_data"].sample_rate == 16000
    assert recognizer.seen["audio_data"].sample_width == 2


def test_transcribe_empty_data_raises():
    with pytest.raises(transcribe.TranscriptionError):
        transcribe.transcribe_bytes(b"", filename="empty.wav")


def test_transcribe_unknown_value_raises():
    import speech_recognition as sr

    recognizer = FakeRecognizer(error=sr.UnknownValueError())
    with pytest.raises(transcribe.TranscriptionError):
        transcribe.transcribe_bytes(make_wav_bytes(), filename="a.wav", recognizer=recognizer)


def test_transcribe_request_error_raises():
    import speech_recognition as sr

    recognizer = FakeRecognizer(error=sr.RequestError("boom"))
    with pytest.raises(transcribe.TranscriptionError):
        transcribe.transcribe_bytes(make_wav_bytes(), filename="a.wav", recognizer=recognizer)


def test_to_audio_data_rejects_non_wav_without_ffmpeg(monkeypatch):
    """WAV 以外かつ ffmpeg が無い場合は分かりやすいエラーを返す。"""
    monkeypatch.setattr(transcribe.shutil, "which", lambda name: None)
    with pytest.raises(transcribe.TranscriptionError):
        transcribe.to_audio_data(b"not-a-wav", filename="a.webm")


# ==============================================================================
# /api/transcribe
# ==============================================================================

def test_transcribe_endpoint_success(client, monkeypatch):
    monkeypatch.setattr(main, "transcribe_bytes", lambda *a, **k: "テスト文字起こし")

    response = client.post(
        "/api/transcribe",
        files={"file": ("sample.wav", make_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "テスト文字起こし", "language": "ja-JP"}


def test_transcribe_endpoint_empty_file_returns_400(client):
    response = client.post(
        "/api/transcribe",
        files={"file": ("empty.wav", b"", "audio/wav")},
    )
    assert response.status_code == 400


def test_transcribe_endpoint_transcription_error_returns_400(client, monkeypatch):
    def boom(*a, **k):
        raise transcribe.TranscriptionError("認識できませんでした")

    monkeypatch.setattr(main, "transcribe_bytes", boom)

    response = client.post(
        "/api/transcribe",
        files={"file": ("sample.wav", make_wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 400


# ==============================================================================
# /api/audio/{filename}
# ==============================================================================

def test_get_audio_serves_file(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "AUDIO_DIR", str(tmp_path))
    (tmp_path / "answer_test.mp3").write_bytes(b"ID3fake")

    response = client.get("/api/audio/answer_test.mp3")

    assert response.status_code == 200
    assert response.content == b"ID3fake"
    assert response.headers["content-type"] == "audio/mpeg"


def test_get_audio_missing_returns_404(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "AUDIO_DIR", str(tmp_path))
    response = client.get("/api/audio/nope.mp3")
    assert response.status_code == 404


def test_get_audio_path_traversal_rejected(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "AUDIO_DIR", str(tmp_path))
    (tmp_path.parent / "secret.mp3").write_bytes(b"secret")

    response = client.get("/api/audio/..%2Fsecret.mp3")
    assert response.status_code in (400, 404)
