/**
 * Lightweight SVG/CSS charts — no third-party dependency.
 *
 * Everything is inline SVG (donuts) or flex divs (bars) so the bundle stays
 * tiny and the visuals inherit the OBSIDIAN palette.
 */

export const CHART_COLORS = [
  '#a2603a', // cognac
  '#5d7a61', // success / sage
  '#5b6c7c', // info / slate
  '#b08432', // warning / amber
  '#8a4f2f', // cognac-deep
  '#c98d63', // cognac-soft
  '#a1524a', // danger
  '#6b4a33', // walnut
  '#7d7466', // muted
  '#d9c8a9', // champagne
]

export interface Series {
  label: string
  value: number
  color: string
}

export function colorAt(i: number): string {
  return CHART_COLORS[i % CHART_COLORS.length]
}

/** Turn a `{ label: value }` record into coloured, sorted series. */
export function seriesFrom(
  record: Record<string, number | undefined>,
  limit = 8,
): Series[] {
  return Object.entries(record)
    .filter(([, v]) => (v ?? 0) > 0)
    .sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))
    .slice(0, limit)
    .map(([label, value], i) => ({ label, value: value ?? 0, color: colorAt(i) }))
}

export function DonutChart({
  data,
  size = 176,
  thickness = 22,
  centerValue,
  centerLabel,
}: {
  data: Series[]
  size?: number
  thickness?: number
  centerValue?: string | number
  centerLabel?: string
}) {
  const total = data.reduce((sum, d) => sum + d.value, 0)
  const radius = (size - thickness) / 2
  const circumference = 2 * Math.PI * radius
  const cx = size / 2
  const cy = size / 2
  let offset = 0

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={centerLabel ?? 'chart'}
    >
      <g transform={`rotate(-90 ${cx} ${cy})`}>
        <circle
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          stroke="rgba(27,24,21,0.06)"
          strokeWidth={thickness}
        />
        {total > 0 &&
          data.map((d, i) => {
            const fraction = d.value / total
            const length = fraction * circumference
            const dash = `${length} ${circumference - length}`
            const el = (
              <circle
                key={`${d.label}-${i}`}
                cx={cx}
                cy={cy}
                r={radius}
                fill="none"
                stroke={d.color}
                strokeWidth={thickness}
                strokeDasharray={dash}
                strokeDashoffset={-offset}
                strokeLinecap="butt"
              >
                <title>{`${d.label}: ${d.value} (${Math.round(fraction * 100)}%)`}</title>
              </circle>
            )
            offset += length
            return el
          })}
      </g>
      {centerValue !== undefined && (
        <text
          x={cx}
          y={cy - 2}
          textAnchor="middle"
          dominantBaseline="middle"
          style={{ fontSize: 24, fontWeight: 600, fill: '#1b1815' }}
        >
          {centerValue}
        </text>
      )}
      {centerLabel && (
        <text
          x={cx}
          y={cy + 18}
          textAnchor="middle"
          dominantBaseline="middle"
          style={{ fontSize: 10.5, letterSpacing: '0.06em', fill: '#7d7466' }}
        >
          {centerLabel}
        </text>
      )}
    </svg>
  )
}

export function ChartLegend({ data, showZero = false }: { data: Series[]; showZero?: boolean }) {
  const items = showZero ? data : data.filter((d) => d.value > 0)
  if (items.length === 0) {
    return <p className="text-xs text-faint">No data yet.</p>
  }
  return (
    <ul className="space-y-1.5">
      {items.map((d, i) => (
        <li key={`${d.label}-${i}`} className="flex items-center justify-between gap-3 text-[13px]">
          <span className="flex items-center gap-2 min-w-0">
            <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: d.color }} />
            <span className="text-graphite truncate capitalize">{d.label.replace(/_/g, ' ')}</span>
          </span>
          <span className="font-semibold tabular-nums text-charcoal">{d.value}</span>
        </li>
      ))}
    </ul>
  )
}

export function BarChart({
  data,
  color = CHART_COLORS[0],
  height = 120,
}: {
  data: { label: string; value: number }[]
  color?: string
  height?: number
}) {
  const max = Math.max(1, ...data.map((d) => d.value))
  return (
    <div>
      <div className="flex items-end gap-[3px]" style={{ height }}>
        {data.map((d, i) => (
          <div key={i} className="flex-1 flex items-end h-full" title={`${d.label}: ${d.value}`}>
            <div
              className="w-full rounded-t transition-all"
              style={{
                height: `${(d.value / max) * 100}%`,
                minHeight: d.value > 0 ? 3 : 0,
                background: color,
                opacity: d.value > 0 ? 1 : 0.18,
              }}
            />
          </div>
        ))}
      </div>
      <div className="flex gap-[3px] mt-1.5">
        {data.map((d, i) => (
          <div key={i} className="flex-1 text-center text-[8.5px] text-faint leading-none">
            {i % 2 === 0 || data.length <= 8 ? d.label : ''}
          </div>
        ))}
      </div>
    </div>
  )
}

export function ChartCard({
  title,
  action,
  children,
}: {
  title: string
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="panel-solid rounded-2xl p-5">
      <div className="flex items-center justify-between">
        <div className="eyebrow">{title}</div>
        {action}
      </div>
      <div className="mt-4">{children}</div>
    </div>
  )
}
