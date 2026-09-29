import { ScoreBar } from '@/components/assistant/ScoreBar'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import type { Match } from '@/lib/types'
import { useI18n } from '@/i18n'

export interface KbMatchItemProps {
  match: Match
  threshold: number
}

export function KbMatchItem({ match, threshold }: KbMatchItemProps) {
  const { t } = useI18n()
  return (
    <li
      data-testid={`kb-match-${match.id}`}
      className="rounded-md border border-[#e1e5ea] bg-white px-2.5 py-2"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-xs font-medium text-[#1f2933]">{match.title}</span>
        <span className="shrink-0 text-xs tabular-nums text-[#6b7785]">
          {match.score.toFixed(2)}
        </span>
      </div>
      <div className="mt-1.5 flex items-center gap-2">
        <ScoreBar score={match.score} threshold={threshold} />
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="cursor-help text-[10px] text-[#8a96a3]" aria-label={t('matchedTerms')}>
              ?
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-[240px] text-xs">
            <p className="font-semibold">{t('matchedTerms')}</p>
            <p className="mt-0.5 break-words">{match.matched_terms.join(', ') || '—'}</p>
            <p className="mt-1 tabular-nums">
              {t('threshold')}: {threshold}
            </p>
          </TooltipContent>
        </Tooltip>
      </div>
    </li>
  )
}
