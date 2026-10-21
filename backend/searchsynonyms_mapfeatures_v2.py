# -*- coding: utf-8 -*-
"""
MapFeatures 類似度検索 & 自然文解析プログラム v2
(searchsynonyms_mapfeatures_v2.py)

【機能追加・改善点】
1. 自然文から「方向 (前後左右、方角・8方位)」を高精度に抽出・分類 (ベクトル・相対コマンド対応)
2. 「質問タイプ (なんですか？, どこですか？, ありますか？, どう行きますか？ など)」を自動分類
3. 建物名や施設名などの固有名詞（スカイツリー、スタバ、マック、浅草寺、慶應義塾大学など）を
   OSM (OpenStreetMap) の map features タグに高精度に結びつけるエンティティ解決・辞書・接尾辞ルール・LLM連携
4. difflib / word2vec の2つの類似度計算アルゴリズムに対応
5. CLI対話型、引数実行、JSON出力、Pythonモジュール呼び出しに完全対応
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import difflib
import requests

# Windows 環境での標準出力の文字化け対策
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# ==============================================================================
# 0. グローバル設定 & モデル遅延読み込み
# ==============================================================================

GEMINI_API_KEY = None
api_key_file = os.path.join(os.path.dirname(__file__), "api_KEY.txt")
if os.path.exists(api_key_file):
    try:
        with open(api_key_file, "r", encoding="utf-8") as f:
            GEMINI_API_KEY = f.read().strip()
    except Exception:
        pass

WORD2VEC_MODEL = None
GINZA_NLP = None


def get_word2vec_model():
    """
    Word2Vec (glove-wiki-gigaword-50) モデルを遅延読み込みする関数
    """
    global WORD2VEC_MODEL
    if WORD2VEC_MODEL is None:
        print("\n[初期化] Word2Vec モデル (glove-wiki-gigaword-50) をロード中... (初回は時間がかかる場合があります)", file=sys.stderr)
        try:
            import gensim.downloader as api
            WORD2VEC_MODEL = api.load('glove-wiki-gigaword-50')
            print("[初期化] Word2Vec モデルのロードが完了しました。\n", file=sys.stderr)
        except Exception as e:
            print(f"[エラー] Word2Vec モデルのロードに失敗しました: {e}", file=sys.stderr)
            raise e
    return WORD2VEC_MODEL


def get_ginza_nlp():
    """
    spaCy GiNZA (ja_ginza) モデルを遅延読み込みする関数
    """
    global GINZA_NLP
    if GINZA_NLP is None:
        print("\n[初期化] spaCy GiNZA モデル (ja_ginza) をロード中...", file=sys.stderr)
        try:
            import spacy
            try:
                GINZA_NLP = spacy.load("ja_ginza", config={"components": {"compound_splitter": {"split_mode": "C"}}})
            except Exception:
                GINZA_NLP = spacy.load("ja_ginza", disable=["compound_splitter"])
            print("[初期化] spaCy GiNZA モデルのロードが完了しました。\n", file=sys.stderr)
        except Exception as e:
            print(f"[警告] GiNZA モデルのロードに失敗しました (ルールベースのみで動作します): {e}", file=sys.stderr)
            GINZA_NLP = None
    return GINZA_NLP


# ==============================================================================
# 1. 方向 (前後左右、方角) の分類・抽出エンジン
# ==============================================================================

# 相対方向定義 (前後左右・斜め)
RELATIVE_PATTERNS = [
    # 複合斜め方向（最長一致を優先）
    ("front_right", "右斜め前", [r"右(?:斜め)?前(?:方|側)?"], "front_right", (1, 1)),
    ("front_left",  "左斜め前", [r"左(?:斜め)?前(?:方|側)?"], "front_left", (-1, 1)),
    ("back_right",  "右斜め後ろ", [r"右(?:斜め)?後(?:ろ|方|側)?"], "back_right", (1, -1)),
    ("back_left",   "左斜め後ろ", [r"左(?:斜め)?後(?:ろ|方|側)?"], "back_left", (-1, -1)),
    # 単純相対方向
    ("front", "前方", [r"正面", r"目の前", r"まっすぐ", r"直進", r"(?<!斜め)(?<![左右])前(?:方|側)?"], "front", (0, 1)),
    ("back",  "後方", [r"背後", r"(?<![左右])うしろ", r"(?<!斜め)(?<![左右])後(?:ろ|方|側)?"], "back", (0, -1)),
    ("right", "右側", [r"(?<!斜め)(?<![前後])右(?:側|手|手側)?", r"(?<![前後])みぎ"], "right", (1, 0)),
    ("left",  "左側", [r"(?<!斜め)(?<![前後])左(?:側|手|手側)?", r"(?<![前後])ひだり"], "left", (-1, 0)),
]

# 絶対方角定義 (8方位)
CARDINAL_PATTERNS = [
    # 8方位（4文字・3文字・2文字の方位を優先）
    ("northeast", "北東", [r"(?:真)?北東(?:方角|方向|側)?" , r"(?:真)?東北(?:方角|方向|側)?"], (1, 1), "↗"),
    ("northwest", "北西", [r"(?:真)?北西(?:方角|方向|側)?" , r"(?:真)?西北(?:方角|方向|側)?"], (-1, 1), "↖"),
    ("southeast", "南東", [r"(?:真)?南東(?:方角|方向|側)?" , r"(?:真)?東南(?:方角|方向|側)?"], (1, -1), "↘"),
    ("southwest", "南西", [r"(?:真)?南西(?:方角|方向|側)?" , r"(?:真)?西南(?:方角|方向|側)?"], (-1, -1), "↙"),
    # 4方位（固有名詞の一部に誤マッチしないよう文脈チェック）
    ("north", "北", [r"真北", r"(?<![東西南北])北(?:方角|方向|側|の|に|へ)"], (0, 1), "↑"),
    ("south", "南", [r"真南", r"(?<![東西南北])南(?:方角|方向|側|の|に|へ)"], (0, -1), "↓"),
    ("east",  "東", [r"真東", r"(?<![東西南北東])東(?:方角|方向|側|の|に|へ)"], (1, 0), "→"),
    ("west",  "西", [r"真西", r"(?<![東西南北])西(?:方角|方向|側|の|に|へ)"], (-1, 0), "←"),
]


def extract_directions(text):
    """
    入力されたテキストから相対方向 (前後左右) および絶対方角 (東西南北) を抽出・正規化する
    """
    raw_matches = []

    # 1. 相対方向マッチング
    for key, name, patterns, cmd, vec in RELATIVE_PATTERNS:
        for pat in patterns:
            for m in re.finditer(pat, text):
                raw_matches.append({
                    "category": "relative",
                    "key": key,
                    "name": name,
                    "matched": m.group(0),
                    "start": m.start(),
                    "end": m.end(),
                    "length": m.end() - m.start(),
                    "command": cmd,
                    "vector": list(vec)
                })

    # 2. 絶対方角マッチング
    for key, name, patterns, vec, sym in CARDINAL_PATTERNS:
        for pat in patterns:
            for m in re.finditer(pat, text):
                start, end = m.start(), m.end()
                matched_str = m.group(0)

                # 「東京」「京都」「東北」などの固有名詞の誤検知を除外
                if text[start:end+1].startswith("東京") or text[max(0, start-1):end+1] == "東京":
                    continue
                if "京都" in text[max(0, start-1):end+1]:
                    continue
                if "東北" in text[max(0, start-1):end+1] and key in ("north", "east"):
                    continue

                raw_matches.append({
                    "category": "cardinal",
                    "key": key,
                    "name": name,
                    "matched": matched_str,
                    "start": start,
                    "end": end,
                    "length": end - start,
                    "vector": list(vec),
                    "symbol": sym
                })

    # 3. スパン重複の解消（最長一致を優先し、重なり合う短縮スパンを除去）
    raw_matches.sort(key=lambda x: (-x["length"], x["start"]))

    selected_matches = []
    occupied_spans = []

    for m in raw_matches:
        m_span = set(range(m["start"], m["end"]))
        overlap = False
        for occ in occupied_spans:
            if m_span & occ:
                overlap = True
                break
        if not overlap:
            selected_matches.append(m)
            occupied_spans.append(m_span)

    # 出現順に並び替え
    selected_matches.sort(key=lambda x: x["start"])
    return selected_matches


# ==============================================================================
# 2. 質問タイプ (なんですか？, どこですか？など) の分類エンジン
# ==============================================================================

QUESTION_INTENTS = [
    {
        "intent": "WHAT",
        "name": "地物・名称・説明の質問 (What)",
        "description": "対象の地物の名前や種類、内容、説明を尋ねる質問",
        "patterns": [
            r"何(?:です|だ|なん|が|の|に|だろう|かしら)", r"なん(?:です|だ|なん|が|の|に|だろう)",
            r"どんな", r"どのような", r"何の建物", r"何の施設",
            r"名前(?:を|は|って)?(?:教えて)?", r"教えて", r"説明して"
        ]
    },
    {
        "intent": "WHERE",
        "name": "位置・場所の質問 (Where)",
        "description": "対象の地物が存在する位置・方角・場所を尋ねる質問",
        "patterns": [
            r"どこ(?:です|に|へ|だ|らへん|ら辺)?", r"どちら(?:です|に|へ|側)?",
            r"場所(?:は|を|って)?", r"位置(?:は|を|って)?", r"どの辺"
        ]
    },
    {
        "intent": "EXISTENCE",
        "name": "存在確認・有無の質問 (Existence)",
        "description": "指定された施設・地物が周辺にあるかどうかを確認する質問",
        "patterns": [
            r"あり(?:ます|る|ない|ますか|るか)", r"見え(?:ます|る|ない|ますか)",
            r"存在し(?:ます|て|ない|ますか)", r"あっ(?:たり|た|てますか)",
            r"ある(?:の|かな|かしら|\?|？)"
        ]
    },
    {
        "intent": "HOW_TO_GO",
        "name": "アクセス・行き方の質問 (How to go / Route)",
        "description": "目的地への行き方・道順・経路を尋ねる質問",
        "patterns": [
            r"どう(?:やって)?(?:行き|行け|いく)", r"行き方", r"道順", r"アクセス",
            r"どう行けば", r"案内して", r"ルート"
        ]
    },
    {
        "intent": "FACILITY_INFO",
        "name": "施設詳細・営業情報の質問 (Facility Info)",
        "description": "料金、営業時間、電話番号等の詳細情報を尋ねる質問",
        "patterns": [
            r"いくら", r"料金", r"営業時間", r"何時まで", r"開いて", r"電話番号",
            r"定休日", r"休み", r"費用"
        ]
    }
]


def classify_question_intent(text):
    """
    質問文のパターンからユーザーの質問の意図（Intent）を分類する
    """
    for item in QUESTION_INTENTS:
        for pat in item["patterns"]:
            m = re.search(pat, text)
            if m:
                return {
                    "intent": item["intent"],
                    "name": item["name"],
                    "description": item["description"],
                    "matched": m.group(0)
                }
    return {
        "intent": "GENERAL_QUERY",
        "name": "一般的な検索・問い合わせ",
        "description": "特定の疑問詞を含まない地物検索クエリ",
        "matched": ""
    }


# ==============================================================================
# 3. 固有名詞・地物抽出 & OSMタグ解決エンジン
# ==============================================================================

# 代表的な固有名詞・ブランド・施設知識ベース
BUILTIN_ENTITY_MAP = {
    # ランドマーク・タワー・展望施設
    "スカイツリー": {"class": "man_made", "value": "communications_tower", "tags": ["tower", "viewpoint", "attraction", "building"]},
    "東京タワー": {"class": "man_made", "value": "tower", "tags": ["tower", "viewpoint", "attraction", "building"]},
    "通天閣": {"class": "man_made", "value": "tower", "tags": ["tower", "viewpoint", "attraction", "building"]},
    "京都タワー": {"class": "man_made", "value": "tower", "tags": ["tower", "viewpoint", "attraction", "building"]},
    "エッフェル塔": {"class": "man_made", "value": "tower", "tags": ["tower", "viewpoint", "attraction", "building"]},
    "あべのハルカス": {"class": "man_made", "value": "tower", "tags": ["tower", "viewpoint", "building", "commercial"]},
    "ランドマークタワー": {"class": "man_made", "value": "tower", "tags": ["tower", "viewpoint", "building"]},
    "ミッドタウン": {"class": "building", "value": "commercial", "tags": ["commercial", "building", "mall"]},
    "六本木ヒルズ": {"class": "building", "value": "commercial", "tags": ["commercial", "building", "viewpoint"]},

    # カフェ・喫茶
    "スタバ": {"class": "amenity", "value": "cafe", "tags": ["cafe", "coffee_shop"]},
    "スターバックス": {"class": "amenity", "value": "cafe", "tags": ["cafe", "coffee_shop"]},
    "ドトール": {"class": "amenity", "value": "cafe", "tags": ["cafe", "coffee_shop"]},
    "タリーズ": {"class": "amenity", "value": "cafe", "tags": ["cafe", "coffee_shop"]},
    "コメダ": {"class": "amenity", "value": "cafe", "tags": ["cafe", "coffee_shop"]},
    "コメダ珈琲": {"class": "amenity", "value": "cafe", "tags": ["cafe", "coffee_shop"]},
    "星乃珈琲": {"class": "amenity", "value": "cafe", "tags": ["cafe", "coffee_shop"]},
    "ブルーボトル": {"class": "amenity", "value": "cafe", "tags": ["cafe", "coffee_shop"]},
    "サンマルク": {"class": "amenity", "value": "cafe", "tags": ["cafe", "bakery"]},

    # ファストフード・飲食店
    "マック": {"class": "amenity", "value": "fast_food", "tags": ["fast_food", "restaurant"]},
    "マクドナルド": {"class": "amenity", "value": "fast_food", "tags": ["fast_food", "restaurant"]},
    "モス": {"class": "amenity", "value": "fast_food", "tags": ["fast_food", "restaurant"]},
    "モスバーガー": {"class": "amenity", "value": "fast_food", "tags": ["fast_food", "restaurant"]},
    "ケンタッキー": {"class": "amenity", "value": "fast_food", "tags": ["fast_food", "restaurant"]},
    "KFC": {"class": "amenity", "value": "fast_food", "tags": ["fast_food", "restaurant"]},
    "吉野家": {"class": "amenity", "value": "fast_food", "tags": ["fast_food", "restaurant"]},
    "すき家": {"class": "amenity", "value": "fast_food", "tags": ["fast_food", "restaurant"]},
    "松屋": {"class": "amenity", "value": "fast_food", "tags": ["fast_food", "restaurant"]},
    "サイゼリヤ": {"class": "amenity", "value": "restaurant", "tags": ["restaurant", "fast_food"]},
    "サイゼ": {"class": "amenity", "value": "restaurant", "tags": ["restaurant", "fast_food"]},
    "ガスト": {"class": "amenity", "value": "restaurant", "tags": ["restaurant"]},
    "バーミヤン": {"class": "amenity", "value": "restaurant", "tags": ["restaurant"]},
    "スシロー": {"class": "amenity", "value": "restaurant", "tags": ["restaurant"]},
    "くら寿司": {"class": "amenity", "value": "restaurant", "tags": ["restaurant"]},
    "はま寿司": {"class": "amenity", "value": "restaurant", "tags": ["restaurant"]},
    "一蘭": {"class": "amenity", "value": "restaurant", "tags": ["restaurant"]},
    "日高屋": {"class": "amenity", "value": "restaurant", "tags": ["restaurant"]},

    # コンビニ
    "セブン": {"class": "shop", "value": "convenience", "tags": ["convenience", "supermarket"]},
    "セブンイレブン": {"class": "shop", "value": "convenience", "tags": ["convenience", "supermarket"]},
    "ローソン": {"class": "shop", "value": "convenience", "tags": ["convenience", "supermarket"]},
    "ファミマ": {"class": "shop", "value": "convenience", "tags": ["convenience", "supermarket"]},
    "ファミリーマート": {"class": "shop", "value": "convenience", "tags": ["convenience", "supermarket"]},
    "ミニストップ": {"class": "shop", "value": "convenience", "tags": ["convenience", "supermarket"]},
    "デイリーヤマザキ": {"class": "shop", "value": "convenience", "tags": ["convenience", "supermarket"]},
    "セイコーマート": {"class": "shop", "value": "convenience", "tags": ["convenience", "supermarket"]},

    # ショッピング・スーパー・百貨店
    "イオン": {"class": "shop", "value": "supermarket", "tags": ["supermarket", "mall", "department_store"]},
    "ららぽーと": {"class": "shop", "value": "mall", "tags": ["mall", "supermarket", "department_store"]},
    "ドンキ": {"class": "shop", "value": "department_store", "tags": ["department_store", "supermarket"]},
    "ドン・キホーテ": {"class": "shop", "value": "department_store", "tags": ["department_store", "supermarket"]},
    "パルコ": {"class": "shop", "value": "mall", "tags": ["mall", "department_store"]},
    "マルイ": {"class": "shop", "value": "department_store", "tags": ["department_store", "mall"]},
    "高島屋": {"class": "shop", "value": "department_store", "tags": ["department_store", "mall"]},
    "伊勢丹": {"class": "shop", "value": "department_store", "tags": ["department_store", "mall"]},
    "三越": {"class": "shop", "value": "department_store", "tags": ["department_store", "mall"]},
    "イトーヨーカドー": {"class": "shop", "value": "supermarket", "tags": ["supermarket", "mall"]},
    "ライフ": {"class": "shop", "value": "supermarket", "tags": ["supermarket"]},
    "西友": {"class": "shop", "value": "supermarket", "tags": ["supermarket"]},
    "まいばすけっと": {"class": "shop", "value": "supermarket", "tags": ["supermarket", "convenience"]},

    # 寺社仏閣・歴史・宗教
    "浅草寺": {"class": "amenity", "value": "place_of_worship", "tags": ["place_of_worship", "historic", "attraction"]},
    "清水寺": {"class": "amenity", "value": "place_of_worship", "tags": ["place_of_worship", "historic", "attraction"]},
    "金閣寺": {"class": "amenity", "value": "place_of_worship", "tags": ["place_of_worship", "historic", "attraction"]},
    "銀閣寺": {"class": "amenity", "value": "place_of_worship", "tags": ["place_of_worship", "historic", "attraction"]},
    "東寺": {"class": "amenity", "value": "place_of_worship", "tags": ["place_of_worship", "historic", "attraction"]},
    "明治神宮": {"class": "amenity", "value": "place_of_worship", "tags": ["place_of_worship", "historic", "attraction"]},
    "伏見稲荷": {"class": "amenity", "value": "place_of_worship", "tags": ["place_of_worship", "historic", "attraction"]},
    "伏見稲荷大社": {"class": "amenity", "value": "place_of_worship", "tags": ["place_of_worship", "historic", "attraction"]},
    "伊勢神宮": {"class": "amenity", "value": "place_of_worship", "tags": ["place_of_worship", "historic", "attraction"]},
    "出雲大社": {"class": "amenity", "value": "place_of_worship", "tags": ["place_of_worship", "historic", "attraction"]},
    "靖国神社": {"class": "amenity", "value": "place_of_worship", "tags": ["place_of_worship", "historic", "attraction"]},
    "厳島神社": {"class": "amenity", "value": "place_of_worship", "tags": ["place_of_worship", "historic", "attraction"]},

    # スタジアム・ドーム・スポーツ
    "東京ドーム": {"class": "leisure", "value": "stadium", "tags": ["stadium", "sports_centre", "pitch"]},
    "京セラドーム": {"class": "leisure", "value": "stadium", "tags": ["stadium", "sports_centre", "pitch"]},
    "PayPayドーム": {"class": "leisure", "value": "stadium", "tags": ["stadium", "sports_centre", "pitch"]},
    "甲子園": {"class": "leisure", "value": "stadium", "tags": ["stadium", "sports_centre", "pitch"]},
    "国立競技場": {"class": "leisure", "value": "stadium", "tags": ["stadium", "sports_centre", "pitch"]},
    "武道館": {"class": "leisure", "value": "sports_centre", "tags": ["sports_centre", "stadium", "theatre"]},

    # テーマパーク・観光・レジャー
    "ディズニー": {"class": "tourism", "value": "theme_park", "tags": ["theme_park", "attraction"]},
    "ディズニーランド": {"class": "tourism", "value": "theme_park", "tags": ["theme_park", "attraction"]},
    "ディズニーシー": {"class": "tourism", "value": "theme_park", "tags": ["theme_park", "attraction"]},
    "USJ": {"class": "tourism", "value": "theme_park", "tags": ["theme_park", "attraction"]},
    "ユニバ": {"class": "tourism", "value": "theme_park", "tags": ["theme_park", "attraction"]},
    "ジブリパーク": {"class": "tourism", "value": "theme_park", "tags": ["theme_park", "attraction"]},
    "サンリオピューロランド": {"class": "tourism", "value": "theme_park", "tags": ["theme_park", "attraction"]},

    # 水族館・動物園
    "美ら海水族館": {"class": "tourism", "value": "aquarium", "tags": ["aquarium", "attraction"]},
    "海遊館": {"class": "tourism", "value": "aquarium", "tags": ["aquarium", "attraction"]},
    "すみだ水族館": {"class": "tourism", "value": "aquarium", "tags": ["aquarium", "attraction"]},
    "サンシャイン水族館": {"class": "tourism", "value": "aquarium", "tags": ["aquarium", "attraction"]},
    "上野動物園": {"class": "tourism", "value": "zoo", "tags": ["zoo", "attraction"]},
    "旭山動物園": {"class": "tourism", "value": "zoo", "tags": ["zoo", "attraction"]},

    # 大学・学校
    "東大": {"class": "amenity", "value": "university", "tags": ["university", "college"]},
    "東京大学": {"class": "amenity", "value": "university", "tags": ["university", "college"]},
    "京大": {"class": "amenity", "value": "university", "tags": ["university", "college"]},
    "京都大学": {"class": "amenity", "value": "university", "tags": ["university", "college"]},
    "慶應": {"class": "amenity", "value": "university", "tags": ["university", "college"]},
    "慶應義塾": {"class": "amenity", "value": "university", "tags": ["university", "college"]},
    "慶應義塾大学": {"class": "amenity", "value": "university", "tags": ["university", "college"]},
    "早稲田": {"class": "amenity", "value": "university", "tags": ["university", "college"]},
    "早稲田大学": {"class": "amenity", "value": "university", "tags": ["university", "college"]},

    # その他公共・インフラ
    "ガソリンスタンド": {"class": "amenity", "value": "fuel", "tags": ["fuel"]},
    "ENEOS": {"class": "amenity", "value": "fuel", "tags": ["fuel"]},
    "エネオス": {"class": "amenity", "value": "fuel", "tags": ["fuel"]},
    "出光": {"class": "amenity", "value": "fuel", "tags": ["fuel"]},
    "アポロステーション": {"class": "amenity", "value": "fuel", "tags": ["fuel"]},
    "コスモ石油": {"class": "amenity", "value": "fuel", "tags": ["fuel"]},
}

# 接尾辞・単語末尾からの地物カテゴリ推定ルール
SUFFIX_RULES = [
    # 寺社・宗教
    (r".*?(?:神社|神宮|大社|八幡宮|天満宮|稲荷)$", "amenity", "place_of_worship", ["place_of_worship", "shrine", "historic"]),
    (r".*?(?:寺|院|大師|薬師)$", "amenity", "place_of_worship", ["place_of_worship", "temple", "historic"]),
    (r".*?(?:教会|チャペル)$", "amenity", "place_of_worship", ["place_of_worship", "church"]),
    # タワー・城・歴史
    (r".*?(?:タワー|塔)$", "man_made", "tower", ["tower", "viewpoint", "attraction"]),
    (r".*?(?:城|城跡|城址)$", "historic", "castle", ["castle", "historic", "attraction"]),
    # 交通
    (r".*?(?:駅|駅前|停留所|ターミナル|バスターミナル)$", "amenity", "bus_station", ["station", "bus_station", "subway_entrance", "platform"]),
    (r".*?(?:空港|飛行場)$", "aeroway", "aerodrome", ["aerodrome", "terminal", "gate"]),
    (r".*?(?:港|フェリー乗り場|フェリーターミナル)$", "amenity", "ferry_terminal", ["ferry_terminal", "harbour"]),
    # 教育
    (r".*?(?:大学|大|大学院|短期大学|短大)$", "amenity", "university", ["university", "college"]),
    (r".*?(?:高校|高等学校|中学|中学校|小学校|学校|校|学園|予備校)$", "amenity", "school", ["school", "college"]),
    (r".*?(?:幼稚園|保育園|こども園)$", "amenity", "kindergarten", ["kindergarten"]),
    # 医療
    (r".*?(?:病院|医院|クリニック|診療所|眼科|歯科|内科|皮膚科|整形外科|耳鼻科)$", "amenity", "hospital", ["hospital", "clinic", "doctors"]),
    (r".*?(?:薬局|ドラッグストア)$", "amenity", "pharmacy", ["pharmacy", "chemist"]),
    # 公共・行政
    (r".*?(?:役所|区役所|市役所|町役場|村役場|都庁|県庁|市庁舎)$", "amenity", "townhall", ["townhall", "courthouse"]),
    (r".*?(?:郵便局|ゆうちょ)$", "amenity", "post_office", ["post_office"]),
    (r".*?(?:警察署|交番|派出所)$", "amenity", "police", ["police"]),
    (r".*?(?:消防署|出張所)$", "amenity", "fire_station", ["fire_station"]),
    (r".*?(?:図書館|図書室)$", "amenity", "library", ["library"]),
    (r".*?(?:銀行|信金|信用金庫|農協|JA)$", "amenity", "bank", ["bank", "atm"]),
    # 文化・娯楽・観光
    (r".*?(?:美術館|博物館|資料館|科学館|記念館|文学館)$", "tourism", "museum", ["museum", "gallery", "attraction"]),
    (r".*?(?:水族館)$", "tourism", "aquarium", ["aquarium", "attraction"]),
    (r".*?(?:動物園)$", "tourism", "zoo", ["zoo", "attraction"]),
    (r".*?(?:公園|庭園|緑地|広場)$", "leisure", "park", ["park", "garden", "pitch"]),
    (r".*?(?:ドーム|スタジアム|球場|競技場|アリーナ|体育館|武道館)$", "leisure", "stadium", ["stadium", "sports_centre", "pitch"]),
    (r".*?(?:映画館|シネマ)$", "amenity", "cinema", ["cinema", "theatre"]),
    (r".*?(?:劇場|ホール|公会堂)$", "amenity", "theatre", ["theatre"]),
    (r".*?(?:温泉|銭湯|サウナ|スパ|健康ランド)$", "leisure", "spa", ["spa", "public_bath", "sauna"]),
    (r".*?(?:ホテル|旅館|イン|民宿|ロッジ)$", "tourism", "hotel", ["hotel", "guest_house", "hostel"]),
    # 商業・飲食
    (r".*?(?:カフェ|喫茶|珈琲|コーヒー)$", "amenity", "cafe", ["cafe"]),
    (r".*?(?:コンビニ|コンビニエンスストア)$", "shop", "convenience", ["convenience", "supermarket"]),
    (r".*?(?:レストラン|食堂|亭|ダイニング|居酒屋|バル|バー)$", "amenity", "restaurant", ["restaurant", "fast_food", "bar", "pub"]),
    (r".*?(?:ラーメン|らーめん|蕎麦|そば|うどん|寿司|鮨|焼肉|中華)$", "amenity", "restaurant", ["restaurant", "fast_food"]),
    (r".*?(?:ベーカリー|パン屋|パン)$", "shop", "bakery", ["bakery", "shop"]),
    (r".*?(?:スーパー|スーパーマーケット|マート)$", "shop", "supermarket", ["supermarket", "convenience"]),
    (r".*?(?:書店|本屋)$", "shop", "books", ["books", "shop"]),
    (r".*?(?:駐車場|コインパーキング|パーキング)$", "amenity", "parking", ["parking"]),
    (r".*?(?:トイレ|お手洗い|公衆トイレ)$", "amenity", "toilets", ["toilets"]),
    (r".*?(?:ガソリンスタンド|給油所)$", "amenity", "fuel", ["fuel"]),
    (r".*?(?:橋|大橋|歩道橋)$", "man_made", "bridge", ["bridge"]),
    (r".*?(?:山|岳|峰|火山)$", "natural", "peak", ["peak", "volcano"]),
    (r".*?(?:川|河川|運河|用水路)$", "natural", "water", ["water", "stream"]),
]


def query_gemini_for_entity(entity_text):
    """
    未知の固有名詞や地物名について、Gemini API を用いて施設種別・OSMタグを推定する
    """
    if not GEMINI_API_KEY:
        return None

    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = (
            f"施設名や地名: 「{entity_text}」について、これが表す施設の種類を英語の一般名詞およびOpenStreetMapのタグ（例: tower, cafe, fast_food, place_of_worship, stadium, museum, park, university, convenience など）で最大3つ、カンマ区切りで出力してください。\n"
            f"出力例: tower, viewpoint, attraction"
        )
        res = model.generate_content(prompt)
        if res.text:
            tags = [t.strip().lower().replace(" ", "_") for t in res.text.strip().split(",") if t.strip()]
            return tags
    except Exception:
        pass
    return None


def resolve_entities_and_keywords(text, doc=None):
    """
    入力テキストから方向詞・疑問詞を除去し、固有名詞や一般名詞を抽出して
    対応するOSMタグ（expanded_tags）を推定・生成する
    """
    resolved_entities = []
    expanded_tags = []
    seen_tags = set()

    # 1. 固有名詞辞書 (BUILTIN_ENTITY_MAP) の走査 (長い名前順)
    for entity_name, data in sorted(BUILTIN_ENTITY_MAP.items(), key=lambda x: -len(x[0])):
        if entity_name in text:
            resolved_entities.append({
                "matched_name": entity_name,
                "source": "knowledge_base",
                "class": data["class"],
                "value": data["value"],
                "tags": data["tags"]
            })
            for t in data["tags"]:
                if t not in seen_tags:
                    seen_tags.add(t)
                    expanded_tags.append(t)

    # 2. GiNZA または形態素トークンの抽出
    nouns = []
    propns = []

    # 方向語・メタ語などの除外ストップワード
    stopwords_ja = {
        "前", "後ろ", "右", "左", "東", "西", "南", "北", "北東", "北西", "南東", "南西",
        "右側", "左側", "前方", "後方", "正面", "目の前", "手前", "側", "方", "方角", "方向",
        "何", "なん", "どこ", "どちら", "名前", "場所", "位置", "辺り", "近く", "周り", "隣",
        "あれ", "これ", "それ", "あそこ", "ここ", "そこ", "やつ", "もの", "建物", "施設"
    }

    if doc is not None:
        for token in doc:
            lemma = token.lemma_ if token.lemma_ else token.text
            if token.pos_ == "PROPN":
                propns.append(token.text)
                if lemma not in stopwords_ja:
                    nouns.append(lemma)
            elif token.pos_ == "NOUN":
                if lemma not in stopwords_ja:
                    nouns.append(lemma)
    else:
        # GiNZAがない場合の簡易抽出
        tokens_raw = re.findall(r'[\u4e00-\u9faf\u3040-\u309f\u30a0-\u30ffA-Za-z0-9]+', text)
        for t in tokens_raw:
            if t not in stopwords_ja and len(t) >= 2:
                nouns.append(t)

    # 3. 接尾辞ルール (SUFFIX_RULES) によるタグ推定
    for word in nouns + propns + [text]:
        for pat, cls, val, tags in SUFFIX_RULES:
            if re.match(pat, word):
                resolved_entities.append({
                    "matched_name": word,
                    "source": "suffix_rule",
                    "class": cls,
                    "value": val,
                    "tags": tags
                })
                for t in tags:
                    if t not in seen_tags:
                        seen_tags.add(t)
                        expanded_tags.append(t)
                break

    # 4. 未知の固有名詞に対する Gemini API フォールバック
    if not expanded_tags and GEMINI_API_KEY:
        target_entity = propns[0] if propns else (nouns[0] if nouns else text)
        gemini_tags = query_gemini_for_entity(target_entity)
        if gemini_tags:
            resolved_entities.append({
                "matched_name": target_entity,
                "source": "gemini_llm_inference",
                "class": "inferred",
                "value": gemini_tags[0],
                "tags": gemini_tags
            })
            for t in gemini_tags:
                if t not in seen_tags:
                    seen_tags.add(t)
                    expanded_tags.append(t)

    # 純粋な地物キーワード（英訳へ渡す用）
    filtered_nouns = [n for n in nouns if n not in stopwords_ja]
    if not filtered_nouns and propns:
        filtered_nouns = propns

    return {
        "resolved_entities": resolved_entities,
        "expanded_tags": expanded_tags,
        "feature_keywords": filtered_nouns
    }


# ==============================================================================
# 4. 英語翻訳 & トークン化
# ==============================================================================

def _translate_google(text, client='gtx', timeout=10):
    """
    Google翻訳 (GTX) エンドポイントで翻訳する。
    429 (レート制限) などのエラー時は例外を送出し、呼び出し側で別プロバイダへフォールバックする。
    """
    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": client,
        "sl": "ja",
        "tl": "en",
        "dt": "t",
        "q": text
    }
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    res = response.json()
    translated_text = "".join([item[0] for item in res[0] if item[0]])
    if translated_text.strip():
        return translated_text.strip()
    return None


def _translate_mymemory(text, timeout=15):
    """
    MyMemory 翻訳APIで翻訳する (Googleが使えない際の代替プロバイダ)。
    """
    url = "https://api.mymemory.translated.net/get"
    params = {
        "q": text,
        "langpair": "ja|en"
    }
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if data.get("responseStatus") != 200:
        return None
    translated = data.get("responseData", {}).get("translatedText")
    if translated and translated.strip():
        return translated.strip()
    return None


def translate_ja_to_en(text):
    """
    日本語テキストを英語に翻訳する関数。

    Google翻訳API (GTX) を第1候補として試し、レート制限(429)やブロック(403)などで
    失敗した場合は、他のGoogleクライアントやMyMemoryなどの代替プロバイダに順次フォールバックする。
    全て失敗した場合はGemini API、最後に入力文字列をそのまま返す。
    """
    providers = [
        ("Google (gtx)", lambda: _translate_google(text, client="gtx")),
        ("Google (dict-chrome-ex)", lambda: _translate_google(text, client="dict-chrome-ex")),
        ("MyMemory", lambda: _translate_mymemory(text)),
    ]

    for name, fn in providers:
        for attempt in range(2):
            try:
                translated_text = fn()
                if translated_text:
                    return translated_text
            except Exception as e:
                print(f"google translate error ({name}): {type(e).__name__}", file=sys.stderr)
                time.sleep(0.5)

    # Gemini API が利用可能な場合のフォールバック
    if GEMINI_API_KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = f"Translate the following Japanese keyword or short phrase to English. Output only the translation: {text}"
            res = model.generate_content(prompt)
            if res.text:
                return res.text.strip()
        except Exception:
            pass

    return text


def lemmatize_word(word):
    """
    英語単語の簡易単数形化 (lemmatization) 処理
    """
    exceptions = {
        'cafes': 'cafe',
        'buses': 'bus',
        'glasses': 'glass',
        'clothes': 'clothes',
    }
    if word in exceptions:
        return exceptions[word]

    if word.endswith('ies') and len(word) > 4:
        return word[:-3] + 'y'
    elif word.endswith(('shes', 'ches', 'xes', 'zes', 'sses')):
        return word[:-2]
    elif word.endswith('ves') and len(word) > 4:
        return word[:-3] + 'f'
    elif word.endswith('es') and len(word) > 3:
        return word[:-1]
    elif word.endswith('s') and not word.endswith('ss') and len(word) > 3:
        return word[:-1]
    return word


def tokenize_and_normalize(text, additional_tags=None):
    """
    英文テキストおよび推定OSMタグを単語ごとに分割・正規化する
    """
    raw_tokens = re.findall(r'\b[a-zA-Z0-9_-]+\b', text.lower())
    if additional_tags:
        for tag in additional_tags:
            for sub_tag in tag.lower().replace("_", " ").split():
                if sub_tag not in raw_tokens:
                    raw_tokens.append(sub_tag)

    stopwords = {
        'a', 'an', 'the', 'and', 'or', 'but', 'is', 'are', 'was', 'were',
        'in', 'on', 'at', 'to', 'for', 'with', 'by', 'about', 'against',
        'between', 'into', 'through', 'during', 'before', 'after', 'above',
        'below', 'from', 'up', 'down', 'of', 'off', 'over', 'under', 'again',
        'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why',
        'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other',
        'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so',
        'than', 'too', 'very', 's', 't', 'can', 'will', 'just', 'don',
        'should', 'now', 'i', 'want', 'look', 'looking', 'find', 'search', 'please',
        'right', 'left', 'front', 'back', 'east', 'west', 'south', 'north'
    }

    tokens = []
    for token in raw_tokens:
        clean_token = token.replace('_', ' ').strip()
        for sub_w in clean_token.split():
            if sub_w in stopwords and len(raw_tokens) > 1:
                continue
            lemma = lemmatize_word(sub_w)
            tokens.append((sub_w, lemma))

    return tokens if tokens else [(t, t) for t in raw_tokens]


# ==============================================================================
# 5. 類似度計算エンジン (difflib / word2vec)
# ==============================================================================

def calculate_similarity_difflib(token_info_list, value, expanded_tags=None):
    """
    difflib.SequenceMatcher による文字列類似度計算 (推定タグ考慮版)
    """
    value_clean = value.lower()
    value_words = value_clean.replace('_', ' ').replace('-', ' ').split()
    value_display = value_clean.replace('_', ' ')

    best_score = 0.0
    best_matched_token = ""
    best_detail = ""

    # 推定タグとの直接完全一致チェック (最優先)
    if expanded_tags:
        for tag in expanded_tags:
            tag_clean = tag.lower().replace('-', '_')
            if tag_clean == value_clean:
                return 1.0, tag, f"固有名詞/カテゴリ推定タグ完全一致 ('{tag}')"
            if tag_clean in value_words:
                return 0.96, tag, f"推定タグ構成語一致 ('{tag}' in '{value_display}')"

    for orig_token, lemma_token in token_info_list:
        scores = []

        # 1. 完全一致
        if lemma_token == value_clean or orig_token == value_clean or lemma_token == value_display or orig_token == value_display:
            scores.append((1.0, f"完全一致 ('{orig_token}')"))

        # 2. 単語完全一致
        elif lemma_token in value_words or orig_token in value_words:
            scores.append((0.95, f"単語一致 ('{orig_token}' in '{value_display}')"))

        # 3. 前方一致 / サブストリング一致
        elif len(lemma_token) >= 3 and value_clean.startswith(lemma_token):
            score = 0.88 * (len(lemma_token) / len(value_clean))
            scores.append((score, f"前方一致 ('{lemma_token}' in '{value_clean}')"))
        elif len(lemma_token) >= 3 and lemma_token in value_clean:
            score = 0.82 * (len(lemma_token) / len(value_clean))
            scores.append((score, f"部分一致 ('{lemma_token}' in '{value_clean}')"))
        elif len(value_clean) >= 3 and value_clean in lemma_token:
            score = 0.80 * (len(value_clean) / len(lemma_token))
            scores.append((score, f"部分一致 ('{value_clean}' in '{lemma_token}')"))

        # 4. difflib SequenceMatcher
        sim_full = difflib.SequenceMatcher(None, lemma_token, value_clean).ratio()
        scores.append((sim_full * 0.85, f"SequenceMatcher 類似度 ({sim_full:.2f})"))

        for vw in value_words:
            sim_word = difflib.SequenceMatcher(None, lemma_token, vw).ratio()
            scores.append((sim_word * 0.85, f"SequenceMatcher 単語類似度 ('{lemma_token}' vs '{vw}': {sim_word:.2f})"))

        token_best_score, token_best_detail = max(scores, key=lambda x: x[0])
        if token_best_score > best_score:
            best_score = token_best_score
            best_matched_token = orig_token
            best_detail = token_best_detail

    return best_score, best_matched_token, best_detail


def calculate_similarity_word2vec(token_info_list, value, model, expanded_tags=None):
    """
    Word2Vec によるベクトル類似度計算 (推定タグ考慮版)
    """
    value_clean = value.lower()
    value_words = value_clean.replace('_', ' ').replace('-', ' ').split()
    value_display = value_clean.replace('_', ' ')

    best_score = 0.0
    best_matched_token = ""
    best_detail = ""

    # 推定タグとの直接一致チェック
    if expanded_tags:
        for tag in expanded_tags:
            tag_clean = tag.lower().replace('-', '_')
            if tag_clean == value_clean:
                return 1.0, tag, f"固有名詞/カテゴリ推定タグ完全一致 ('{tag}')"
            if tag_clean in value_words:
                return 0.96, tag, f"推定タグ構成語一致 ('{tag}' in '{value_display}')"

    for orig_token, lemma_token in token_info_list:
        scores = []
        target_words = [lemma_token, orig_token]

        for w in target_words:
            # 1. 完全一致
            if w == value_clean or w == value_display:
                scores.append((1.0, f"完全一致 ('{orig_token}')"))
                continue
            if w in value_words:
                scores.append((0.95, f"単語一致 ('{orig_token}' in '{value_display}')"))
                continue

            # 2. Word2Vec ベクトル類似度計算
            if w in model.key_to_index:
                for vw in value_words:
                    if vw in model.key_to_index:
                        cos_sim = float(model.similarity(w, vw))
                        score = max(0.0, cos_sim)
                        scores.append((score, f"Word2Vec コサイン類似度 ('{w}' vs '{vw}': {cos_sim:.4f})"))
                    else:
                        if w in vw or vw in w:
                            scores.append((0.75, f"部分単語一致 ('{w}' & '{vw}')"))

                if value_clean in model.key_to_index:
                    cos_sim_full = float(model.similarity(w, value_clean))
                    score_full = max(0.0, cos_sim_full)
                    scores.append((score_full, f"Word2Vec 全体類似度 ('{w}' vs '{value_clean}': {cos_sim_full:.4f})"))
            else:
                # 語彙に存在しない場合は SequenceMatcher にフォールバック
                sim_fallback = difflib.SequenceMatcher(None, w, value_clean).ratio()
                scores.append((sim_fallback * 0.7, f"フォールバック類似度 ('{w}' vs '{value_clean}': {sim_fallback:.2f})"))

        if scores:
            token_best_score, token_best_detail = max(scores, key=lambda x: x[0])
            if token_best_score > best_score:
                best_score = token_best_score
                best_matched_token = orig_token
                best_detail = token_best_detail

    return best_score, best_matched_token, best_detail


# ==============================================================================
# 6. 自然文の統合解析 & MapFeatures 類似度検索
# ==============================================================================

def analyze_and_search(input_text, method='difflib', use_ginza=True, csv_path='mapfeatures.csv', top_k=10):
    """
    自然文を受け取り、方向分類・質問分類・固有名詞解決・MapFeatures類似度検索を一括実行して結果を返す
    """
    csv_file_path = os.path.join(os.path.dirname(__file__), csv_path) if not os.path.isabs(csv_path) else csv_path
    if not os.path.exists(csv_file_path):
        raise FileNotFoundError(f"CSVファイル '{csv_file_path}' が見つかりません。")

    # 1. 方向 (前後左右、方角) の抽出
    directions = extract_directions(input_text)

    # 2. 質問タイプ (なんですか？, どこですか？など) の分類
    intent_info = classify_question_intent(input_text)

    # 3. GiNZA NLP による構文解析 (有効時)
    doc = None
    if use_ginza:
        nlp = get_ginza_nlp()
        if nlp:
            try:
                doc = nlp(input_text)
            except Exception as e:
                print(f"[警告] GiNZA解析中にエラーが発生しました: {e}")

    # 4. 固有名詞の解決 & OSMタグ推定
    entity_result = resolve_entities_and_keywords(input_text, doc=doc)
    resolved_entities = entity_result["resolved_entities"]
    expanded_tags = entity_result["expanded_tags"]
    feature_keywords = entity_result["feature_keywords"]

    # 5. 英語への翻訳とトークン化
    # 翻訳対象テキスト: 抽出された地物キーワード（無ければ全体）
    target_translate_text = " ".join(feature_keywords) if feature_keywords else input_text
    translated_text = translate_ja_to_en(target_translate_text)

    # トークン化（推定タグも統合）
    tokens = tokenize_and_normalize(translated_text, additional_tags=expanded_tags)

    # 6. 類似度計算
    w2v_model = None
    if method == 'word2vec':
        w2v_model = get_word2vec_model()

    features = []
    with open(csv_file_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cls = row.get('class', '').strip()
            val = row.get('value', '').strip()
            if cls and val:
                features.append((cls, val))

    results = []
    seen = set()

    for cls, val in features:
        if (cls, val) in seen:
            continue
        seen.add((cls, val))

        if method == 'word2vec':
            score, matched_token, detail = calculate_similarity_word2vec(tokens, val, w2v_model, expanded_tags=expanded_tags)
        else:
            score, matched_token, detail = calculate_similarity_difflib(tokens, val, expanded_tags=expanded_tags)

        results.append({
            'class': cls,
            'value': val,
            'score': score,
            'matched_token': matched_token,
            'detail': detail
        })

    # 類似度順にソート
    results.sort(key=lambda x: (x['score'], x['class'], x['value']), reverse=True)
    top_results = results[:top_k]

    return {
        "input_text": input_text,
        "analysis": {
            "directions": directions,
            "intent": intent_info,
            "resolved_entities": resolved_entities,
            "expanded_tags": expanded_tags,
            "feature_keywords": feature_keywords,
            "translated_en": translated_text,
            "tokens": [t[0] for t in tokens],
        },
        "method": method,
        "top_results": top_results
    }


def print_formatted_results(analysis_data, top_k=10):
    """
    解析結果およびMapFeatures類似度トップランキングをコンソールに分かりやすく整形表示する
    """
    input_text = analysis_data["input_text"]
    analysis = analysis_data["analysis"]
    method = analysis_data["method"]
    top_results = analysis_data["top_results"]

    print("=" * 80)
    print(f"【入力文章】: {input_text}")
    print("=" * 80)

    # 1. 方向抽出結果
    dirs = analysis["directions"]
    print("■ [1] 方向・方角の抽出結果:")
    if dirs:
        for d in dirs:
            if d["category"] == "relative":
                print(f"  ・ 相対方向 : {d['name']} (コマンド: '{d['command']}', 基準ベクトル: {d['vector']}, マッチ: '{d['matched']}')")
            else:
                print(f"  ・ 絶対方角 : {d['name']} {d.get('symbol', '')} (方角ベクトル: {d['vector']}, マッチ: '{d['matched']}')")
    else:
        print("  ・ 方向・方角の指定なし")

    # 2. 質問タイプ分類結果
    intent = analysis["intent"]
    print(f"\n■ [2] 質問タイプの分類結果:")
    print(f"  ・ インテント : {intent['intent']} ({intent['name']})")
    print(f"  ・ 説明       : {intent['description']}")
    if intent["matched"]:
        print(f"  ・ 検出表現   : '{intent['matched']}'")

    # 3. 固有名詞・地物抽出 & OSMタグ解決結果
    print(f"\n■ [3] 固有名詞解決 & OSMタグ推定 (改善機能):")
    resolved = analysis["resolved_entities"]
    if resolved:
        for r in resolved:
            print(f"  ・ 検出固有名詞/施設 : '{r['matched_name']}' (ソース: {r['source']}) => Class: {r['class']}, Value: {r['value']}")
    else:
        print("  ・ 登録固有名詞の直接一致なし")

    if analysis["expanded_tags"]:
        print(f"  ・ 推定されたOSMタグ群: {', '.join(analysis['expanded_tags'])}")
    if analysis["feature_keywords"]:
        print(f"  ・ 抽出地物キーワード : {', '.join(analysis['feature_keywords'])}")

    print(f"  ・ 英訳 (Translation) : {analysis['translated_en']}")
    print(f"  ・ 解析トークン一覧   : {analysis['tokens']}")

    # 4. 類似度検索結果
    print("-" * 80)
    print(f"■ [4] mapfeatures.csv との類似度 トップ {len(top_results)} (手法: {method.upper()}):")
    print(f"{'順位':<4} | {'類似度':<8} | {'Class':<15} | {'Value':<25} | {'マッチ詳細'}")
    print("-" * 80)

    for idx, item in enumerate(top_results, 1):
        score_str = f"{item['score']:.4f}"
        print(f"{idx:<4} | {score_str:<8} | {item['class']:<15} | {item['value']:<25} | Token: '{item['matched_token']}' ({item['detail']})")
    print("=" * 80 + "\n")


# ==============================================================================
# 7. メイン関数 & CLI エントリーポイント
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="自然文から方向・質問タイプ分類 & 固有名詞対応 MapFeatures 類似度検索プログラム v2")
    parser.add_argument("text", nargs="*", default=None, help="検索する入力テキスト (日本語)")
    parser.add_argument("-m", "--method", choices=["difflib", "word2vec"], default=None,
                        help="類似度計算の手法を選択 (difflib または word2vec)")
    parser.add_argument("-g", "--ginza", action="store_true", default=True,
                        help="GiNZA を用いた形態素・構文解析を有効にする (デフォルト: ON)")
    parser.add_argument("--no-ginza", action="store_false", dest="ginza",
                        help="GiNZA 解析を無効にして軽量ルールベースのみで動作する")
    parser.add_argument("-t", "--top", type=int, default=10, help="表示する上位件数 (デフォルト: 10)")
    parser.add_argument("--json", action="store_true", default=False, help="結果をJSON形式で出力する")

    args = parser.parse_args()

    # 入力テキストの結合
    input_text = " ".join(args.text) if args.text else None

    # 対話式プロンプト（引数が未指定の場合）
    if not input_text and not args.json:
        print("\n" + "=" * 80)
        print("  MapFeatures 自然文解析 & 類似度検索ツール v2")
        print("  (方向分類・質問分類・固有名詞/建物名OSMタグ対応)")
        print("=" * 80)

    method = args.method
    if not method and not args.json:
        print("\n類似度計算アルゴリズムの手法を選択してください:")
        print("  1. difflib  (difflib.SequenceMatcher による文字列類似度 - 高速)")
        print("  2. word2vec (Word2Vec 単語分散表現による意味的類似度)")
        try:
            choice = input("選択してください [1/2] (デフォルト: 1): ").strip()
            if choice == "2" or choice.lower() == "word2vec":
                method = "word2vec"
            else:
                method = "difflib"
        except (EOFError, KeyboardInterrupt):
            method = "difflib"
    elif not method:
        method = "difflib"

    if not input_text:
        try:
            input_text = input("\n検索文章を入力してください\n(例: 右側にあるスカイツリーはなんですか？ / 北東にあるスタバはどこですか？): ").strip()
        except (EOFError, KeyboardInterrupt):
            input_text = "右側にあるスカイツリーはなんですか？"

    if not input_text:
        input_text = "右側にあるスカイツリーはなんですか？"

    # 解析と検索の実行
    result_data = analyze_and_search(
        input_text,
        method=method,
        use_ginza=args.ginza,
        top_k=args.top
    )

    if args.json:
        print(json.dumps(result_data, ensure_ascii=False, indent=2))
    else:
        print_formatted_results(result_data, top_k=args.top)


if __name__ == "__main__":
    main()
