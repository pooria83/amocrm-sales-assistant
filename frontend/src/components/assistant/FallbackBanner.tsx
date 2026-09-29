import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { useI18n } from '@/i18n'

export interface FallbackBannerProps {
  grounded: boolean
}

// Grey banner shown whenever the reply did NOT come from the LLM
// (no KB match → honest template; validation failed twice → template).
export function FallbackBanner({ grounded }: FallbackBannerProps) {
  const { t } = useI18n()
  return (
    <Alert
      data-testid="fallback-banner"
      className="border-[#d5dbe2] bg-[#eef1f4]"
    >
      <AlertTitle className="text-sm text-[#55606b]">
        {grounded ? t('templateBanner') : t('noMatch')}
      </AlertTitle>
      <AlertDescription className="text-xs text-[#6b7785]">
        {grounded ? t('templateHint') : t('noMatchHint')}
      </AlertDescription>
    </Alert>
  )
}
