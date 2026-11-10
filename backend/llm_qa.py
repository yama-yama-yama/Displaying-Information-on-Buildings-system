# -*- coding: utf-8 -*-
"""
LLM 連携 QA モジュール (llm_qa.py)

geolocate_step_serch.py の探索結果（建物名・座標・属性・周辺データ）と
ユーザーの質問文を受け取り、LLM で回答を生成する。
必要に応じて gTTS で回答テキストを mp3 音声ファイルに変換する。

LLM プロバイダは次の優先順位で自動選択する:
1. 環境変数 `GEMINI_API_KEY`（または後方互換の `api_KEY.txt`）→ Gemini API
2. 環境変数 `OPENAI_API_KEY` → OpenAI 互換 API
   （`OPENAI_BASE_URL` / `OPENAI_MODEL` で接続先とモデルを指定可能）

Web 検索は既定で有効。OpenAI 互換 API では Responses API の
`tools=[{"type": "web_search"}]` を使い、Gemini では Google Search
グラウンディングを使う。`LLM_WEB_SEARCH=0` で無効化できる。
"""

import argparse
import json
import os
import sys
import uuid

import requests
from gtts import gTTS

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

DEFAULT_API_KEY_PATH = os.path.join(os.path.dirname(__file__), "api_KEY.txt")
# 後方互換のためモジュール読み込み時点の環境変数も保持する（実処理では load_gemini_api_key を使う）
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DEFAULT_MODEL = "gemini-3.8-flash"

# OpenAI 互換 API の既定値（OPENAI_BASE_URL / OPENAI_MODEL で上書き可能）
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_TIMEOUT = 60

# Web 検索ツール。LLM_WEB_SEARCH=0/false/off で無効化できる。
WEB_SEARCH_TOOL = {"type": "web_search"}
WEB_SEARCH_ENV = "LLM_WEB_SEARCH"

DEFAULT_AUDIO_PATH = "answer.mp3"
# 生成した mp3 を保存するディレクトリ（GET /api/audio/{filename} から配信する）
AUDIO_DIR = os.path.join(os.path.dirname(__file__), "audio")


SYSTEM_PROMPT = """あなたは屋外ナビゲーションアシスタントです。
以下の情報をもとに、ユーザーの質問に対して日本語で簡潔かつ親しみやすく回答してください。

【回答のルール】
- 建物名や目的の施設が分かっている場合は、まずそれを明示してください。
- 現在地からの方角とおよその距離を、ユーザーがイメージしやすい言葉で伝えてください。
- 周辺の目印（交差点、駅、看板、他の店舗など）が分かれば加えてください。
- 不確かな情報は「おそらく」「〜の可能性があります」などとし、誤った確信を持って伝えないでください。
- 回答は 3〜5 文程度にまとめ、長すぎないようにしてください。
"""


def load_gemini_api_key(path=DEFAULT_API_KEY_PATH):
    """
    Gemini API キーを取得する。

    優先順位:
    1. 環境変数 GEMINI_API_KEY
    2. api_KEY.txt（`DEFAULT_API_KEY_PATH`、存在する場合）

    :return: API キー文字列。見つからなければ None。
    """
    env_key = os.getenv("GEMINI_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                key = f.read().strip()
            return key or None
        except Exception:
            return None
    return None


def load_openai_config():
    """
    OpenAI 互換 API の接続設定を環境変数から読み込む。

    - `OPENAI_API_KEY`   : API キー（必須）
    - `OPENAI_BASE_URL`  : ベース URL（既定: https://api.openai.com/v1）
    - `OPENAI_API_BASE`  : `OPENAI_BASE_URL` の別名
    - `OPENAI_MODEL`     : モデル名（既定: gpt-4o-mini）

    :return: 設定 dict。`OPENAI_API_KEY` が無ければ None。
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not api_key.strip():
        return None

    base_url = (
        os.getenv("OPENAI_BASE_URL")
        or os.getenv("OPENAI_API_BASE")
        or DEFAULT_OPENAI_BASE_URL
    ).strip()
    model = (os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip()

    return {
        "api_key": api_key.strip(),
        "base_url": base_url,
        "model": model,
    }


def web_search_enabled():
    """
    Web 検索ツールを使うかどうか。

    環境変数 `LLM_WEB_SEARCH` が `0` / `false` / `off` / `no` の場合は無効。
    未設定または空文字の場合は有効（既定で検索する）。
    """
    value = os.getenv(WEB_SEARCH_ENV)
    if value is None or not value.strip():
        return True
    return value.strip().lower() not in ("0", "false", "off", "no")


def detect_provider(path=DEFAULT_API_KEY_PATH):
    """
    使用する LLM プロバイダを判定する。

    優先順位:
    1. `GEMINI_API_KEY` が設定されていれば "gemini"
    2. `OPENAI_API_KEY` が設定されていれば "openai"
    3. `api_KEY.txt` が存在すれば後方互換として "gemini"

    :return: "gemini" / "openai" / None
    """
    env_gemini = os.getenv("GEMINI_API_KEY")
    if env_gemini and env_gemini.strip():
        return "gemini"
    if load_openai_config():
        return "openai"
    if load_gemini_api_key(path):
        return "gemini"
    return None


def build_prompt(geolocate_result, question, current_location=None, facing=None):
    """
    ジオロケーション結果と質問から LLM へのプロンプトを構築する。
    """
    res = geolocate_result or {}
    analysis = res.get("analysis", {})
    target = analysis.get("target_attribute", {})

    result_block = ""
    if res.get("status") in ("geocode_success", "success", "overpass_success"):
        # main.py の build_geolocate_result は "found_target" を返す。
        # 旧 geolocate_step_serch_v2 形式の "result" も後方互換で受け付ける。
        found = res.get("found_target") or res.get("result") or {}
        bearing = found.get("bearing")
        bearing_suffix = f" ({bearing}°)" if bearing is not None else ""
        result_block = (
            f"【特定された建物】\n"
            f"- 名称: {found.get('name', '不明')}\n"
            f"- 座標: 緯度 {found.get('latitude', '不明')}, 経度 {found.get('longitude', '不明')}\n"
            f"- OSM属性: class={found.get('osm_class', '不明')}, type={found.get('osm_type', '不明')}\n"
            f"- 現在地からの距離: 約 {found.get('distance_meters', '不明')}m\n"
            f"- 方角/ベクトル: {found.get('vector_name', '不明')}{bearing_suffix}\n"
        )
        if found.get("display_name"):
            result_block += f"- 住所/表示名: {found['display_name']}\n"
        tags = found.get("tags")
        if tags:
            result_block += f"- 付加タグ: {json.dumps(tags, ensure_ascii=False)}\n"
        for extra_key, extra_label in (
            ("height", "高さ"),
            ("building_levels", "階数"),
            ("start_date", "竣工年/建造年"),
        ):
            val = found.get(extra_key)
            if val:
                result_block += f"- {extra_label}: {val}\n"
    else:
        result_block = "【特定された建物】\n情報が不足しており、建物を特定できませんでした。\n"

    location_block = ""
    if current_location:
        location_block += f"- 現在地: 緯度 {current_location[0]}, 経度 {current_location[1]}\n"
    if facing:
        location_block += f"- 進行方向/向いている方角: {facing}\n"

    candidate_block = ""
    candidates = res.get("candidates")
    if candidates:
        candidate_block = "【候補建物】\n"
        for i, c in enumerate(candidates[:5], 1):
            candidate_block += (
                f"{i}. {c.get('name', '不明')} "
                f"({c.get('osm_class', '?')}={c.get('osm_type', '?')}, "
                f"距離 {c.get('distance_meters', '?')}m, スコア {c.get('score', 0):.2f})\n"
            )

    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"{result_block}\n"
        f"{candidate_block}\n"
        f"{location_block}\n"
        f"【ユーザーの質問】\n{question}\n\n"
        f"上記をもとに、ユーザーが目的の場所にスムーズにたどり着けるよう案内してください。"
    )
    return prompt


def ask_gemini(prompt, api_key=None, model=None, web_search=None):
    """
    Gemini API にプロンプトを送信し、回答テキストを返す。

    `web_search=True`（既定）の場合は Google Search グラウンディングを有効にする。
    """
    key = api_key or load_gemini_api_key(DEFAULT_API_KEY_PATH)
    if not key:
        raise RuntimeError(
            "Gemini API キーが見つかりません。環境変数 GEMINI_API_KEY を設定するか、"
            f"{DEFAULT_API_KEY_PATH} を用意してください。"
        )

    use_web_search = web_search_enabled() if web_search is None else web_search
    model = model or DEFAULT_MODEL
    try:
        from google import genai
        from google.genai import types as genai_types

        client = genai.Client(api_key=key)
        config = None
        if use_web_search:
            config = genai_types.GenerateContentConfig(
                tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())]
            )
        response = client.models.generate_content(
            model=model, contents=prompt, config=config
        )
        return response.text.strip() if response and response.text else ""
    except Exception as e:
        raise RuntimeError(f"Gemini API 呼び出しに失敗しました: {e}")


class OpenAIApiError(RuntimeError):
    """OpenAI 互換 API の HTTP エラー（フォールバック判定用）。"""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


# Responses API が使えるかどうかのプロセス内キャッシュ（None=未判定）
_responses_supported = None


def build_openai_endpoint(base_url=None):
    """ベース URL から chat/completions のエンドポイントを組み立てる。"""
    url = (base_url or DEFAULT_OPENAI_BASE_URL).strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/responses"):
        return url[: -len("/responses")] + "/chat/completions"
    return f"{url}/chat/completions"


def build_openai_responses_endpoint(base_url=None):
    """ベース URL から responses のエンドポイントを組み立てる。"""
    url = (base_url or DEFAULT_OPENAI_BASE_URL).strip().rstrip("/")
    if url.endswith("/responses"):
        return url
    if url.endswith("/chat/completions"):
        return url[: -len("/chat/completions")] + "/responses"
    return f"{url}/responses"


def _openai_headers(key):
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _post_openai_json(endpoint, payload, key, timeout):
    """OpenAI 互換 API に JSON を POST し、レスポンス JSON を返す。"""
    try:
        response = requests.post(
            endpoint, json=payload, headers=_openai_headers(key), timeout=timeout
        )
    except Exception as e:
        raise RuntimeError(f"OpenAI 互換 API 呼び出しに失敗しました: {e}")

    if response.status_code >= 400:
        detail = (response.text or "")[:500]
        raise OpenAIApiError(
            f"HTTP {response.status_code}: {detail}", response.status_code
        )

    try:
        return response.json()
    except Exception as e:
        raise RuntimeError(f"OpenAI 互換 API のレスポンス解析に失敗しました: {e}")


def _extract_chat_text(data):
    """chat/completions 形式から回答テキストを取り出す。"""
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None


def _extract_responses_text(data):
    """
    Responses API 形式から回答テキストを取り出す。

    `output_text` が無い場合は `output[].content[].text` を連結する。
    ゲートウェイが chat/completions 形式で返す場合にも対応する。
    """
    if not isinstance(data, dict):
        return None

    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    texts = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "output_text" and item.get("text"):
            texts.append(item["text"])
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") in ("output_text", "text") and content.get("text"):
                texts.append(content["text"])

    if texts:
        return "".join(texts)

    return _extract_chat_text(data)


def _ask_openai_responses(prompt, key, base_url, model, timeout):
    """Responses API + web_search ツールで問い合わせる。"""
    endpoint = build_openai_responses_endpoint(base_url)
    payload = {
        "model": model,
        "input": prompt,
        "tools": [dict(WEB_SEARCH_TOOL)],
    }
    data = _post_openai_json(endpoint, payload, key, timeout)
    text = _extract_responses_text(data)
    if text is None:
        raise RuntimeError("OpenAI 互換 API のレスポンス形式が不正です")
    return (text or "").strip()


def _ask_openai_chat(prompt, key, base_url, model, timeout, web_search):
    """chat/completions で問い合わせる（必要なら web_search ツール付き）。"""
    endpoint = build_openai_endpoint(base_url)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if web_search:
        payload["tools"] = [dict(WEB_SEARCH_TOOL)]

    try:
        data = _post_openai_json(endpoint, payload, key, timeout)
    except OpenAIApiError as e:
        if not web_search or e.status_code not in (400, 404, 405, 422):
            raise
        # tools 非対応サーバー向け: ツール無しで再試行する
        payload.pop("tools", None)
        data = _post_openai_json(endpoint, payload, key, timeout)

    text = _extract_chat_text(data)
    if text is None:
        text = _extract_responses_text(data)
    if text is None:
        raise RuntimeError("OpenAI 互換 API のレスポンス形式が不正です")
    return (text or "").strip()


def ask_openai(prompt, api_key=None, base_url=None, model=None,
               timeout=DEFAULT_OPENAI_TIMEOUT, web_search=None):
    """
    OpenAI 互換 API（OpenAI / Azure OpenAI / Ollama / LM Studio / vLLM など）に
    プロンプトを送信し、回答テキストを返す。

    Web 検索が有効（既定）の場合は、まず Responses API に
    `tools=[{"type": "web_search"}]` を付けて問い合わせる。Responses API 非対応の
    サーバーでは chat/completions にフォールバックする。
    """
    global _responses_supported

    config = load_openai_config() or {}
    key = api_key or config.get("api_key")
    if not key:
        raise RuntimeError(
            "OpenAI 互換 API キーが見つかりません。環境変数 OPENAI_API_KEY を設定してください。"
        )

    base_url = base_url or config.get("base_url")
    model = model or config.get("model") or DEFAULT_OPENAI_MODEL
    use_web_search = web_search_enabled() if web_search is None else web_search

    if use_web_search and _responses_supported is not False:
        try:
            answer = _ask_openai_responses(prompt, key, base_url, model, timeout)
            _responses_supported = True
            return answer
        except OpenAIApiError as e:
            if e.status_code in (400, 404, 405, 422):
                _responses_supported = False
            print(
                "[OpenAI] responses API を利用できないため chat/completions に切り替えます: "
                f"{e}",
                file=sys.stderr,
            )
        except RuntimeError as e:
            print(
                "[OpenAI] responses API を利用できないため chat/completions に切り替えます: "
                f"{e}",
                file=sys.stderr,
            )

    return _ask_openai_chat(prompt, key, base_url, model, timeout, use_web_search)


def ask_llm(prompt, api_key=None, model=None, web_search=None):
    """
    利用可能なプロバイダ（Gemini / OpenAI 互換）を自動選択して回答を生成する。

    `api_key` が明示された場合は従来どおり Gemini のキーとして扱う。
    `web_search` を省略した場合は環境変数 `LLM_WEB_SEARCH` に従う（既定: 有効）。
    """
    if api_key:
        return ask_gemini(prompt, api_key=api_key, model=model, web_search=web_search)

    provider = detect_provider()
    if provider == "gemini":
        return ask_gemini(prompt, model=model, web_search=web_search)

    if provider == "openai":
        config = load_openai_config() or {}
        return ask_openai(
            prompt,
            api_key=config.get("api_key"),
            base_url=config.get("base_url"),
            model=model or config.get("model"),
            web_search=web_search,
        )

    raise RuntimeError(
        "LLM API キーが見つかりません。環境変数 GEMINI_API_KEY または "
        "OPENAI_API_KEY を設定してください。"
    )


def build_unique_audio_path(directory=None, ext=".mp3"):
    """衝突しない mp3 の出力パスを生成する（UUID 連番）。"""
    directory = directory or AUDIO_DIR
    os.makedirs(directory, exist_ok=True)
    filename = f"answer_{uuid.uuid4().hex[:12]}{ext}"
    return os.path.join(directory, filename)


def text_to_speech(text, output_path=None, lang="ja"):
    """
    gTTS を使ってテキストを mp3 ファイルに保存する。

    :param output_path: None の場合は `AUDIO_DIR` に一意な名前で保存する。
    """
    if not text:
        return None
    if output_path is None:
        output_path = build_unique_audio_path()
    else:
        parent = os.path.dirname(os.path.abspath(output_path))
        os.makedirs(parent, exist_ok=True)
    tts = gTTS(text=text, lang=lang)
    tts.save(output_path)
    return output_path


def answer_question(geolocate_result, question, current_location=None, facing=None,
                    api_key=None, model=None, web_search=None,
                    generate_audio=False, audio_path=None):
    """
    geolocate_step_serch の結果と質問から LLM 回答を生成し、必要なら音声化する。

    LLM プロバイダは `ask_llm` が自動選択する（Gemini → OpenAI 互換の順）。
    `web_search` を省略した場合は環境変数 `LLM_WEB_SEARCH` に従う（既定: 有効）。

    :return: dict {"answer": str, "audio_path": str|None, "prompt": str}
    """
    prompt = build_prompt(geolocate_result, question,
                          current_location=current_location, facing=facing)
    answer = ask_llm(prompt, api_key=api_key, model=model, web_search=web_search)
    saved_path = None
    if generate_audio and answer:
        saved_path = text_to_speech(answer, output_path=audio_path)
    return {
        "answer": answer,
        "audio_path": saved_path,
        "prompt": prompt,
    }


def main():
    parser = argparse.ArgumentParser(description="LLM QA + gTTS 音声生成")
    parser.add_argument("question", nargs="*", help="質問文 (例: あの建物は何ですか)")
    parser.add_argument("--result", default=None, help="geolocate_step_serch の JSON 結果ファイルパス")
    parser.add_argument("--lat", type=float, default=None, help="現在地の緯度")
    parser.add_argument("--lon", type=float, default=None, help="現在地の経度")
    parser.add_argument("--facing", default=None, help="向いている方角")
    parser.add_argument("--audio", default=DEFAULT_AUDIO_PATH, help="出力する mp3 ファイルパス")
    parser.add_argument("--no-audio", action="store_true", help="音声生成をスキップ")
    parser.add_argument("--model", default=None, help="LLM モデル名（未指定時はプロバイダの既定値）")

    args = parser.parse_args()

    question = " ".join(args.question) if args.question else None
    if not question:
        try:
            question = input("質問文を入力してください: ").strip()
        except (EOFError, KeyboardInterrupt):
            question = "この建物について教えて"
    if not question:
        question = "この建物について教えて"

    geolocate_result = None
    if args.result:
        try:
            with open(args.result, "r", encoding="utf-8") as f:
                geolocate_result = json.load(f)
        except Exception as e:
            print(f"[警告] 結果ファイルの読み込みに失敗しました: {e}", file=sys.stderr)

    current_location = (args.lat, args.lon) if args.lat is not None and args.lon is not None else None

    try:
        result = answer_question(
            geolocate_result=geolocate_result,
            question=question,
            current_location=current_location,
            facing=args.facing,
            model=args.model,
            generate_audio=(not args.no_audio),
            audio_path=args.audio,
        )
    except RuntimeError as e:
        print(f"[エラー] {e}", file=sys.stderr)
        sys.exit(1)

    print("=" * 80)
    print("【LLM 回答】")
    print("=" * 80)
    print(result["answer"])
    if result["audio_path"]:
        print(f"\n[音声ファイル] {result['audio_path']} を生成しました")
    print("=" * 80)


if __name__ == "__main__":
    main()
