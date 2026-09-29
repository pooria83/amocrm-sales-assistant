import { CheckCircle2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { Validation } from '@/lib/types'
import { useI18n } from '@/i18n'

export interface ValidationBadgeProps {
  validation?: Validation
}

// Shows the "✓ Numbers verified" badge only when the numbers really went
// through the guardrail on an LLM reply (not on a template fallback).
export function ValidationBadge({ validation }: ValidationBadgeProps) {
  const { t } = useI18n()
  if (!validation || validation.fallback_used || !validation.numbers_ok) return null
  return (
    <Badge
      data-testid="badge-numbers"
      variant="outline"
      className="gap-1 border-[#b7e0c6] bg-[#f0faf3] text-[11px] font-medium text-[#2f8042]"
    >
      <CheckCircle2 className="h-3 w-3" />
      {t('numbersVerified')}
    </Badge>
  )
}
