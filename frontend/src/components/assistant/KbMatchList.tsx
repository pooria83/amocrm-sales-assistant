import { KbMatchItem } from '@/components/assistant/KbMatchItem'
import type { Match } from '@/lib/types'
import { useI18n } from '@/i18n'

export interface KbMatchListProps {
  matches: Match[]
  threshold: number
}

export function KbMatchList({ matches, threshold }: KbMatchListProps) {
  const { t } = useI18n()
  if (matches.length === 0) return null
  return (
    <section data-testid="kb-matches" className="space-y-1.5">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-[#8a96a3]">
        {t('kbMatches')}
      </h3>
      <ul className="space-y-1.5">
        {matches.map((match) => (
          <KbMatchItem key={match.id} match={match} threshold={threshold} />
        ))}
      </ul>
    </section>
  )
}
