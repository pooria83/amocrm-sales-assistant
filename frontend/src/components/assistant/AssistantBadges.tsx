import { IntentBadge } from '@/components/assistant/IntentBadge'
import { LanguageBadge } from '@/components/assistant/LanguageBadge'
import { ValidationBadge } from '@/components/assistant/ValidationBadge'
import type { Intent, Lang, LangSource, Validation } from '@/lib/types'

export interface AssistantBadgesProps {
  lang: Lang
  langSource: LangSource
  intent: Intent
  validation?: Validation
}

export function AssistantBadges({ lang, langSource, intent, validation }: AssistantBadgesProps) {
  return (
    <div data-testid="assistant-badges" className="flex flex-wrap items-center gap-1.5">
      <LanguageBadge lang={lang} source={langSource} />
      <IntentBadge intent={intent} />
      <ValidationBadge validation={validation} />
    </div>
  )
}
