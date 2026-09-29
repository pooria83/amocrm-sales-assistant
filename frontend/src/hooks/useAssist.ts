import { useEffect } from 'react'
import { buildHistory, lastCustomerMessage, type Scenario } from '@/data/scenarios'
import { assist, retrieve } from '@/lib/api'
import { useI18n } from '@/i18n'
import { useConversation, useSelectedChat, type ChatSession } from './useConversation'

export interface AssistView {
  scenario: Scenario
  session: ChatSession
  retry: () => void
}

// Two-phase flow (CONTEXT §5): /api/retrieve first so BM25 matches render
// instantly, then /api/assist fills the reply and the internal hints.
export function useAssist(): AssistView {
  const { scenario, session } = useSelectedChat()
  const { dispatch } = useConversation()
  const { lang } = useI18n()
  const { status } = session

  useEffect(() => {
    if (status !== 'idle') return
    const message = lastCustomerMessage(scenario.messages)
    if (!message) return

    const id = scenario.id
    const history = buildHistory(scenario.messages)
    dispatch({ type: 'retrieve_started', id })

    retrieve({ message, ui_lang: lang, history })
      .then((retrieval) => {
        dispatch({ type: 'retrieve_done', id, retrieval })
        dispatch({ type: 'assist_started', id })
        return assist({ message, ui_lang: lang, history, deal: scenario.deal })
      })
      .then((result) => dispatch({ type: 'assist_done', id, result }))
      .catch(() => dispatch({ type: 'assist_error', id }))
  }, [status, scenario, lang, dispatch])

  const retry = () => dispatch({ type: 'assist_retry', id: scenario.id })

  return { scenario, session, retry }
}
