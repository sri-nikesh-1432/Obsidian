import type { StorageStatus } from '../lib/types'
import { formatBytes } from '../lib/format'

/**
 * Storage entitlement meter. Apple-style: a single soft capsule with a
 * gradient fill, the exact figures beneath, and an amber/red tone as the
 * account approaches or passes its ceiling.
 */
export default function StorageMeter({
  storage,
  compact = false,
  onUpgrade,
}: {
  storage: StorageStatus
  compact?: boolean
  onUpgrade?: () => void
}) {
  const percent = Math.max(0, Math.min(100, storage.percent_used || 0))
  const tone = storage.exceeded
    ? 'from-danger to-danger/70'
    : storage.near_limit
      ? 'from-warning to-cognac-soft'
      : 'from-cognac-soft to-cognac'
  const tierLabel = storage.tier === 0 ? 'Free plan' : `Plan · ${storage.total_gb} GB`

  return (
    <div className={compact ? 'px-1 py-0.5' : 'glass rounded-2xl p-5'}>
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-medium text-graphite">Storage</span>
          <span className="text-[10.5px] uppercase tracking-[0.18em] text-faint">{tierLabel}</span>
        </div>
        <span className="text-[13px] text-muted tabular-nums">
          {formatBytes(storage.used_bytes)}
          <span className="text-faint"> / {storage.total_gb} GB</span>
        </span>
      </div>

      <div
        className="mt-3 h-2.5 w-full rounded-full bg-ivory-deep/80 overflow-hidden ring-1 ring-inset ring-white/60"
        role="progressbar"
        aria-valuenow={Math.round(percent)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Storage used"
      >
        <div
          className={`h-full rounded-full bg-gradient-to-r ${tone} transition-[width] duration-700 ease-out`}
          style={{ width: `${percent}%` }}
        />
      </div>

      <div className="mt-2.5 flex items-center justify-between text-xs">
        <span className={storage.exceeded ? 'text-danger' : 'text-muted'}>
          {storage.exceeded
            ? 'Storage full — upgrade to keep uploading'
            : `${formatBytes(storage.remaining_bytes)} free`}
        </span>
        {storage.next_plan && onUpgrade && (
          <button
            onClick={onUpgrade}
            className="text-cognac-deep font-medium hover:underline focus-ring rounded"
          >
            Upgrade to {storage.next_plan.total_gb} GB →
          </button>
        )}
      </div>
    </div>
  )
}
