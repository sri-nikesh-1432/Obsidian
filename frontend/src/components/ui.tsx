import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { useEffect } from 'react'
import { X } from 'lucide-react'

/* --------------------------------------------------------------- layout */

export function Card({
  children,
  className = '',
  glass = false,
}: {
  children: ReactNode
  className?: string
  glass?: boolean
}) {
  return <div className={`${glass ? 'glass' : 'panel-solid'} rounded-2xl ${className}`}>{children}</div>
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string
  subtitle?: string
  actions?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 mb-6">
      <div>
        <h1 className="text-2xl font-semibold text-editorial">{title}</h1>
        {subtitle && <p className="text-sm text-muted mt-1">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

/* -------------------------------------------------------------- buttons */

interface BtnProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'accent' | 'soft' | 'ghost' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
}

export function Button({
  variant = 'soft',
  size = 'md',
  loading = false,
  className = '',
  children,
  disabled,
  ...rest
}: BtnProps) {
  const sizeCls = size === 'sm' ? 'btn-sm' : size === 'lg' ? 'btn-lg' : ''
  return (
    <button
      className={`btn btn-${variant} ${sizeCls} focus-ring ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <span className="spinner" style={{ borderTopColor: 'currentColor', borderColor: 'currentColor', borderTopStyle: 'solid' }} />}
      {children}
    </button>
  )
}

/* --------------------------------------------------------------- fields */

export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
}: {
  label: string
  hint?: string
  error?: string
  children: ReactNode
  htmlFor?: string
}) {
  return (
    <label className="block" htmlFor={htmlFor}>
      <span className="text-[13px] font-medium text-graphite">{label}</span>
      <div className="mt-1.5">{children}</div>
      {hint && !error && <span className="text-xs text-faint mt-1 block">{hint}</span>}
      {error && <span className="text-xs text-danger mt-1 block">{error}</span>}
    </label>
  )
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  const { className = '', ...rest } = props
  return <input className={`field focus-ring ${className}`} {...rest} />
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const { className = '', ...rest } = props
  return <textarea className={`field focus-ring resize-y ${className}`} {...rest} />
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  const { className = '', children, ...rest } = props
  return (
    <select className={`field focus-ring ${className}`} {...rest}>
      {children}
    </select>
  )
}

export function ChoiceRow<T extends string>({
  value,
  options,
  onChange,
  name,
}: {
  value: T
  options: { value: T; label: string; description?: string }[]
  onChange: (value: T) => void
  name: string
}) {
  return (
    <div className="grid gap-2" role="radiogroup" aria-label={name}>
      {options.map((opt) => {
        const active = opt.value === value
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(opt.value)}
            className={`text-left rounded-xl border px-4 py-3 transition-all focus-ring ${
              active
                ? 'border-cognac/60 bg-cognac/5 shadow-[0_0_0_3px_rgba(162,96,58,0.10)]'
                : 'border-beige bg-white/70 hover:border-faint/60'
            }`}
          >
            <div className="flex items-center gap-2.5">
              <span
                className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                  active ? 'border-cognac' : 'border-beige-dark'
                }`}
              >
                {active && <span className="w-2 h-2 rounded-full bg-cognac" />}
              </span>
              <span className="text-sm font-medium text-charcoal">{opt.label}</span>
            </div>
            {opt.description && (
              <p className="text-xs text-muted mt-1 pl-6.5">{opt.description}</p>
            )}
          </button>
        )
      })}
    </div>
  )
}

/* --------------------------------------------------------------- badges */

export function Badge({
  tone = 'neutral',
  children,
  icon,
}: {
  tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'accent'
  children: ReactNode
  icon?: ReactNode
}) {
  const tones: Record<string, string> = {
    neutral: 'bg-beige/70 text-graphite border-beige-dark',
    success: 'bg-success/10 text-success border-success/25',
    warning: 'bg-warning/10 text-warning border-warning/25',
    danger: 'bg-danger/10 text-danger border-danger/25',
    info: 'bg-info/10 text-info border-info/25',
    accent: 'bg-cognac/10 text-cognac-deep border-cognac/25',
  }
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11.5px] font-medium ${tones[tone]}`}
    >
      {icon}
      {children}
    </span>
  )
}

/* --------------------------------------------------------------- states */

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 text-muted py-8 justify-center">
      <span className="spinner" />
      {label && <span className="text-sm">{label}</span>}
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string
  description: string
  action?: ReactNode
  icon?: ReactNode
}) {
  return (
    <div className="panel-solid rounded-2xl py-14 px-6 text-center">
      {icon && <div className="mx-auto mb-4 w-12 h-12 rounded-2xl bg-ivory-deep flex items-center justify-center text-cognac">{icon}</div>}
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="text-sm text-muted mt-2 max-w-md mx-auto leading-relaxed">{description}</p>
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="panel-solid rounded-2xl py-10 px-6 text-center border-danger/25">
      <h3 className="text-base font-semibold text-danger">Something went wrong</h3>
      <p className="text-sm text-muted mt-2">{message}</p>
      {onRetry && (
        <Button variant="soft" size="sm" className="mt-4" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- modal */

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  width = 'max-w-lg',
}: {
  open: boolean
  onClose: () => void
  title: string
  subtitle?: string
  children: ReactNode
  width?: string
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4 sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className="absolute inset-0 bg-charcoal/25 backdrop-blur-[3px]" onClick={onClose} />
      <div className={`glass relative w-full ${width} rounded-2xl p-6 fade-up max-h-[88vh] overflow-y-auto scrollbar-thin`}>
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h2 className="text-lg font-semibold text-editorial">{title}</h2>
            {subtitle && <p className="text-sm text-muted mt-0.5">{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            className="text-faint hover:text-charcoal transition-colors focus-ring rounded-md p-1"
            aria-label="Close dialog"
          >
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  danger = false,
  loading = false,
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  danger?: boolean
  loading?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <Modal open={open} onClose={onCancel} title={title} width="max-w-md">
      <p className="text-sm text-muted leading-relaxed">{message}</p>
      <div className="flex justify-end gap-2 mt-6">
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button variant={danger ? 'danger' : 'primary'} loading={loading} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  )
}

/* ---------------------------------------------------------------- stats */

export function StatCard({
  label,
  value,
  hint,
  icon,
}: {
  label: string
  value: ReactNode
  hint?: string
  icon?: ReactNode
}) {
  return (
    <div className="panel-solid rounded-2xl p-4 sm:p-5">
      <div className="flex items-center justify-between">
        <span className="eyebrow">{label}</span>
        {icon && <span className="text-faint">{icon}</span>}
      </div>
      <div className="mt-2 text-2xl font-semibold text-editorial tabular-nums">{value}</div>
      {hint && <div className="text-xs text-muted mt-1">{hint}</div>}
    </div>
  )
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
  disabled,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
  description?: string
  disabled?: boolean
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <div className="text-sm font-medium text-charcoal">{label}</div>
        {description && <div className="text-xs text-muted mt-0.5 max-w-md">{description}</div>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative w-11 h-6 rounded-full transition-colors shrink-0 focus-ring ${
          checked ? 'bg-cognac' : 'bg-beige-dark'
        } ${disabled ? 'opacity-50' : ''}`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${
            checked ? 'translate-x-5' : ''
          }`}
        />
      </button>
    </div>
  )
}
