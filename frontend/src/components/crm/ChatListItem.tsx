import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { MessageCircle, Send } from 'lucide-react'

export interface ChatListItemProps {
  id: string
  name: string
  preview: string
  channel: 'telegram' | 'whatsapp'
  unread: boolean
  selected: boolean
  onSelect: (id: string) => void
}

const channelIcon = {
  telegram: Send,
  whatsapp: MessageCircle,
}

export function ChatListItem({
  id,
  name,
  preview,
  channel,
  unread,
  selected,
  onSelect,
}: ChatListItemProps) {
  const Icon = channelIcon[channel]
  return (
    <button
      type="button"
      data-testid={`chat-item-${id}`}
      onClick={() => onSelect(id)}
      className={cn(
        'flex w-full items-start gap-3 px-3 py-3 text-left transition-colors',
        selected ? 'bg-[#e8f1fd]' : 'hover:bg-[#f4f6f8]',
      )}
    >
      <Avatar className="h-9 w-9 shrink-0">
        <AvatarFallback className="bg-[#dfe7f1] text-sm font-semibold text-[#33506b]">
          {name.slice(0, 1)}
        </AvatarFallback>
      </Avatar>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-sm font-medium text-[#1f2933]">{name}</span>
          <Icon className="h-3.5 w-3.5 shrink-0 text-[#8a96a3]" aria-hidden />
        </div>
        <p className="mt-0.5 line-clamp-2 text-xs text-[#6b7785]">{preview}</p>
      </div>
      {unread && (
        <Badge
          data-testid={`unread-${id}`}
          className="mt-1 h-5 min-w-5 shrink-0 rounded-full bg-[#2f80ed] px-1.5 text-[11px] text-white"
        >
          1
        </Badge>
      )}
    </button>
  )
}
