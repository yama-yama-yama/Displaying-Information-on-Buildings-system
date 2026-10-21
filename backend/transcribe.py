# -*- coding: utf-8 -*-
"""音声データの文字起こしモジュール。

`voice_comand_test.py` の tkinter / PyAudio による録音部分を切り離し、
FastAPI にアップロードされた音声データを `speech_recognition` で
文字起こしできるようにモジュール化したもの。
"""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from typing import Optional

import speech_recognition as sr

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

DEFAULT_LANGUAGE = "ja-JP"

# Google Web Speech API が扱いやすい形式（モノラル / 16kHz / 16bit PCM）
TARGET_SAMPLE_RATE = 16000
TARGET_SAMPLE_WIDTH = 2

SUPPORTED_UPLOAD_EXTENSIONS = {".wav", ".mp3", ".m4a", ".webm", ".ogg", ".oga", ".flac", ".aac", ".mp4"}


class TranscriptionError(RuntimeError):
    """文字起こしに失敗したことを表す例外。呼び出し側で HTTP 4xx/5xx に変換する。"""


def _is_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def _wav_bytes_to_audio_data(data: bytes) -> sr.AudioData:
    """WAV バイト列を `sr.AudioData` に変換する。"""
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
    except wave.Error as e:
        raise TranscriptionError(f"WAV の解析に失敗しました: {e}")

    if not frames:
        raise TranscriptionError("音声データが空です")
    if sample_width != TARGET_SAMPLE_WIDTH:
        raise TranscriptionError("16bit PCM 形式の WAV のみ対応しています")
    return sr.AudioData(frames, sample_rate, sample_width)


def _convert_with_ffmpeg(data: bytes, suffix: str) -> sr.AudioData:
    """ffmpeg を使って任意形式の音声を WAV(16kHz/mono/16bit) に変換する。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise TranscriptionError(
            "WAV 以外の音声を扱うには ffmpeg が必要です。ffmpeg をインストールするか、"
            "ブラウザ内での音声認識（Web Speech API）をご利用ください。"
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        src_path = os.path.join(tmp_dir, f"input{suffix or '.bin'}")
        dst_path = os.path.join(tmp_dir, "output.wav")
        with open(src_path, "wb") as f:
            f.write(data)

        proc = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-i", src_path,
                "-ac", "1",
                "-ar", str(TARGET_SAMPLE_RATE),
                "-acodec", "pcm_s16le",
                "-f", "wav",
                dst_path,
            ],
            capture_output=True,
        )
        if proc.returncode != 0 or not os.path.exists(dst_path):
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            raise TranscriptionError(f"音声の変換に失敗しました: {stderr}")

        with open(dst_path, "rb") as f:
            return _wav_bytes_to_audio_data(f.read())


def to_audio_data(data: bytes, filename: Optional[str] = None) -> sr.AudioData:
    """アップロードされた音声バイト列を `sr.AudioData` に変換する。"""
    if not data:
        raise TranscriptionError("音声データが空です")

    if _is_wav(data):
        return _wav_bytes_to_audio_data(data)

    suffix = os.path.splitext(filename)[1].lower() if filename else ""
    return _convert_with_ffmpeg(data, suffix)


def transcribe_bytes(
    data: bytes,
    language: str = DEFAULT_LANGUAGE,
    filename: Optional[str] = None,
    recognizer: Optional[sr.Recognizer] = None,
) -> str:
    """音声バイト列を文字起こししてテキストを返す。

    :raises TranscriptionError: 音声が空・非対応形式・認識失敗などの場合。
    """
    recognizer = recognizer or sr.Recognizer()
    audio_data = to_audio_data(data, filename=filename)

    try:
        return recognizer.recognize_google(audio_data, language=language)
    except sr.UnknownValueError:
        raise TranscriptionError("音声を認識できませんでした。もう一度はっきり話してください。")
    except sr.RequestError as e:
        raise TranscriptionError(f"音声認識 API の呼び出しに失敗しました: {e}")
