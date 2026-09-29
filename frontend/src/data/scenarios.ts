import type { DealContext, HistoryMessage } from '@/lib/types'

export interface FeedMessage {
  id: string
  role: 'customer' | 'manager' | 'note'
  text: string
}

export interface Scenario {
  id: string
  contact: string
  unread: boolean
  deal: DealContext
  messages: FeedMessage[]
}

// Seeded conversations = the 4 demo scenarios (CONTEXT §19).
export const SCENARIOS: Scenario[] = [
  {
    id: 's1',
    contact: 'Алексей',
    unread: true,
    deal: {
      contact: 'Алексей',
      company: 'ООО «Вектор»',
      channel: 'telegram',
      plan: 'start',
      seats_used: 5,
      seat_limit: 5,
      addons_owned: [],
      stage: 'client',
    },
    messages: [
      { id: 's1-m1', role: 'customer', text: 'Здравствуйте! Мы сейчас на тарифе Старт.' },
      { id: 's1-m2', role: 'manager', text: 'Добрый день, Алексей! Чем могу помочь?' },
      {
        id: 's1-m3',
        role: 'customer',
        text: 'Сколько пользователей можно подключить на тарифе Старт и есть ли интеграция с Telegram?',
      },
    ],
  },
  {
    id: 's2',
    contact: 'Ирина',
    unread: true,
    deal: {
      contact: 'Ирина',
      company: 'ООО «Вектор»',
      channel: 'telegram',
      plan: 'business',
      seats_used: 12,
      seat_limit: 50,
      addons_owned: [],
      stage: 'trial',
    },
    messages: [
      { id: 's2-m1', role: 'customer', text: 'Мы тестируем ваш сервис вторую неделю.' },
      { id: 's2-m2', role: 'manager', text: 'Отлично, Ирина! Как впечатления?' },
      {
        id: 's2-m3',
        role: 'customer',
        text: 'В целом нравится, но дороговато для нас. Есть скидки?',
      },
    ],
  },
  {
    id: 's3',
    contact: 'Daniel',
    unread: true,
    deal: {
      contact: 'Daniel',
      company: 'Northwind Ltd',
      channel: 'telegram',
      plan: 'business',
      seats_used: 20,
      seat_limit: 50,
      addons_owned: [],
      stage: 'client',
    },
    messages: [
      { id: 's3-m1', role: 'customer', text: "Hi, we've been using TeamFlow for a month." },
      { id: 's3-m2', role: 'manager', text: 'Здравствуйте, Daniel! Чем могу помочь?' },
      {
        id: 's3-m3',
        role: 'customer',
        text: 'We want to connect 1C and get reports by manager — is that possible?',
      },
    ],
  },
  {
    id: 's4',
    contact: 'Сергей',
    unread: false,
    deal: {
      contact: 'Сергей',
      company: 'ООО «Вектор»',
      channel: 'telegram',
      plan: 'none',
      seats_used: 0,
      seat_limit: 0,
      addons_owned: [],
      stage: 'new',
    },
    messages: [
      { id: 's4-m1', role: 'customer', text: 'Здравствуйте!' },
      { id: 's4-m2', role: 'manager', text: 'Здравствуйте, Сергей! Чем могу помочь?' },
      {
        id: 's4-m3',
        role: 'customer',
        text: 'Сможете сделать для нас кастомное мобильное приложение под iOS?',
      },
    ],
  },
]

export function lastCustomerMessage(messages: FeedMessage[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === 'customer') return messages[i].text
  }
  return ''
}

// History sent to the API excludes the message itself (it goes into
// <customer_message> separately).
export function buildHistory(messages: FeedMessage[]): HistoryMessage[] {
  const customerMessage = lastCustomerMessage(messages)
  const history: HistoryMessage[] = []
  for (const message of messages) {
    if (message.role === 'note') continue
    if (message.role === 'customer' && message.text === customerMessage) continue
    history.push({ role: message.role, text: message.text })
  }
  return history
}
