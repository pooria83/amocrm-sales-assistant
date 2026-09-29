export interface DealFieldProps {
  label: string
  value: string
}

export function DealField({ label, value }: DealFieldProps) {
  return (
    <div className="flex items-baseline justify-between gap-2 text-xs">
      <span className="shrink-0 text-[#8a96a3]">{label}</span>
      <span className="truncate text-right font-medium text-[#1f2933]">{value}</span>
    </div>
  )
}
