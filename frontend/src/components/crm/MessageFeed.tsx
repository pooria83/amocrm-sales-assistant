import { InternalNote } from '@/components/crm/InternalNote'
import { MessageBubble } from '@/components/crm/MessageBubble'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { FeedMessage } from '@/data/scenarios'
import { useEffect, useRef } from 'react'

export interface MessageFeedProps {
  messages: FeedMessage[]
}

export function MessageFeed({ messages }: MessageFeedProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length])

  return (
    <ScrollArea data-testid="message-feed" className="min-h-0 flex-1 bg-[#f4f6f8]">
      <div className="flex flex-col gap-2.5 px-4 py-4">
        {messages.map((message) =>
          message.role === 'note' ? (
            <InternalNote key={message.id} text={message.text} />
          ) : (
            <MessageBubble key={message.id} role={message.role} text={message.text} />
          ),
        )}
        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  )
}
