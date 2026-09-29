export interface ScoreBarProps {
  score: number
  threshold: number
}

// Bar width = min(score / (2 × threshold), 1); the tick marks the threshold,
// which sits at exactly 50% of that scale (CONTEXT §16).
export function ScoreBar({ score, threshold }: ScoreBarProps) {
  const width = Math.min(score / (2 * threshold), 1) * 100
  return (
    <div className="relative h-1.5 w-full overflow-visible rounded-full bg-[#e8ecf1]">
      <div
        className="h-full rounded-full bg-[#2f80ed]"
        style={{ width: `${width}%` }}
        data-testid="score-bar-fill"
      />
      <span
        className="absolute -top-1 h-3.5 w-0.5 bg-[#f2994a]"
        style={{ left: '50%' }}
        aria-label="threshold"
      />
    </div>
  )
}
