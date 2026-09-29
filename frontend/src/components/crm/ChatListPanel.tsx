import { ChatListItem } from '@/components/crm/ChatListItem'
import { Separator } from '@/components/ui/separator'
import { useI18n } from '@/i18n'
import type { Scenario } from '@/data/scenarios'

export interface ChatListPanelProps {
  scenarios: Scenario[]
  previews: Record<string, string>
  unread: Record<string, boolean>
  selectedId: string
  onSelect: (id: string) => void
}

export function ChatListPanel({
  scenarios,
  previews,
  unread,
  selectedId,
  onSelect,
}: ChatListPanelProps) {
  const { t } = useI18n()
  return (
    <aside
      data-testid="chat-list"
      className="flex w-[300px] shrink-0 flex-col border-r border-[#e1e5ea] bg-white"
    >
      <div className="flex h-12 items-center px-4">
        <h2 className="text-sm font-semibold text-[#1f2933]">{t('chats')}</h2>
      </div>
      <Separator />
      <nav className="flex-1 overflow-y-auto">
        {scenarios.map((scenario) => (
          <ChatListItem
            key={scenario.id}
            id={scenario.id}
            name={scenario.contact}
            preview={previews[scenario.id] ?? ''}
            channel={scenario.deal.channel}
            unread={Boolean(unread[scenario.id])}
            selected={scenario.id === selectedId}
            onSelect={onSelect}
          />
        ))}
      </nav>
    </aside>
  )
}
