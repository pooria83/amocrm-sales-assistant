import { Skeleton } from '@/components/ui/skeleton'
import { useI18n } from '@/i18n'

export interface LoadingStateProps {
  phase: 'retrieving' | 'generating'
}

export function LoadingState({ phase }: LoadingStateProps) {
  const { t } = useI18n()
  return (
    <div data-testid="assistant-loading" className="space-y-2.5" aria-busy="true">
      <p className="text-xs text-[#8a96a3]">
        {phase === 'retrieving' ? t('loadingRetrieval') : t('loadingGeneration')}
      </p>
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-16 w-full" />
      <Skeleton className="h-16 w-full" />
    </div>
  )
}
