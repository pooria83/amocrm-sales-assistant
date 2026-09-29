import { Progress } from '@/components/ui/progress'
import { useI18n } from '@/i18n'

export interface SeatsUsageProps {
  seatsUsed: number
  seatLimit: number
}

export function SeatsUsage({ seatsUsed, seatLimit }: SeatsUsageProps) {
  const { t } = useI18n()
  const hasLimit = seatLimit > 0
  const percent = hasLimit ? Math.round((seatsUsed / seatLimit) * 100) : 0
  const nearLimit = hasLimit && percent >= 90

  return (
    <div data-testid="seats-usage" className="space-y-1.5">
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-[#8a96a3]">{t('seats')}</span>
        <span
          className={`font-medium tabular-nums ${nearLimit ? 'text-[#d64545]' : 'text-[#1f2933]'}`}
        >
          {hasLimit ? `${seatsUsed} / ${seatLimit}` : `${seatsUsed}`}
        </span>
      </div>
      <Progress
        value={percent}
        className={nearLimit ? 'h-1.5 [&>div]:bg-[#e05252]' : 'h-1.5 [&>div]:bg-[#2f80ed]'}
      />
    </div>
  )
}
