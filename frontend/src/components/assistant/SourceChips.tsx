import { Badge } from '@/components/ui/badge'
import { useI18n } from '@/i18n'

export interface SourceChipsProps {
  ids: string[]
  titles: Record<string, string>
}

// «Источники / Sources» — the KB entries the model was given (§4a:
// kb_refs are filled by the backend, never by the LLM).
export function SourceChips({ ids, titles }: SourceChipsProps) {
  const { t } = useI18n()
  if (ids.length === 0) return null
  return (
    <div data-testid="source-chips" className="flex flex-wrap items-center gap-1.5">
      <span className="text-[11px] font-medium text-[#8a96a3]">{t('sources')}:</span>
      {ids.map((id) => (
        <Badge
          key={id}
          data-testid={`source-chip-${id}`}
          variant="outline"
          className="border-[#cfe0f5] bg-[#f2f7fe] px-1.5 py-0 font-normal text-[#336099]"
        >
          {titles[id] ?? id}
        </Badge>
      ))}
    </div>
  )
}
