import { useEffect, useState } from 'react'
import { Check, Copy, Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import type { CustomerReply } from '@/lib/types'
import { useI18n } from '@/i18n'

export interface CustomerReplyCardProps {
  reply: CustomerReply
  onSendToChat: (text: string) => void
}

// Contract 1 (customer-facing) only — it never receives internal hints.
export function CustomerReplyCard({ reply, onSendToChat }: CustomerReplyCardProps) {
  const { t } = useI18n()
  const [draft, setDraft] = useState(reply.text)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    setDraft(reply.text)
    setCopied(false)
  }, [reply.text])

  const copy = () => {
    void navigator.clipboard.writeText(draft).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <Card data-testid="customer-reply" className="border-[#cfe0f5] bg-white">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-semibold text-[#1f2933]">{t('replyLabel')}</CardTitle>
        <Button
          variant="ghost"
          size="sm"
          data-testid="copy-reply"
          onClick={copy}
          className="h-7 gap-1.5 px-2 text-xs text-[#6b7785]"
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? t('copied') : t('copyReply')}
        </Button>
      </CardHeader>
      <CardContent className="space-y-2.5">
        <Textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={t('replyPlaceholder')}
          rows={4}
          className="resize-none text-sm leading-relaxed"
        />
        <div className="flex justify-end">
          <Button
            size="sm"
            data-testid="send-to-chat"
            onClick={() => onSendToChat(draft)}
            disabled={!draft.trim()}
            className="gap-1.5 bg-[#2f80ed] text-white hover:bg-[#2569cc]"
          >
            <Send className="h-3.5 w-3.5" />
            {t('sendToChat')}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
