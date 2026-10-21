# -*- coding: utf-8 -*-
"""
FastAPI バックエンドエントリポイント

フロントエンドからの自然文質問と位置情報を受け取り、
LLM とジオコーディングを使って建物を特定し、案内回答を返す。
"""

import math
import os
import re
import sys
from typing import Optional

import requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(__file__))

from feature_tags import collect_search_tags, is_high_building
from llm_qa import AUDIO_DIR, answer_question, ask_llm
from searchsynonyms_mapfeatures_v2 import analyze_and_search
from transcribe import TranscriptionError, transcribe_bytes

app = FastAPI(title="屋外ナビアシスタント API", version="0.1.0")

# CORS: 開発中はフロントエンド開発サーバーからのリクエストを許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# リクエスト・レスポンスモデル
# ==============================================================================

class AnalyzeRequest(BaseModel):
    text: str = Field(..., description="解析する自然文")
    method: str = Field("difflib", description="類似度手法 (difflib / word2vec)")
    top_k: int = Field(10, description="返す上位件数")


class AskRequest(BaseModel):
    question: str = Field(..., description="ユーザーの質問文")
    latitude: Optional[float] = Field(None, description="現在地の緯度")
    longitude: Optional[float] = Field(None, description="現在地の経度")
    facing: Optional[str] = Field(None, description="向いている方角")
    generate_audio: bool = Field(False, description="回答音声を生成するか")


class AnalyzeResponse(BaseModel):
    input_text: str
    analysis: dict
    method: str
    top_results: list


class AskResponse(BaseModel):
    question: str
    answer: str
    audio_path: Optional[str]
    analysis: dict
    found_target: Optional[dict]


# ==============================================================================
# ジオコーディング・建物検索補助関数
# ==============================================================================

EARTH_RADIUS_M = 6371000


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2点間の距離（メートル）を返す。"""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """点1から点2への方角（度数、北=0, 東=90）を返す。"""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def vector_to_cardinal(bearing: float) -> str:
    """方角を8方位の日本語表現に変換する。"""
    directions = ["北", "北東", "東", "南東", "南", "南西", "西", "北西"]
    idx = round(bearing / 45) % 8
    return directions[idx]


def nominatim_search(query: str, lat: Optional[float] = None, lon: Optional[float] = None) -> Optional[dict]:
    """
    Nominatim で施設・地名を検索する。
    現在地が与えられた場合は近傍を優先するため viewbox を付与する。
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": query,
        "format": "json",
        "limit": "5",
        "addressdetails": "1",
        "accept-language": "ja",
    }
    if lat is not None and lon is not None:
        delta = 0.05
        params["viewbox"] = f"{lon - delta},{lat + delta},{lon + delta},{lat - delta}"
        params["bounded"] = "0"

    headers = {"User-Agent": "gps-buildings-info/0.1 (contact@example.com)"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None
        return data[0]
    except Exception as e:
        print(f"[Nominatim error] {e}", file=sys.stderr)
        return None


# ==============================================================================
# Overpass API による周辺 POI 検索・候補ランキング
# ==============================================================================

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_RADIUS_M = 500

# 候補の osm_class として優先的に使う OSM キー
OSM_CLASS_KEYS = (
    "amenity", "shop", "tourism", "building", "man_made", "leisure",
    "office", "historic", "highway", "railway",
)

# 8方位（北から時計回り）
CARDINAL_ORDER = ["north", "northeast", "east", "southeast",
                  "south", "southwest", "west", "northwest"]

# facing（進行方向）→ 方位角。英語キーと日本語表記の両方を受け付ける。
FACING_BEARINGS = {
    "north": 0, "northeast": 45, "east": 90, "southeast": 135,
    "south": 180, "southwest": 225, "west": 270, "northwest": 315,
    "北": 0, "北東": 45, "東": 90, "南東": 135,
    "南": 180, "南西": 225, "西": 270, "北西": 315,
}

# 進行方向を基準にした相対方位（前方から時計回り）
RELATIVE_ORDER = [
    "front", "front_right", "right", "back_right",
    "back", "back_left", "left", "front_left",
]

_TAG_KEY_RE = re.compile(r"^[A-Za-z0-9_:]+$")
_TAG_VALUE_RE = re.compile(r"^[A-Za-z0-9_:.\-]+$")


def _overpass_tag_filter(tag: str) -> Optional[str]:
    """``amenity=cafe`` / ``building`` を Overpass QL のフィルタに変換する。"""
    if not isinstance(tag, str):
        return None
    tag = tag.strip()
    if not tag:
        return None

    if "=" in tag:
        key, value = (part.strip() for part in tag.split("=", 1))
        if not _TAG_KEY_RE.match(key) or not _TAG_VALUE_RE.match(value):
            return None
        return f'["{key}"="{value}"]'

    if not _TAG_KEY_RE.match(tag):
        return None
    return f'["{tag}"]'


def overpass_search(
    lat: float,
    lon: float,
    tags,
    radius: int = OVERPASS_RADIUS_M,
) -> list:
    """
    現在地周辺の POI を Overpass API で検索する。

    :param tags: ``["amenity=cafe", "building"]`` のような OSM タグ候補
    :return: 候補 dict のリスト（距離・方位つき）。失敗時は空リスト。
    """
    filters = []
    seen = set()
    for tag in tags or []:
        f = _overpass_tag_filter(tag)
        if f and f not in seen:
            seen.add(f)
            filters.append(f)

    if not filters:
        return []

    # クエリが大きくなりすぎないよう最大 4 タグまで
    parts = []
    for f in filters[:4]:
        for element in ("node", "way", "relation"):
            parts.append(f"{element}{f}(around:{int(radius)},{lat},{lon});")

    query = f"[out:json][timeout:20];({''.join(parts)});out center tags;"
    headers = {"User-Agent": "gps-buildings-info/0.1 (contact@example.com)"}

    try:
        resp = requests.post(
            OVERPASS_URL, data={"data": query}, headers=headers, timeout=25
        )
        resp.raise_for_status()
        elements = resp.json().get("elements", [])
    except Exception as e:
        print(f"[Overpass error] {e}", file=sys.stderr)
        return []

    candidates = []
    for element in elements:
        tags_dict = element.get("tags") or {}
        center = element.get("center") or {}
        el_lat = element.get("lat", center.get("lat"))
        el_lon = element.get("lon", center.get("lon"))
        if el_lat is None or el_lon is None:
            continue

        el_lat, el_lon = float(el_lat), float(el_lon)
        distance = round(haversine(lat, lon, el_lat, el_lon))
        bearing = round(calculate_bearing(lat, lon, el_lat, el_lon))

        osm_class = "不明"
        for key in OSM_CLASS_KEYS:
            if tags_dict.get(key):
                osm_class = key
                break
        osm_type = tags_dict.get(osm_class, element.get("type", "不明"))

        candidates.append({
            "name": tags_dict.get("name") or tags_dict.get("name:ja") or "名称不明の施設",
            "latitude": el_lat,
            "longitude": el_lon,
            "osm_class": osm_class,
            "osm_type": osm_type,
            "is_high_building": is_high_building(osm_class, osm_type),
            "distance_meters": distance,
            "bearing": bearing,
            "vector_name": vector_to_cardinal(bearing),
            "display_name": tags_dict.get("name") or "",
            "tags": tags_dict,
            "height": tags_dict.get("height"),
            "building_levels": tags_dict.get("building:levels"),
            "start_date": tags_dict.get("start_date") or tags_dict.get("year"),
        })

    return candidates


def _parse_facing(facing: Optional[str]) -> Optional[float]:
    """facing 文字列を方位角に変換する。不明なら None。"""
    if not facing:
        return None
    return FACING_BEARINGS.get(facing.strip().lower())


def _direction_match_score(bearing: float, analysis: dict, facing: Optional[str]) -> float:
    """
    質問中の方向表現と候補の方位が一致するかを 0.0〜1.0 で返す。

    - 方向指定がない: 0.5（中立）
    - 一致する: 1.0
    - 一致しない: 0.0
    - 相対方向だが facing が無く判定できない: 0.5
    """
    directions = analysis.get("directions") or []
    if not directions:
        return 0.5

    facing_bearing = _parse_facing(facing)
    candidate_cardinal = CARDINAL_ORDER[round(bearing / 45) % 8]

    evaluable = False
    matched = False
    for direction in directions:
        key = direction.get("key")
        if direction.get("category") == "cardinal":
            evaluable = True
            if key == candidate_cardinal:
                matched = True
        elif direction.get("category") == "relative" and facing_bearing is not None:
            evaluable = True
            relative = (bearing - facing_bearing + 360) % 360
            relative_key = RELATIVE_ORDER[round(relative / 45) % 8]
            if key == relative_key:
                matched = True

    if not evaluable:
        return 0.5
    return 1.0 if matched else 0.0


def _tag_match_score(candidate: dict, analysis: dict) -> float:
    """候補のタグ・名称が解析結果のタグ候補/キーワードにどれだけ一致するか。"""
    tags = candidate.get("tags") or {}
    expanded_tags = [t for t in (analysis.get("expanded_tags") or []) if isinstance(t, str) and "=" in t]

    tag_score = 0.0
    if expanded_tags:
        matches = 0
        for tag in expanded_tags:
            key, value = tag.split("=", 1)
            if str(tags.get(key.strip(), "")) == value.strip():
                matches += 1
        tag_score = matches / len(expanded_tags)

    name = candidate.get("name") or ""
    keywords = analysis.get("feature_keywords") or []
    name_score = 1.0 if any(kw and kw in name for kw in keywords) else 0.0

    return max(tag_score, name_score)


def rank_candidates(
    candidates: list,
    analysis: dict,
    facing: Optional[str] = None,
    radius: int = OVERPASS_RADIUS_M,
) -> list:
    """
    候補を「タグ一致度・近さ・方位一致度」でランキングする。

    score = 0.40 * タグ一致 + 0.35 * 近さ + 0.25 * 方位一致
    """
    ranked = []
    for candidate in candidates:
        distance = candidate.get("distance_meters") or 0
        proximity = max(0.0, 1.0 - distance / radius)
        tag_score = _tag_match_score(candidate, analysis)
        direction_score = _direction_match_score(
            candidate.get("bearing") or 0.0, analysis, facing
        )

        enriched = dict(candidate)
        enriched["tag_score"] = round(tag_score, 3)
        enriched["direction_score"] = round(direction_score, 3)
        enriched["score"] = round(
            0.40 * tag_score + 0.35 * proximity + 0.25 * direction_score, 3
        )
        ranked.append(enriched)

    ranked.sort(key=lambda c: (c["score"], -c.get("distance_meters", 0)), reverse=True)
    return ranked


def build_geolocate_result(
    question: str,
    analysis: dict,
    lat: Optional[float],
    lon: Optional[float],
    facing: Optional[str] = None,
    top_results: Optional[list] = None,
):
    """
    解析結果と位置情報から、llm_qa に渡せる geolocate_result 形式の dict を構築する。

    1. 固有名詞・キーワードがあれば Nominatim で検索する
    2. Nominatim で見つからない場合は、現在地周辺を Overpass API で検索し、
       タグ一致度・近さ・方位一致度で候補をランキングする

    Overpass 検索に使うタグは `feature_tags.collect_search_tags` で
    `expanded_tags` / `mapfeatures.csv` の類似度結果 / `high_buildings.csv` を
    統合したものを用いる（詳細は同モジュールの docstring を参照）。
    """
    resolved_entities = analysis.get("resolved_entities", [])
    expanded_tags = analysis.get("expanded_tags", [])
    feature_keywords = analysis.get("feature_keywords", [])
    search_tags = collect_search_tags(analysis, top_results=top_results)

    # 検索クエリの決定
    search_query = None
    if resolved_entities:
        search_query = resolved_entities[0].get("matched_name", "")
    elif feature_keywords:
        search_query = " ".join(feature_keywords[:3])
    elif expanded_tags:
        search_query = expanded_tags[0].replace("_", " ")

    candidates = []
    found_target = None
    status = "not_found"

    if search_query:
        nominatim_result = nominatim_search(search_query, lat=lat, lon=lon)
        if nominatim_result:
            try:
                target_lat = float(nominatim_result.get("lat", 0))
                target_lon = float(nominatim_result.get("lon", 0))
                distance = None
                bearing = None
                vector_name = None
                if lat is not None and lon is not None:
                    distance = round(haversine(lat, lon, target_lat, target_lon))
                    bearing = round(calculate_bearing(lat, lon, target_lat, target_lon))
                    vector_name = vector_to_cardinal(bearing)

                found_target = {
                    "name": nominatim_result.get("display_name", "不明").split(",")[0],
                    "latitude": target_lat,
                    "longitude": target_lon,
                    "osm_class": nominatim_result.get("class", "不明"),
                    "osm_type": nominatim_result.get("type", "不明"),
                    "distance_meters": distance,
                    "bearing": bearing,
                    "vector_name": vector_name,
                    "display_name": nominatim_result.get("display_name", "不明"),
                    "tags": nominatim_result,
                }
                candidates.append(found_target)
                status = "geocode_success"
            except Exception as e:
                print(f"[geocode parse error] {e}", file=sys.stderr)

    # Nominatim で見つからない場合は、現在地周辺を Overpass で検索する
    if found_target is None and lat is not None and lon is not None and search_tags:
        overpass_candidates = overpass_search(lat, lon, search_tags)
        if overpass_candidates:
            candidates = rank_candidates(overpass_candidates, analysis, facing=facing)
            found_target = candidates[0]
            status = "overpass_success"

    return {
        "status": status,
        "found_target": found_target,
        "candidates": candidates,
        "analysis": analysis,
        "input_text": question,
        "search_tags": search_tags,
    }


# ==============================================================================
# エンドポイント
# ==============================================================================

@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze_text(request: AnalyzeRequest):
    """
    自然文から方向・疑問意図・固有名詞・OSMタグ候補を解析する。
    """
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="text が空です")

    try:
        result = analyze_and_search(
            request.text,
            method=request.method,
            use_ginza=False,  # APIレスポンスを軽くするため GiNZA は無効化
            top_k=request.top_k,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析に失敗しました: {e}")


@app.post("/api/ask", response_model=AskResponse)
def ask(request: AskRequest):
    """
    質問文と現在地を受け取り、LLM で回答を生成する。
    """
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="question が空です")

    try:
        analysis = analyze_and_search(
            request.question,
            method="difflib",
            use_ginza=False,
            top_k=5,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"テキスト解析に失敗しました: {e}")

    geolocate_result = build_geolocate_result(
        request.question,
        analysis["analysis"],
        lat=request.latitude,
        lon=request.longitude,
        facing=request.facing,
        top_results=analysis.get("top_results"),
    )

    current_location = None
    if request.latitude is not None and request.longitude is not None:
        current_location = (request.latitude, request.longitude)

    try:
        llm_result = answer_question(
            geolocate_result=geolocate_result,
            question=request.question,
            current_location=current_location,
            facing=request.facing,
            generate_audio=request.generate_audio,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"回答生成に失敗しました: {e}")

    audio_path = llm_result.get("audio_path")
    audio_url = f"/api/audio/{os.path.basename(audio_path)}" if audio_path else None

    return {
        "question": request.question,
        "answer": llm_result["answer"],
        "audio_path": audio_url,
        "analysis": analysis["analysis"],
        "found_target": geolocate_result.get("found_target"),
    }


# ==============================================================================
# 音声入力・音声応答
# ==============================================================================

MAX_AUDIO_UPLOAD_BYTES = 15 * 1024 * 1024  # 15MB


class TranscribeResponse(BaseModel):
    text: str
    language: str


@app.post("/api/transcribe", response_model=TranscribeResponse)
async def transcribe(
    file: UploadFile = File(..., description="文字起こしする音声ファイル (wav/webm/ogg/mp3 など)"),
    language: str = "ja-JP",
):
    """
    アップロードされた音声ファイルを文字起こししてテキストを返す。

    WAV は標準ライブラリで解析し、それ以外の形式は ffmpeg で変換する。
    ブラウザの MediaRecorder が生成する webm/ogg にも対応する。
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="音声ファイルが空です")
    if len(data) > MAX_AUDIO_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="音声ファイルが大きすぎます")

    try:
        text = transcribe_bytes(data, language=language, filename=file.filename)
    except TranscriptionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文字起こしに失敗しました: {e}")

    return {"text": text, "language": language}


@app.get("/api/audio/{filename}")
def get_audio(filename: str):
    """生成済みの音声ファイルを配信する。"""
    # パストラバーサル対策: 単純なファイル名のみ許可する
    if filename != os.path.basename(filename) or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="不正なファイル名です")

    base_dir = os.path.realpath(AUDIO_DIR)
    audio_path = os.path.realpath(os.path.join(base_dir, filename))
    if not audio_path.startswith(base_dir + os.sep) or not os.path.isfile(audio_path):
        raise HTTPException(status_code=404, detail="音声ファイルが見つかりません")

    media_type = "audio/mpeg" if filename.lower().endswith(".mp3") else "application/octet-stream"
    return FileResponse(audio_path, media_type=media_type, filename=filename)


class LlmOnlyRequest(BaseModel):
    prompt: str = Field(..., description="LLM に送信するプロンプト")
    model: Optional[str] = Field(None, description="使用するモデル名（未指定時はプロバイダの既定値）")


class LlmOnlyResponse(BaseModel):
    prompt: str
    answer: str


@app.post("/api/ask-llm-only", response_model=LlmOnlyResponse)
def ask_llm_only(request: LlmOnlyRequest):
    """
    プロンプトをそのまま LLM に送信し、回答のみを返す（ジオコーディングなし）。

    プロバイダは `GEMINI_API_KEY` → `OPENAI_API_KEY` の順で自動選択される。
    """
    if not request.prompt or not request.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt が空です")

    try:
        answer = ask_llm(request.prompt, model=request.model)
        return {"prompt": request.prompt, "answer": answer}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM API 呼び出しに失敗しました: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
