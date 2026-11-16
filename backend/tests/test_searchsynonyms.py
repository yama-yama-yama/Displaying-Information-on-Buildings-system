# -*- coding: utf-8 -*-
"""日本語キーワード抽出・接尾辞ルール・類似度計算のテスト。"""

import searchsynonyms_mapfeatures_v2 as ss


# ==============================================================================
# 日本語の分割
# ==============================================================================

def test_split_ja_segments_basic():
    assert ss.split_ja_segments("前方のドームの大きさ") == ["ドーム"]


def test_split_ja_segments_keeps_proper_noun():
    assert ss.split_ja_segments("サンドーム福井の大きさ") == ["サンドーム福井"]


def test_split_ja_segments_removes_question_words():
    assert ss.split_ja_segments("スターバックスはどこ") == ["スターバックス"]


# ==============================================================================
# 接尾辞ルールとタグ形式
# ==============================================================================

def test_suffix_rule_matches_segment():
    result = ss.resolve_entities_and_keywords("前方のドームの大きさ")

    assert result["feature_keywords"] == ["ドーム"]
    assert "leisure=stadium" in result["expanded_tags"]


def test_expanded_tags_are_key_value():
    result = ss.resolve_entities_and_keywords("前方のドームの大きさ")

    assert result["expanded_tags"]
    assert all("=" in tag for tag in result["expanded_tags"])
    assert "stadium" in result["expanded_keywords"]


def test_known_entity_is_key_value():
    result = ss.resolve_entities_and_keywords("東京タワーはどこ")

    assert "man_made=tower" in result["expanded_tags"]
    assert "tower" in result["expanded_keywords"]


# ==============================================================================
# difflib の誤マッチ抑制
# ==============================================================================

def test_difflib_rejects_dome_home():
    score, _, _ = ss.calculate_similarity_difflib([("dome", "dome")], "home")
    assert score < 0.5


def test_difflib_rejects_size_site():
    score, _, _ = ss.calculate_similarity_difflib([("size", "size")], "site")
    assert score < 0.5


def test_difflib_accepts_exact():
    score, _, _ = ss.calculate_similarity_difflib([("stadium", "stadium")], "stadium")
    assert score == 1.0


def test_difflib_uses_value_part_of_expanded_tags():
    score, _, _ = ss.calculate_similarity_difflib(
        [("nothing", "nothing")], "stadium", expanded_tags=["leisure=stadium"]
    )
    assert score == 1.0


# ==============================================================================
# analyze_and_search の統合
# ==============================================================================

def test_analyze_and_search_dome(monkeypatch):
    monkeypatch.setattr(ss, "translate_ja_to_en", lambda text: "dome")

    result = ss.analyze_and_search("前方のドームの大きさ", use_ginza=False, top_k=20)
    analysis = result["analysis"]

    assert analysis["feature_keywords"] == ["ドーム"]
    assert "leisure=stadium" in analysis["expanded_tags"]
    assert "expanded_keywords" in analysis
