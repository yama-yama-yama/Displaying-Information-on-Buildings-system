# -*- coding: utf-8 -*-
"""ローカル CSV とタグマージ (`feature_tags`) のテスト。"""

import feature_tags
import main


# ==============================================================================
# CSV 読み込み
# ==============================================================================

def test_load_tag_csv_reads_mapfeatures():
    rows = feature_tags.load_tag_csv(feature_tags.MAPFEATURES_CSV)
    assert rows
    assert all(isinstance(cls, str) and isinstance(value, str) for cls, value in rows)
    assert ("amenity", "cafe") in rows


def test_load_tag_csv_reads_high_buildings():
    rows = feature_tags.load_tag_csv(feature_tags.HIGH_BUILDINGS_CSV)
    assert ("man_made", "tower") in rows
    assert ("building", "office") in rows


def test_load_tag_csv_missing_file_returns_empty(tmp_path):
    assert feature_tags.load_tag_csv(str(tmp_path / "missing.csv")) == []


def test_load_high_building_tags_format():
    tags = feature_tags.load_high_building_tags()
    assert "man_made=tower" in tags
    assert all("=" in tag for tag in tags)


def test_is_high_building():
    assert feature_tags.is_high_building("man_made", "tower") is True
    assert feature_tags.is_high_building("building", "office") is True
    assert feature_tags.is_high_building("amenity", "cafe") is False


# ==============================================================================
# collect_search_tags
# ==============================================================================

def test_collect_search_tags_prioritizes_expanded_tags_and_dedupes():
    analysis = {"expanded_tags": ["amenity=cafe"], "feature_keywords": []}
    top_results = [
        {"class": "shop", "value": "bakery", "score": 0.9},
        {"class": "amenity", "value": "cafe", "score": 0.8},  # 重複
        {"class": "building", "value": "yes", "score": 0.2},  # しきい値未満
    ]

    tags = feature_tags.collect_search_tags(analysis, top_results=top_results)

    assert tags == ["amenity=cafe", "shop=bakery"]


def test_collect_search_tags_sorts_top_results_by_score():
    analysis = {"expanded_tags": [], "feature_keywords": []}
    top_results = [
        {"class": "a", "value": "low", "score": 0.6},
        {"class": "b", "value": "high", "score": 0.95},
    ]

    tags = feature_tags.collect_search_tags(analysis, top_results=top_results)
    assert tags == ["b=high", "a=low"]


def test_collect_search_tags_uses_embedded_top_results():
    analysis = {
        "expanded_tags": [],
        "feature_keywords": [],
        "top_results": [{"class": "amenity", "value": "cafe", "score": 0.9}],
    }
    assert feature_tags.collect_search_tags(analysis) == ["amenity=cafe"]


def test_collect_search_tags_supplements_high_buildings():
    analysis = {"expanded_tags": [], "feature_keywords": ["高いビル"]}
    tags = feature_tags.collect_search_tags(analysis)

    assert "building=office" in tags
    assert "building=apartments" in tags


def test_collect_search_tags_supplements_for_english():
    analysis = {"expanded_tags": [], "feature_keywords": [], "translated_en": "tall tower"}
    tags = feature_tags.collect_search_tags(analysis)
    assert "building=office" in tags


def test_collect_search_tags_no_supplement_for_cafe():
    analysis = {"expanded_tags": ["amenity=cafe"], "feature_keywords": ["カフェ"]}
    tags = feature_tags.collect_search_tags(analysis)

    assert tags == ["amenity=cafe"]
    assert "man_made=tower" not in tags


def test_collect_search_tags_respects_max_tags():
    analysis = {"expanded_tags": ["amenity=cafe"], "feature_keywords": ["高層ビル"]}
    tags = feature_tags.collect_search_tags(analysis, max_tags=3)
    assert len(tags) == 3


# ==============================================================================
# build_geolocate_result との統合
# ==============================================================================

def test_build_geolocate_result_uses_merged_tags(monkeypatch):
    monkeypatch.setattr(main, "nominatim_search", lambda *a, **k: None)
    captured = {}

    def fake_overpass_search(lat, lon, tags):
        captured["tags"] = tags
        return [{
            "name": "タワーA",
            "latitude": lat,
            "longitude": lon,
            "bearing": 0,
            "distance_meters": 100,
            "tags": {"man_made": "tower"},
        }]

    monkeypatch.setattr(main, "overpass_search", fake_overpass_search)

    analysis = {
        "resolved_entities": [],
        "expanded_tags": [],
        "feature_keywords": ["高層ビル"],
        "directions": [],
    }
    top_results = [{"class": "man_made", "value": "tower", "score": 0.9}]

    result = main.build_geolocate_result(
        "あの高層ビルは？", analysis, lat=35.0, lon=139.0, top_results=top_results
    )

    assert result["status"] == "overpass_success"
    # expanded_tags は空だが、top_results と high_buildings.csv がマージされる
    assert "man_made=tower" in captured["tags"]
    assert "building=office" in captured["tags"]
    assert result["search_tags"] == captured["tags"]
