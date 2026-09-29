import { useState } from 'react'
import { Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { useI18n } from '@/i18n'

export interface ComposerProps {
  onSend: (mode: 'chat' | 'note', text: string) => void
}

// Tabs «Чат» | «Примечание»: same destination split as AmoCRM —
// a chat message goes to the customer, a note stays internal.
export function Composer({ onSend }: ComposerProps) {
  const { t } = useI18n()
  const [mode, setMode] = useState<'chat' | 'note'>('chat')
  const [text, setText] = useState('')

  const send = () => {
    const value = text.trim()
    if (!value) return
    onSend(mode, value)
    setText('')
  }

  return (
    <div data-testid="composer" className="border-t border-[#e1e5ea] bg-white px-4 pb-4 pt-2">
      <Tabs
        value={mode}
        onValueChange={(value) => setMode(value as 'chat' | 'note')}
        className="w-full"
      >
        <TabsList className="mb-2 h-8 bg-[#f4f6f8]">
          <TabsTrigger
            value="chat"
            data-testid="tab-chat"
            className="h-7 px-3 text-xs data-[state=active]:bg-white"
          >
            {t('tabChat')}
          </TabsTrigger>
          <TabsTrigger
            value="note"
            data-testid="tab-note"
            className="h-7 px-3 text-xs data-[state=active]:bg-white"
          >
            {t('tabNote')}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="chat" className="mt-0 space-y-2">
          <Textarea
            data-testid="composer-input"
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                send()
              }
            }}
            placeholder={t('chatPlaceholder')}
            rows={2}
            className="resize-none text-sm"
          />
          <div className="flex justify-end">
            <Button
              size="sm"
              data-testid="composer-send"
              onClick={send}
              disabled={!text.trim()}
              className="h-7 gap-1.5 bg-[#2f80ed] text-white hover:bg-[#2569cc]"
            >
              <Send className="h-3.5 w-3.5" />
              {t('sendToChat')}
            </Button>
          </div>
        </TabsContent>
        <TabsContent value="note" className="mt-0 space-y-2">
          <Textarea
            data-testid="composer-note-input"
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                send()
              }
            }}
            placeholder={t('notePlaceholder')}
            rows={2}
            className="resize-none text-sm"
          />
          <div className="flex justify-end">
            <Button
              size="sm"
              variant="outline"
              data-testid="composer-note-send"
              onClick={send}
              disabled={!text.trim()}
              className="h-7 gap-1.5 border-[#e3cf96] text-xs text-[#6b5b2a] hover:bg-[#fdf6e3]"
            >
              {t('addNote')}
            </Button>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
