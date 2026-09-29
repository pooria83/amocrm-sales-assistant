import { AssistantBadges } from '@/components/assistant/AssistantBadges'
import { CustomerReplyCard } from '@/components/assistant/CustomerReplyCard'
import { ErrorState } from '@/components/assistant/ErrorState'
import { InternalHintsCard } from '@/components/assistant/InternalHintsCard'
import { KbMatchList } from '@/components/assistant/KbMatchList'
import { LoadingState } from '@/components/assistant/LoadingState'
import { SourceChips } from '@/components/assistant/SourceChips'
import { useAssist } from '@/hooks/useAssist'
import { useConversation } from '@/hooks/useConversation'
import { useI18n } from '@/i18n'

// Container for the whole suggestion area: it owns the two-phase assist
// flow and renders the two output contracts as separate cards.
export function AssistantPanel() {
  const { scenario, session, retry } = useAssist()
  const { dispatch } = useConversation()
  const { t } = useI18n()
  const { retrieval, result, status } = session
  const id = scenario.id

  const titles: Record<string, string> = {}
  for (const match of retrieval?.matches ?? []) titles[match.id] = match.title

  const showLoading = status === 'idle' || status === 'retrieving' || status === 'generating'
  const showGenerating = status === 'retrieving' || status === 'generating'

  return (
    <section
      data-testid="assistant-panel"
      className="max-h-[46%] shrink-0 space-y-3 overflow-y-auto border-t border-[#e1e5ea] bg-[#fafbfc] px-4 py-3"
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-[#8a96a3]">
          {t('assistantPanelTitle')}
        </h3>
        {retrieval && (
          <AssistantBadges
            lang={retrieval.detected_lang}
            langSource={retrieval.lang_source}
            intent={result?.intent ?? 'other'}
            validation={result?.validation}
          />
        )}
      </div>

      {retrieval && <KbMatchList matches={retrieval.matches} threshold={retrieval.threshold} />}

      {status === 'error' && <ErrorState onRetry={retry} />}
      {showLoading && <LoadingState phase={showGenerating ? 'generating' : 'retrieving'} />}

      {status === 'done' && result && (
        <>
          <SourceChips ids={result.customer_reply.kb_refs} titles={titles} />
          <CustomerReplyCard
            reply={result.customer_reply}
            onSendToChat={(text) => dispatch({ type: 'send_to_chat', id, text })}
          />
          <InternalHintsCard
            hints={result.internal_sales_hints}
            onAddNote={(text) => dispatch({ type: 'add_note', id, text })}
          />
        </>
      )}
    </section>
  )
}
