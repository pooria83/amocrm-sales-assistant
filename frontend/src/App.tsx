import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { CrmLayout } from '@/components/crm/CrmLayout'
import { ConversationProvider } from '@/hooks/useConversation'
import { I18nProvider } from '@/i18n'

function App() {
  return (
    <I18nProvider>
      <ConversationProvider>
        <ErrorBoundary>
          <CrmLayout />
        </ErrorBoundary>
      </ConversationProvider>
    </I18nProvider>
  )
}

export default App
