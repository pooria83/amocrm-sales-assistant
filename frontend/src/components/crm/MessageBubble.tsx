import { cn } from '@/lib/utils'

export interface MessageBubbleProps {
  role: 'customer' | 'manager'
  text: string
}

export function MessageBubble({ role, text }: MessageBubbleProps) {
  const isCustomer = role === 'customer'
  return (
    <div className={cn('flex', isCustomer ? 'justify-start' : 'justify-end')}>
      <div
        data-testid={isCustomer ? 'bubble-customer' : 'bubble-manager'}
        className={cn(
          'max-w-[75%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed',
          isCustomer
            ? 'rounded-bl-sm border border-[#e1e5ea] bg-white text-[#1f2933]'
            : 'rounded-br-sm bg-[#d8e9ff] text-[#1f2933]',
        )}
      >
        {text}
      </div>
    </div>
  )
}
