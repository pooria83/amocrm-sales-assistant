import { LanguageToggle } from '@/components/common/LanguageToggle'
import type { Channel } from '@/lib/types'
import { useI18n } from '@/i18n'

export interface ConversationHeaderProps {
  contact: string
  channel: Channel
}

export function ConversationHeader({ contact, channel }: ConversationHeaderProps) {
  const { t } = useI18n()
  return (
    <header
      data-testid="conversation-header"
      className="flex h-12 shrink-0 items-center justify-between border-b border-[#e1e5ea] bg-white px-4"
    >
      <div className="flex items-baseline gap-2">
        <span className="text-sm font-semibold text-[#1f2933]">{contact}</span>
        <span className="text-xs text-[#8a96a3]">{t(`channel_${channel}`)}</span>
      </div>
      <LanguageToggle />
    </header>
  )
}
