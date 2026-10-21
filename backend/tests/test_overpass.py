# -*- coding: utf-8 -*-
"""Overpass 周辺検索と候補ランキングのテスト。"""

import main


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


# ==============================================================================
# タグフィルタ
# ==============================================================================

def test_overpass_tag_filter_key_value():
    assert main._overpass_tag_filter("amenity=cafe") == '["amenity"="cafe"]'


def test_overpass_tag_filter_single_key():
    assert main._overpass_tag_filter("building") == '["building"]'


def test_overpass_tag_filter_rejects_invalid():
    assert main._overpass_tag_filter("") is None
    assert main._overpass_tag_filter("amenity=cafe;out;") is None
    assert main._overpass_tag_filter("amenity=") is None
    assert main._overpass_tag_filter(None) is None


# ==============================================================================
# overpass_search
# ==============================================================================

def test_overpass_search_parses_nodes_and_ways(monkeypatch):
    payload = {
        "elements": [
            {
                "type": "node",
                "lat": 35.6815,
                "lon": 139.7675,
                "tags": {
                    "amenity": "cafe",
                    "name": "カフェA",
                    "building:levels": "2",
                },
            },
            {
                "type": "way",
                "center": {"lat": 35.6800, "lon": 139.7660},
                "tags": {
                    "amenity": "cafe",
                    "name": "カフェB",
                    "height": "10",
                    "start_date": "2020",
                },
            },
            # 座標が無い要素はスキップされる
            {"type": "node", "tags": {"amenity": "cafe"}},
        ]
    }
    captured = {}

    def fake_post(url, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["query"] = data["data"]
        return FakeResponse(payload)

    monkeypatch.setattr(main.requests, "post", fake_post)

    candidates = main.overpass_search(35.6812, 139.7671, ["amenity=cafe", "building"])

    assert len(candidates) == 2
    assert "node[\"amenity\"=\"cafe\"]" in captured["query"]
    assert "way[\"building\"]" in captured["query"]
    assert "around:" in captured["query"]

    cafe_a, cafe_b = candidates
    assert cafe_a["name"] == "カフェA"
    assert cafe_a["osm_class"] == "amenity"
    assert cafe_a["osm_type"] == "cafe"
    assert cafe_a["building_levels"] == "2"
    assert cafe_a["is_high_building"] is False
    assert isinstance(cafe_a["distance_meters"], int)
    assert cafe_a["vector_name"] in {"北", "北東", "東", "南東", "南", "南西", "西", "北西"}

    assert cafe_b["height"] == "10"
    assert cafe_b["start_date"] == "2020"
    assert cafe_b["latitude"] == 35.68


def test_overpass_search_without_tags_returns_empty(monkeypatch):
    def fail(*args, **kwargs):  # pragma: no cover
        raise AssertionError("タグが無い場合は API を呼ばない")

    monkeypatch.setattr(main.requests, "post", fail)
    assert main.overpass_search(35.0, 139.0, []) == []


def test_overpass_search_marks_high_building(monkeypatch):
    payload = {
        "elements": [
            {
                "type": "node",
                "lat": 35.6586,
                "lon": 139.7454,
                "tags": {"man_made": "tower", "name": "タワー"},
            }
        ]
    }
    monkeypatch.setattr(
        main.requests, "post", lambda *a, **k: FakeResponse(payload)
    )

    candidates = main.overpass_search(35.6812, 139.7671, ["man_made=tower"])
    assert len(candidates) == 1
    assert candidates[0]["is_high_building"] is True


def test_overpass_search_handles_request_error(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(main.requests, "post", boom)
    assert main.overpass_search(35.0, 139.0, ["amenity=cafe"]) == []


# ==============================================================================
# rank_candidates
# ==============================================================================

def _candidate(name, bearing, distance, amenity="cafe"):
    return {
        "name": name,
        "bearing": bearing,
        "distance_meters": distance,
        "tags": {"amenity": amenity},
    }


def test_rank_candidates_prefers_matching_relative_direction():
    analysis = {
        "directions": [{"category": "relative", "key": "front_right", "vector": [1, 1]}],
        "expanded_tags": ["amenity=cafe"],
        "feature_keywords": ["カフェ"],
    }
    candidates = [
        _candidate("左斜め前", bearing=315, distance=50),
        _candidate("右斜め前", bearing=45, distance=100),
    ]

    ranked = main.rank_candidates(candidates, analysis, facing="north")

    assert ranked[0]["name"] == "右斜め前"
    assert ranked[0]["direction_score"] == 1.0
    assert ranked[1]["direction_score"] == 0.0
    assert ranked[0]["score"] > ranked[1]["score"]


def test_rank_candidates_prefers_matching_cardinal_direction():
    analysis = {
        "directions": [{"category": "cardinal", "key": "north", "vector": [0, 1]}],
        "expanded_tags": [],
        "feature_keywords": [],
    }
    candidates = [
        _candidate("南", bearing=180, distance=50),
        _candidate("北", bearing=5, distance=120),
    ]

    ranked = main.rank_candidates(candidates, analysis, facing="north")
    assert ranked[0]["name"] == "北"


def test_rank_candidates_without_direction_is_neutral():
    analysis = {"directions": [], "expanded_tags": ["amenity=cafe"], "feature_keywords": []}
    candidates = [_candidate("近い", bearing=0, distance=50), _candidate("遠い", bearing=180, distance=400)]

    ranked = main.rank_candidates(candidates, analysis)
    assert ranked[0]["name"] == "近い"
    assert all(c["direction_score"] == 0.5 for c in ranked)


# ==============================================================================
# build_geolocate_result の Overpass フォールバック
# ==============================================================================

def test_build_geolocate_result_falls_back_to_overpass(monkeypatch):
    monkeypatch.setattr(main, "nominatim_search", lambda *a, **k: None)

    overpass_candidates = [
        _candidate("カフェB", bearing=45, distance=120),
        _candidate("カフェA", bearing=315, distance=80),
    ]
    monkeypatch.setattr(
        main, "overpass_search", lambda lat, lon, tags: overpass_candidates
    )

    analysis = {
        "resolved_entities": [],
        "expanded_tags": ["amenity=cafe"],
        "feature_keywords": [],
        "directions": [{"category": "cardinal", "key": "northeast", "vector": [1, 1]}],
    }

    result = main.build_geolocate_result(
        "北東のカフェは？", analysis, lat=35.6812, lon=139.7671, facing="north"
    )

    assert result["status"] == "overpass_success"
    assert result["found_target"]["name"] == "カフェB"
    assert len(result["candidates"]) == 2
    assert result["candidates"][0]["score"] >= result["candidates"][1]["score"]


def test_build_geolocate_result_no_overpass_without_location(monkeypatch):
    monkeypatch.setattr(main, "nominatim_search", lambda *a, **k: None)

    def fail(*args, **kwargs):  # pragma: no cover
        raise AssertionError("位置情報が無い場合は Overpass を呼ばない")

    monkeypatch.setattr(main, "overpass_search", fail)

    analysis = {
        "resolved_entities": [],
        "expanded_tags": ["amenity=cafe"],
        "feature_keywords": [],
    }
    result = main.build_geolocate_result("カフェは？", analysis, lat=None, lon=None)

    assert result["status"] == "not_found"
