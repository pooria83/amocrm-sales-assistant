import { Lock } from 'lucide-react'
import { useI18n } from '@/i18n'

export interface InternalNoteProps {
  text: string
}

// Mirrors how AmoCRM separates internal notes from customer messages.
export function InternalNote({ text }: InternalNoteProps) {
  const { t } = useI18n()
  return (
    <div
      data-testid="internal-note"
      className="mx-auto flex w-[85%] items-start gap-2 rounded-lg border border-[#f0d48a] bg-[#fdf6e3] px-3 py-2 text-sm text-[#6b5b2a]"
    >
      <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <div className="min-w-0">
        <span className="mr-2 text-xs font-semibold uppercase tracking-wide text-[#a48631]">
          {t('noteAdded')}
        </span>
        <span className="break-words text-[#4f4420]">{text}</span>
      </div>
    </div>
  )
}
