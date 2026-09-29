import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import type { Intent, Lang } from './lib/types'

export type UiLang = Lang

const ru = {
  appName: 'Ассистент продаж',
  chats: 'Чаты',
  dealCard: 'Сделка',
  tabChat: 'Чат',
  tabNote: 'Примечание',
  sendToChat: 'Отправить в чат',
  addNote: 'Добавить примечание',
  copyReply: 'Копировать',
  copied: 'Скопировано',
  replyLabel: 'Ответ клиенту',
  replyPlaceholder: 'Черновик ответа…',
  hintsLabel: 'Подсказки менеджеру',
  internalOnly: 'Только для менеджера',
  internalHint: 'Внутренняя подсказка',
  upsellSection: 'Допродажи',
  crossSellSection: 'Кросс-продажи',
  noCandidates: 'Нет подходящих допродаж',
  talkingPoint: 'Что сказать',
  reason: 'Почему подходит',
  sources: 'Источники',
  kbMatches: 'Найдено в базе знаний',
  score: 'Вес BM25',
  threshold: 'Порог',
  matchedTerms: 'Совпавшие слова',
  noMatch: 'Нет совпадений в базе знаний',
  templateBanner: 'Ответ сформирован по шаблону',
  numbersVerified: 'Числа проверены по базе знаний',
  language: 'Язык',
  langSource_message: 'по сообщению',
  langSource_conversation: 'по диалогу',
  langSource_ui_default: 'по умолчанию',
  intent: 'Намерение',
  loadingRetrieval: 'Ищем в базе знаний…',
  loadingGeneration: 'Генерируем ответ…',
  errorText: 'Не удалось получить ответ. Попробуйте ещё раз.',
  retry: 'Повторить',
  chatPlaceholder: 'Написать сообщение…',
  notePlaceholder: 'Заметка для себя…',
  contact: 'Контакт',
  company: 'Компания',
  channel: 'Канал',
  plan: 'Тариф',
  seats: 'Места',
  stage: 'Этап',
  assistantPanelTitle: 'Ассистент',
  noteAdded: 'Примечание',
  escaltionHint: 'эскалация',
  plan_start: 'Старт',
  plan_business: 'Бизнес',
  plan_enterprise: 'Энтерпрайз',
  plan_none: 'Нет',
  stage_trial: 'Пробный период',
  stage_negotiation: 'Переговоры',
  stage_client: 'Клиент',
  stage_new: 'Новый',
  channel_telegram: 'Telegram',
  channel_whatsapp: 'WhatsApp',
  intent_pricing: 'Цена',
  intent_objection: 'Возражение',
  intent_integration: 'Интеграция',
  intent_limits: 'Лимиты',
  intent_reporting: 'Отчёты',
  intent_support: 'Поддержка',
  intent_other: 'Прочее',
} as const

export type TKey = keyof typeof ru

const en: Record<TKey, string> = {
  appName: 'Sales Assistant',
  chats: 'Chats',
  dealCard: 'Deal',
  tabChat: 'Chat',
  tabNote: 'Note',
  sendToChat: 'Send to chat',
  addNote: 'Add note',
  copyReply: 'Copy',
  copied: 'Copied',
  replyLabel: 'Reply to customer',
  replyPlaceholder: 'Draft reply…',
  hintsLabel: 'Hints for the manager',
  internalOnly: 'Manager only',
  internalHint: 'Internal hint',
  upsellSection: 'Upsell',
  crossSellSection: 'Cross-sell',
  noCandidates: 'No upsell candidates',
  talkingPoint: 'Talking point',
  reason: 'Why it fits',
  sources: 'Sources',
  kbMatches: 'Found in the KB',
  score: 'BM25 score',
  threshold: 'Threshold',
  matchedTerms: 'Matched terms',
  noMatch: 'No KB match',
  templateBanner: 'Template reply',
  numbersVerified: 'Numbers verified against KB',
  language: 'Language',
  langSource_message: 'from message',
  langSource_conversation: 'from conversation',
  langSource_ui_default: 'default',
  intent: 'Intent',
  loadingRetrieval: 'Searching the KB…',
  loadingGeneration: 'Generating the reply…',
  errorText: 'Could not get a reply. Please try again.',
  retry: 'Retry',
  chatPlaceholder: 'Type a message…',
  notePlaceholder: 'Note to yourself…',
  contact: 'Contact',
  company: 'Company',
  channel: 'Channel',
  plan: 'Plan',
  seats: 'Seats',
  stage: 'Stage',
  assistantPanelTitle: 'Assistant',
  noteAdded: 'Note',
  escaltionHint: 'escalation',
  plan_start: 'Start',
  plan_business: 'Business',
  plan_enterprise: 'Enterprise',
  plan_none: 'None',
  stage_trial: 'Trial',
  stage_negotiation: 'Negotiation',
  stage_client: 'Client',
  stage_new: 'New',
  channel_telegram: 'Telegram',
  channel_whatsapp: 'WhatsApp',
  intent_pricing: 'Pricing',
  intent_objection: 'Objection',
  intent_integration: 'Integration',
  intent_limits: 'Limits',
  intent_reporting: 'Reporting',
  intent_support: 'Support',
  intent_other: 'Other',
}

const dictionaries: Record<UiLang, Record<TKey, string>> = { ru, en }

interface I18nValue {
  lang: UiLang
  setLang: (lang: UiLang) => void
  t: (key: TKey) => string
  intentLabel: (intent: Intent) => string
}

const I18nContext = createContext<I18nValue | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<UiLang>('ru')

  const value = useMemo<I18nValue>(
    () => ({
      lang,
      setLang,
      t: (key) => dictionaries[lang][key],
      intentLabel: (intent) => dictionaries[lang][`intent_${intent}`],
    }),
    [lang],
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useI18n must be used within I18nProvider')
  return ctx
}
