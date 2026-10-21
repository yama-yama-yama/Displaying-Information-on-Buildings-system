export interface AnalyzeRequest {
  text: string
  method?: 'difflib' | 'word2vec'
  top_k?: number
}

export interface AnalyzeResponse {
  input_text: string
  analysis: {
    directions: DirectionInfo[]
    intent: IntentInfo
    resolved_entities: ResolvedEntity[]
    expanded_tags: string[]
    feature_keywords: string[]
    translated_en: string
    tokens: string[]
  }
  method: string
  top_results: MapFeatureResult[]
}

export interface DirectionInfo {
  category: 'relative' | 'cardinal'
  key: string
  name: string
  matched: string
  command?: string
  vector: [number, number]
  symbol?: string
}

export interface IntentInfo {
  intent: string
  name: string
  description: string
  matched: string
}

export interface ResolvedEntity {
  matched_name: string
  source: string
  class: string
  value: string
  tags: string[]
}

export interface MapFeatureResult {
  class: string
  value: string
  score: number
  matched_token: string
  detail: string
}

export interface AskRequest {
  question: string
  latitude?: number
  longitude?: number
  facing?: string
  generate_audio?: boolean
}

export interface AskResponse {
  question: string
  answer: string
  audio_path?: string
  analysis: AnalyzeResponse['analysis']
  found_target?: FoundTarget
}

export interface LlmOnlyRequest {
  prompt: string
  model?: string
}

export interface LlmOnlyResponse {
  prompt: string
  answer: string
}

export interface FoundTarget {
  name: string
  latitude: number
  longitude: number
  osm_class: string
  osm_type: string
  distance_meters?: number
  vector_name?: string
  display_name: string
}
