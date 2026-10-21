# -*- coding: utf-8 -*-
"""ローカル CSV と解析結果から Overpass 用のタグ候補を組み立てるモジュール。

## マージ方針（優先順位）

1. `expanded_tags`
   固有名詞解決（`resolve_entities_and_keywords`）で得た高信頼のタグ候補を最優先する。
2. `top_results`（`mapfeatures.csv` との類似度検索結果）
   スコア降順で追加する。`MIN_SCORE` 未満の候補はノイズになるため除外する。
3. `high_buildings.csv` による高層建築の補完
   質問が「ビル / タワー / 高層」など高い建造物を対象にしている場合のみ、
   高層建築タグを補完候補として追加する。

重複は挿入順を保ったまま除去し、最終的に `max_tags` 件へ切り詰める。
`mapfeatures.csv` は候補の網羅性を、`high_buildings.csv` は
高層建築というカテゴリの精度を担う、という役割分担に整理する。
"""

import csv
import os

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

MAPFEATURES_CSV = os.path.join(BACKEND_DIR, "mapfeatures.csv")
HIGH_BUILDINGS_CSV = os.path.join(BACKEND_DIR, "high_buildings.csv")

# Overpass クエリを重くしすぎないための上限
MAX_TAGS = 8
# mapfeatures.csv の類似度スコアしきい値
MIN_SCORE = 0.5

# 高層建築とみなす質問キーワード
HIGH_BUILDING_KEYWORDS = (
    "ビル", "タワー", "高層", "塔", "マンション", "超高層", "ランドマーク",
)
HIGH_BUILDING_EN_KEYWORDS = ("tower", "skyscraper", "high-rise", "high rise")


def load_tag_csv(path):
    """``class,value`` 形式の CSV を ``[(class, value), ...]`` として読み込む。"""
    if not os.path.exists(path):
        return []

    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cls = (row.get("class") or "").strip()
            value = (row.get("value") or "").strip()
            if cls and value:
                rows.append((cls, value))
    return rows


def load_high_building_tags():
    """`high_buildings.csv` を ``["man_made=tower", ...]`` 形式で返す。"""
    return [f"{cls}={value}" for cls, value in load_tag_csv(HIGH_BUILDINGS_CSV)]


# 候補が高層建築かどうかを O(1) で判定するための集合
HIGH_BUILDING_SET = frozenset(load_tag_csv(HIGH_BUILDINGS_CSV))


def is_high_building(osm_class, osm_type):
    """OSM の class/type が `high_buildings.csv` に含まれるか。"""
    return (str(osm_class), str(osm_type)) in HIGH_BUILDING_SET


def _needs_high_building_supplement(analysis, current_tags):
    """高層建築タグの補完が必要かを判定する。"""
    keywords = analysis.get("feature_keywords") or []
    text = " ".join(str(k) for k in keywords)
    text += " " + str(analysis.get("translated_en") or "")

    if any(kw in text for kw in HIGH_BUILDING_KEYWORDS):
        return True
    lowered = text.lower()
    return any(kw in lowered for kw in HIGH_BUILDING_EN_KEYWORDS)


def collect_search_tags(
    analysis,
    top_results=None,
    max_tags=MAX_TAGS,
    min_score=MIN_SCORE,
):
    """
    解析結果とローカル CSV をマージし、Overpass 検索に使うタグ一覧を返す。

    :param analysis: `analyze_and_search` の `analysis` 部分
    :param top_results: 類似度検索結果。None の場合は `analysis["top_results"]` を参照
    :param max_tags: 返すタグの最大件数
    :param min_score: `top_results` を採用する最小スコア
    """
    analysis = analysis or {}
    tags = []
    seen = set()

    def add(tag):
        if not isinstance(tag, str):
            return
        tag = tag.strip()
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)

    # 1. 固有名詞解決で得た高信頼タグ
    for tag in analysis.get("expanded_tags") or []:
        add(tag)

    # 2. mapfeatures.csv との類似度検索結果
    rows = top_results if top_results is not None else analysis.get("top_results") or []
    for row in sorted(rows, key=lambda r: r.get("score", 0), reverse=True):
        if row.get("score", 0) < min_score:
            continue
        cls = str(row.get("class") or "").strip()
        value = str(row.get("value") or "").strip()
        if cls and value:
            add(f"{cls}={value}")

    # 3. 高層建築の補完
    if _needs_high_building_supplement(analysis, tags):
        for tag in load_high_building_tags():
            add(tag)

    return tags[:max_tags]
