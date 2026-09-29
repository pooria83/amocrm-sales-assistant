import { Badge } from '@/components/ui/badge'
import type { Lang, LangSource } from '@/lib/types'
import { useI18n } from '@/i18n'

export interface LanguageBadgeProps {
  lang: Lang
  source?: LangSource
}

export function LanguageBadge({ lang, source }: LanguageBadgeProps) {
  const { t } = useI18n()
  return (
    <Badge
      data-testid="badge-language"
      variant="outline"
      className="gap-1 border-[#cfe0f5] bg-[#f2f7fe] text-[11px] font-medium text-[#336099]"
    >
      {t('language')}: {lang.toUpperCase()}
      {source && <span className="font-normal text-[#8a96a3]">({t(`langSource_${source}`)})</span>}
    </Badge>
  )
}
