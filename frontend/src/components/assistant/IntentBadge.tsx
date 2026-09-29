import { Badge } from '@/components/ui/badge'
import type { Intent } from '@/lib/types'
import { useI18n } from '@/i18n'

export interface IntentBadgeProps {
  intent: Intent
}

export function IntentBadge({ intent }: IntentBadgeProps) {
  const { t, intentLabel } = useI18n()
  if (intent === 'other') return null
  return (
    <Badge
      data-testid="badge-intent"
      variant="outline"
      className="border-[#e1e5ea] bg-[#f4f6f8] text-[11px] font-medium text-[#6b7785]"
    >
      {t('intent')}: {intentLabel(intent)}
    </Badge>
  )
}
