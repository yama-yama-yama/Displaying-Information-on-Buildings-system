# -*- coding: utf-8 -*-
"""座標計算ヘルパーと build_geolocate_result のテスト。"""

import main


# ==============================================================================
# 距離・方角
# ==============================================================================

def test_haversine_known_distance():
    """東京駅付近と東京タワー付近の距離はおよそ 2.7km。"""
    distance = main.haversine(35.6812, 139.7671, 35.6586, 139.7454)
    assert 2000 < distance < 4000


def test_haversine_zero_for_same_point():
    assert main.haversine(35.0, 139.0, 35.0, 139.0) == 0


def test_calculate_bearing_cardinal():
    assert main.calculate_bearing(0.0, 0.0, 1.0, 0.0) == 0.0      # 北
    assert round(main.calculate_bearing(0.0, 0.0, 0.0, 1.0)) == 90  # 東
    assert round(main.calculate_bearing(0.0, 0.0, -1.0, 0.0)) == 180  # 南
    assert round(main.calculate_bearing(0.0, 0.0, 0.0, -1.0)) == 270  # 西


def test_vector_to_cardinal():
    assert main.vector_to_cardinal(0) == "北"
    assert main.vector_to_cardinal(45) == "北東"
    assert main.vector_to_cardinal(90) == "東"
    assert main.vector_to_cardinal(180) == "南"
    assert main.vector_to_cardinal(270) == "西"
    assert main.vector_to_cardinal(350) == "北"  # ラップ


# ==============================================================================
# build_geolocate_result
# ==============================================================================

def test_build_geolocate_result_success(monkeypatch):
    monkeypatch.setattr(
        main,
        "nominatim_search",
        lambda *a, **k: {
            "lat": "35.658000",
            "lon": "139.745000",
            "display_name": "スターバックス 渋谷店, 渋谷区, 東京都, 日本",
            "class": "amenity",
            "type": "cafe",
        },
    )
    analysis = {
        "resolved_entities": [{"matched_name": "スターバックス"}],
        "expanded_tags": ["amenity=cafe"],
        "feature_keywords": ["スタバ"],
    }

    result = main.build_geolocate_result(
        "スタバはどこ？", analysis, lat=35.6812, lon=139.7671
    )

    assert result["status"] == "geocode_success"
    target = result["found_target"]
    assert target["name"] == "スターバックス 渋谷店"
    assert target["latitude"] == 35.658
    assert target["longitude"] == 139.745
    assert target["distance_meters"] is not None
    assert target["bearing"] is not None
    assert target["vector_name"] is not None
    assert result["candidates"][0] is target


def test_build_geolocate_result_not_found(monkeypatch):
    monkeypatch.setattr(main, "nominatim_search", lambda *a, **k: None)
    analysis = {"resolved_entities": [], "expanded_tags": [], "feature_keywords": []}

    result = main.build_geolocate_result("こんにちは", analysis, lat=None, lon=None)

    assert result["status"] == "not_found"
    assert result["found_target"] is None
    assert result["candidates"] == []


def test_build_geolocate_result_uses_feature_keywords(monkeypatch):
    """固有名詞が無い場合は feature_keywords で検索する。"""
    captured = {}

    def fake_search(query, lat=None, lon=None):
        captured["query"] = query
        return None

    monkeypatch.setattr(main, "nominatim_search", fake_search)
    analysis = {
        "resolved_entities": [],
        "expanded_tags": ["amenity=cafe"],
        "feature_keywords": ["カフェ", "駅前"],
    }

    main.build_geolocate_result("カフェはどこ？", analysis, lat=None, lon=None)
    assert captured["query"] == "カフェ 駅前"
