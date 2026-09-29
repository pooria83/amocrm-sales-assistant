import { RefreshCw } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n'

export interface ErrorStateProps {
  onRetry: () => void
}

export function ErrorState({ onRetry }: ErrorStateProps) {
  const { t } = useI18n()
  return (
    <Alert data-testid="assistant-error" variant="destructive" className="border-[#f3c2c2] bg-[#fdf1f1]">
      <AlertTitle className="text-sm">{t('errorText')}</AlertTitle>
      <AlertDescription className="flex justify-end">
        <Button
          size="sm"
          variant="outline"
          data-testid="retry"
          onClick={onRetry}
          className="h-7 gap-1.5 text-xs"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          {t('retry')}
        </Button>
      </AlertDescription>
    </Alert>
  )
}
