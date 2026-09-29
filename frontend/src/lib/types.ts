// Types mirroring the backend Pydantic models (CONTEXT §13).
// customer_reply and internal_sales_hints are independent contracts.

export type Lang = 'ru' | 'en'
export type LangSource = 'message' | 'conversation' | 'ui_default'
export type PlanId = 'start' | 'business' | 'enterprise' | 'none'
export type Stage = 'trial' | 'negotiation' | 'client' | 'new'
export type Channel = 'telegram' | 'whatsapp'
export type Intent =
  | 'pricing'
  | 'objection'
  | 'integration'
  | 'limits'
  | 'reporting'
  | 'support'
  | 'other'

export interface HistoryMessage {
  role: 'customer' | 'manager'
  text: string
}

export interface DealContext {
  contact: string
  company: string
  channel: Channel
  plan: PlanId
  seats_used: number
  seat_limit: number
  addons_owned: string[]
  stage: Stage
}

export interface Match {
  id: string
  title: string
  score: number
  matched_terms: string[]
}

export interface RetrieveRequest {
  message: string
  ui_lang: Lang
  history: HistoryMessage[]
}

export interface RetrieveResponse {
  detected_lang: Lang
  lang_source: LangSource
  matches: Match[]
  threshold: number
  grounded: boolean
}

export interface AssistRequest extends RetrieveRequest {
  deal: DealContext
}

export interface CustomerReply {
  text: string
  lang: Lang
  kb_refs: string[]
}

export interface HintItem {
  id: string
  title: string
  reason: string
  talking_point: string
}

export interface InternalSalesHints {
  lang: Lang
  upsell: HintItem[]
  cross_sell: HintItem[]
  notes: string
}

export interface Validation {
  numbers_ok: boolean
  language_ok: boolean
  no_leakage: boolean
  schema_ok: boolean
  retries: number
  fallback_used: boolean
  model: string
  latency_ms: number
}

export interface AssistResponse {
  detected_lang: Lang
  grounded: boolean
  intent: Intent
  customer_reply: CustomerReply
  internal_sales_hints: InternalSalesHints
  retrieval: { matches: Match[]; threshold: number }
  validation: Validation
}
