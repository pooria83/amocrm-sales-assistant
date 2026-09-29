import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { CrmLayout } from '@/components/crm/CrmLayout'
import { TooltipProvider } from '@/components/ui/tooltip'
import { ConversationProvider } from '@/hooks/useConversation'
import { I18nProvider } from '@/i18n'

function App() {
  return (
    <I18nProvider>
      <ConversationProvider>
        <TooltipProvider delayDuration={200}>
          <ErrorBoundary>
            <CrmLayout />
          </ErrorBoundary>
        </TooltipProvider>
      </ConversationProvider>
    </I18nProvider>
  )
}

export default App
