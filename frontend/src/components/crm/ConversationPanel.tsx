import { AssistantPanel } from '@/components/assistant/AssistantPanel'
import { Composer } from '@/components/crm/Composer'
import { ConversationHeader } from '@/components/crm/ConversationHeader'
import { MessageFeed } from '@/components/crm/MessageFeed'
import { useConversation, useSelectedChat } from '@/hooks/useConversation'

// Container for the centre column: conversation + assistant + composer.
export function ConversationPanel() {
  const { scenario, session } = useSelectedChat()
  const { dispatch } = useConversation()

  const onSend = (mode: 'chat' | 'note', text: string) => {
    if (mode === 'chat') {
      dispatch({ type: 'send_to_chat', id: scenario.id, text })
    } else {
      dispatch({ type: 'add_note', id: scenario.id, text })
    }
  }

  return (
    <main className="flex min-w-0 flex-1 flex-col">
      <ConversationHeader contact={scenario.contact} channel={scenario.deal.channel} />
      <MessageFeed messages={session.messages} />
      <AssistantPanel />
      <Composer onSend={onSend} />
    </main>
  )
}
