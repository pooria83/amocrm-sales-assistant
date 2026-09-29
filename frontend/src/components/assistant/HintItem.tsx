import { Badge } from '@/components/ui/badge'
import type { HintItem as HintItemModel } from '@/lib/types'
import { useI18n } from '@/i18n'

export interface HintItemProps {
  variant: 'upsell' | 'cross-sell'
  item: HintItemModel
}

export function HintItem({ variant, item }: HintItemProps) {
  const { t } = useI18n()
  return (
    <li data-testid={`hint-${item.id}`} className="rounded-md border border-[#f0d48a] bg-[#fffdf6] p-2.5">
      <div className="flex items-center gap-2">
        <Badge
          variant={variant === 'upsell' ? 'default' : 'secondary'}
          className={variant === 'upsell' ? 'bg-[#2f80ed] text-[10px] text-white' : 'text-[10px]'}
        >
          {variant === 'upsell' ? t('upsellSection') : t('crossSellSection')}
        </Badge>
        <span className="text-sm font-semibold text-[#4f4420]">{item.title}</span>
      </div>
      <p className="mt-1.5 text-xs leading-relaxed text-[#6b5b2a]">{item.reason}</p>
      <p className="mt-1.5 text-xs leading-relaxed text-[#8a7434]">
        <span className="font-semibold">{t('talkingPoint')}:</span> {item.talking_point}
      </p>
    </li>
  )
}
