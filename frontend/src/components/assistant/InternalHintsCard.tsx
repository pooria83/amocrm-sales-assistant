import { Lock, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { HintItem } from '@/components/assistant/HintItem'
import type { InternalSalesHints } from '@/lib/types'
import { useI18n } from '@/i18n'

export interface InternalHintsCardProps {
  hints: InternalSalesHints
  onAddNote: (text: string) => void
}

export function composeNote(hints: InternalSalesHints): string {
  const lines: string[] = []
  for (const item of [...hints.upsell, ...hints.cross_sell]) {
    lines.push(`• ${item.title}: ${item.reason} — ${item.talking_point}`)
  }
  if (hints.notes) lines.push(hints.notes)
  return lines.join('\n')
}

// Contract 2 (internal-only) only — it never receives the customer reply.
export function InternalHintsCard({ hints, onAddNote }: InternalHintsCardProps) {
  const { t } = useI18n()
  const hasContent = hints.upsell.length > 0 || hints.cross_sell.length > 0 || Boolean(hints.notes)
  const note = composeNote(hints)

  return (
    <Card data-testid="internal-hints" className="border-[#f0d48a] bg-[#fdf9ec]">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="flex items-center gap-1.5 text-sm font-semibold text-[#6b5b2a]">
          <Lock className="h-3.5 w-3.5" aria-hidden />
          {t('hintsLabel')}
        </CardTitle>
        <span className="rounded-full bg-[#f5e9c8] px-2 py-0.5 text-[10px] font-medium text-[#8a7434]">
          {t('internalOnly')}
        </span>
      </CardHeader>
      <CardContent className="space-y-2">
        {!hasContent && (
          <p data-testid="no-candidates" className="text-xs italic text-[#8a7434]">
            {t('noCandidates')}
          </p>
        )}
        {hints.upsell.length > 0 && (
          <ul className="space-y-2">
            {hints.upsell.map((item) => (
              <HintItem key={item.id} variant="upsell" item={item} />
            ))}
          </ul>
        )}
        {hints.cross_sell.length > 0 && (
          <ul className="space-y-2">
            {hints.cross_sell.map((item) => (
              <HintItem key={item.id} variant="cross-sell" item={item} />
            ))}
          </ul>
        )}
        {hints.notes && (
          <p
            data-testid="hint-notes"
            className="rounded-md border border-dashed border-[#e3cf96] bg-white/60 p-2.5 text-xs leading-relaxed text-[#6b5b2a]"
          >
            {hints.notes}
          </p>
        )}
        {hasContent && (
          <div className="flex justify-end pt-1">
            <Button
              size="sm"
              variant="outline"
              data-testid="add-note"
              onClick={() => onAddNote(note)}
              className="h-7 gap-1.5 border-[#e3cf96] bg-white text-xs text-[#6b5b2a] hover:bg-[#fdf6e3]"
            >
              <Plus className="h-3.5 w-3.5" />
              {t('addNote')}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
