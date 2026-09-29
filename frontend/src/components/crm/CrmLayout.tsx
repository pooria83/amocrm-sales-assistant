import { ChatListPanel } from '@/components/crm/ChatListPanel'
import { ConversationPanel } from '@/components/crm/ConversationPanel'
import { DealCardPanel } from '@/components/crm/DealCardPanel'
import { useConversation } from '@/hooks/useConversation'

// Three-column AmoCRM-familiar shell: chats | conversation | deal card.
export function CrmLayout() {
  const { state, scenarios, dispatch } = useConversation()
  const selected = scenarios.find((s) => s.id === state.selectedId) ?? scenarios[0]

  const previews: Record<string, string> = {}
  const unread: Record<string, boolean> = {}
  for (const scenario of scenarios) {
    const messages = state.sessions[scenario.id]?.messages ?? []
    const visible = messages.filter((message) => message.role !== 'note')
    const last = visible.length > 0 ? visible[visible.length - 1] : messages[0]
    previews[scenario.id] = last ? last.text : ''
    unread[scenario.id] = scenario.unread && !state.visited.includes(scenario.id)
  }

  return (
    <div
      data-testid="crm-layout"
      className="flex h-screen w-screen overflow-hidden bg-[#f4f6f8] text-[#1f2933]"
    >
      <ChatListPanel
        scenarios={scenarios}
        previews={previews}
        unread={unread}
        selectedId={state.selectedId}
        onSelect={(id) => dispatch({ type: 'select', id })}
      />
      <ConversationPanel />
      <DealCardPanel deal={selected.deal} />
    </div>
  )
}
