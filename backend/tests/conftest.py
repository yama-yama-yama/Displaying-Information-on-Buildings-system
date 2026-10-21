# -*- coding: utf-8 -*-
"""pytest 共通設定。

backend ディレクトリを import パスに追加し、`main` などを直接 import できるようにする。
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import main  # noqa: E402  (sys.path 設定後に import する必要がある)


@pytest.fixture()
def client():
    """FastAPI のテストクライアント。"""
    return TestClient(main.app)


@pytest.fixture()
def fake_analysis():
    """analyze_and_search の最小限の戻り値。"""
    return {
        "input_text": "右斜め前のスタバはどこ？",
        "analysis": {
            "directions": [],
            "intent": {
                "intent": "where",
                "name": "場所を尋ねる",
                "description": "",
                "matched": "どこ",
            },
            "resolved_entities": [
                {
                    "matched_name": "スターバックス",
                    "source": "manual",
                    "class": "amenity",
                    "value": "cafe",
                    "tags": ["amenity=cafe"],
                }
            ],
            "expanded_tags": ["amenity=cafe"],
            "feature_keywords": ["スタバ"],
            "translated_en": "starbucks",
            "tokens": ["starbucks"],
        },
        "method": "difflib",
        "top_results": [],
    }


@pytest.fixture()
def fake_nominatim():
    """nominatim_search が返す 1 件分の結果。"""
    return {
        "lat": "35.658000",
        "lon": "139.745000",
        "display_name": "スターバックス 渋谷店, 渋谷区, 東京都, 日本",
        "class": "amenity",
        "type": "cafe",
    }
