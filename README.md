# GPS_buildings_info — 屋外ナビアシスタント

位置情報・方位・音声入力を利用し、抽象的な質問から特定の建物を割り出して案内する
ナビゲーションシステムです。

- バックエンド: Python 3.12 / FastAPI / Gemini API / OpenStreetMap (Nominatim)
- フロントエンド: Vue 3 + TypeScript + Vite

## ディレクトリ構成

```
backend/
  main.py                       FastAPI エントリポイント
  llm_qa.py                     LLM 連携（Gemini / OpenAI 互換）・プロンプト構築・gTTS 音声生成
  searchsynonyms_mapfeatures_v2.py  自然文解析・OSM タグ推定
  feature_tags.py               ローカル CSV と解析結果のタグマージ
  transcribe.py                 音声文字起こし（/api/transcribe 用）
  voice_comand_test.py          ローカル録音用 CLI（tkinter / PyAudio）
  mapfeatures.csv               OSM 地物タグ候補（類似度検索用）
  high_buildings.csv            高層建築タグ候補
  tests/                        pytest
frontend/
  src/components/ChatPanel.vue  質問入力・音声入力・回答音声の再生
  src/composables/              Geolocation / DeviceOrientation / 音声認識
  src/services/api.ts           バックエンド API クライアント
```

## セットアップ

### バックエンド

```bash
cd backend
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
# source venv/bin/activate

pip install -r requirements.txt
```

Gemini API キーは次のいずれかで設定してください（環境変数が優先されます）。

1. 環境変数

   ```bash
   # Windows (PowerShell)
   $env:GEMINI_API_KEY = "your-api-key"
   # macOS / Linux
   export GEMINI_API_KEY="your-api-key"
   ```

2. `backend/api_KEY.txt` にキーを 1 行で保存する

#### OpenAI 互換 API を使う場合

`GEMINI_API_KEY` が未設定で `OPENAI_API_KEY` が設定されている場合は、
OpenAI 互換 API（OpenAI / Azure OpenAI / Ollama / LM Studio / vLLM など）を使用します。

```bash
# Windows (PowerShell)
$env:OPENAI_API_KEY = "your-api-key"
$env:OPENAI_BASE_URL = "http://localhost:11434/v1"  # 省略時: https://api.openai.com/v1
$env:OPENAI_MODEL = "llama3"                         # 省略時: gpt-4o-mini

# macOS / Linux
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="http://localhost:11434/v1"
export OPENAI_MODEL="llama3"
```

プロバイダの優先順位は次のとおりです。

1. `GEMINI_API_KEY`（環境変数）→ Gemini API
2. `OPENAI_API_KEY`（環境変数）→ OpenAI 互換 API
3. `backend/api_KEY.txt` → 後方互換として Gemini API

`OPENAI_BASE_URL` は `/v1` まで含めて指定してください。`OPENAI_API_BASE` も別名として使えます。

#### Web 検索ツール

回答生成時は既定で Web 検索を有効にしています。

- **OpenAI 互換 API**: Responses API に `tools=[{"type": "web_search"}]` を付けて問い合わせます。
  Responses API 非対応のサーバーでは chat/completions にフォールバックし、
  ツール非対応の場合はツール無しで再試行します。
- **Gemini API**: Google Search グラウンディングを使用します。

無効化する場合は `LLM_WEB_SEARCH=0` を設定してください。

起動:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### フロントエンド

```bash
cd frontend
npm install
npm run dev
```

バックエンドの URL を変更する場合は `frontend/.env.local` に設定します。

```bash
VITE_API_BASE_URL=http://localhost:8000
```

### 音声アップロードについて

`/api/transcribe` は WAV を標準ライブラリで解析し、webm / ogg / mp3 などは
`ffmpeg` で変換します。WAV 以外をサーバーへ送る場合は `ffmpeg` をインストールしてください。
ブラウザが Web Speech API に対応している場合は、音声認識をブラウザ内で行うため
`ffmpeg` は不要です。

## API

| メソッド | パス | 説明 |
| --- | --- | --- |
| GET | `/api/health` | ヘルスチェック |
| POST | `/api/analyze` | 自然文の解析（方向・意図・固有名詞・OSM タグ候補） |
| POST | `/api/ask` | 質問と現在地から建物を特定し、LLM が案内回答を生成 |
| POST | `/api/ask-llm-only` | プロンプトをそのまま LLM（Gemini / OpenAI 互換を自動選択）に送信 |
| POST | `/api/transcribe` | 音声ファイルを文字起こし（multipart: `file`） |
| GET | `/api/audio/{filename}` | 生成された回答音声 (mp3) を配信 |

### リクエスト例

```bash
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"北に見える塔は何ですか？","latitude":35.6812,"longitude":139.7671,"facing":"north","generate_audio":true}'
```

`generate_audio: true` の場合、レスポンスの `audio_path` に
`/api/audio/xxxx.mp3` が入ります。

## 位置検索のタグマージ方針

Overpass API で周辺検索する際のタグ候補は `backend/feature_tags.py` の
`collect_search_tags()` で組み立てます。優先順位は次のとおりです。

1. `expanded_tags` — 固有名詞解決で得た高信頼タグ（最優先）
2. `top_results` — `mapfeatures.csv` との類似度検索結果（スコア `0.5` 以上のみ）
3. `high_buildings.csv` — 質問が「ビル / タワー / 高層」などの場合は高層建築タグを補完

重複は挿入順を保って除去し、最大 8 件に制限します。`mapfeatures.csv` は候補の網羅性を、
`high_buildings.csv` は高層建築カテゴリの精度を担います。

## テスト

```bash
# バックエンド
cd backend
pip install -r requirements-dev.txt
python -m pytest

# フロントエンド
cd frontend
npm test          # vitest run
npm run type-check
```

## 環境変数

| 変数 | 場所 | 説明 |
| --- | --- | --- |
| `GEMINI_API_KEY` | バックエンド | Gemini API キー（最優先） |
| `OPENAI_API_KEY` | バックエンド | OpenAI 互換 API キー（Gemini キーが無い場合に使用） |
| `OPENAI_BASE_URL` | バックエンド | OpenAI 互換 API のベース URL（既定: `https://api.openai.com/v1`） |
| `OPENAI_API_BASE` | バックエンド | `OPENAI_BASE_URL` の別名 |
| `OPENAI_MODEL` | バックエンド | OpenAI 互換 API のモデル名（既定: `gpt-4o-mini`） |
| `LLM_WEB_SEARCH` | バックエンド | `0` / `false` / `off` / `no` で Web 検索ツールを無効化（既定: 有効） |
| `VITE_API_BASE_URL` | フロントエンド | バックエンドのベース URL（既定: `http://localhost:8000`） |
