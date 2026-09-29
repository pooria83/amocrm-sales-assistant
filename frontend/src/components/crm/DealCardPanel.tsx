import { DealField } from '@/components/crm/DealField'
import { SeatsUsage } from '@/components/crm/SeatsUsage'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import type { DealContext } from '@/lib/types'
import { useI18n } from '@/i18n'

export interface DealCardPanelProps {
  deal: DealContext
}

// Right column: the deal card. This data feeds the rule engine.
export function DealCardPanel({ deal }: DealCardPanelProps) {
  const { t } = useI18n()
  return (
    <aside
      data-testid="deal-card"
      className="w-[280px] shrink-0 border-l border-[#e1e5ea] bg-white"
    >
      <div className="flex h-12 items-center border-b border-[#e1e5ea] px-4">
        <h2 className="text-sm font-semibold text-[#1f2933]">{t('dealCard')}</h2>
      </div>
      <Card className="m-3 border-[#e1e5ea] shadow-none">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold text-[#1f2933]">{deal.company}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2.5">
          <DealField label={t('contact')} value={deal.contact} />
          <DealField label={t('company')} value={deal.company} />
          <DealField label={t('channel')} value={t(`channel_${deal.channel}`)} />
          <DealField label={t('plan')} value={t(`plan_${deal.plan}`)} />
          <DealField label={t('stage')} value={t(`stage_${deal.stage}`)} />
          <Separator />
          <SeatsUsage seatsUsed={deal.seats_used} seatLimit={deal.seat_limit} />
        </CardContent>
      </Card>
    </aside>
  )
}
