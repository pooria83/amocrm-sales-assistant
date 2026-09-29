import {
  createContext,
  useContext,
  useMemo,
  useReducer,
  type Dispatch,
  type ReactNode,
} from 'react'
import { SCENARIOS, type FeedMessage, type Scenario } from '@/data/scenarios'
import type { AssistResponse, RetrieveResponse } from '@/lib/types'

export type AssistStatus = 'idle' | 'retrieving' | 'generating' | 'done' | 'error'

export interface ChatSession {
  messages: FeedMessage[]
  retrieval: RetrieveResponse | null
  result: AssistResponse | null
  status: AssistStatus
}

export interface ConversationState {
  sessions: Record<string, ChatSession>
  selectedId: string
}

export type ConversationAction =
  | { type: 'select'; id: string }
  | { type: 'retrieve_started'; id: string }
  | { type: 'retrieve_done'; id: string; retrieval: RetrieveResponse }
  | { type: 'assist_started'; id: string }
  | { type: 'assist_done'; id: string; result: AssistResponse }
  | { type: 'assist_error'; id: string }
  | { type: 'assist_retry'; id: string }
  | { type: 'send_to_chat'; id: string; text: string }
  | { type: 'add_note'; id: string; text: string }

function initialSessions(): Record<string, ChatSession> {
  const sessions: Record<string, ChatSession> = {}
  for (const scenario of SCENARIOS) {
    sessions[scenario.id] = {
      messages: [...scenario.messages],
      retrieval: null,
      result: null,
      status: 'idle',
    }
  }
  return sessions
}

export function conversationReducer(
  state: ConversationState,
  action: ConversationAction,
): ConversationState {
  const session = state.sessions[action.id]
  if (!session) return state
  const update = (patch: Partial<ChatSession>): ConversationState => ({
    ...state,
    sessions: { ...state.sessions, [action.id]: { ...session, ...patch } },
  })

  switch (action.type) {
    case 'select':
      return { ...state, selectedId: action.id }
    case 'retrieve_started':
      return update({ status: 'retrieving', retrieval: null, result: null })
    case 'retrieve_done':
      return update({ retrieval: action.retrieval })
    case 'assist_started':
      return update({ status: 'generating' })
    case 'assist_done':
      return update({ status: 'done', result: action.result })
    case 'assist_error':
      return update({ status: 'error' })
    case 'assist_retry':
      return update({ status: 'idle', retrieval: null, result: null })
    case 'send_to_chat':
      return update({
        messages: [
          ...session.messages,
          { id: `local-${Date.now()}`, role: 'manager', text: action.text },
        ],
      })
    case 'add_note':
      return update({
        messages: [
          ...session.messages,
          { id: `note-${Date.now()}`, role: 'note', text: action.text },
        ],
      })
    default:
      return state
  }
}

const initialState: ConversationState = {
  sessions: initialSessions(),
  selectedId: SCENARIOS[0].id,
}

interface ConversationValue {
  state: ConversationState
  dispatch: Dispatch<ConversationAction>
  scenarios: Scenario[]
}

const ConversationContext = createContext<ConversationValue | null>(null)

export function ConversationProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(conversationReducer, initialState)
  const value = useMemo<ConversationValue>(
    () => ({ state, dispatch, scenarios: SCENARIOS }),
    [state, dispatch],
  )
  return <ConversationContext.Provider value={value}>{children}</ConversationContext.Provider>
}

export function useConversation(): ConversationValue {
  const ctx = useContext(ConversationContext)
  if (!ctx) throw new Error('useConversation must be used within ConversationProvider')
  return ctx
}

export function useSelectedChat(): {
  scenario: Scenario
  session: ChatSession
} {
  const { state, scenarios } = useConversation()
  const scenario = scenarios.find((s) => s.id === state.selectedId) ?? scenarios[0]
  return { scenario, session: state.sessions[scenario.id] }
}
