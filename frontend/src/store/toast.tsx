import { createContext, useCallback, useContext, useState } from 'react'
import type { ReactNode } from 'react'
import { CheckCircle2, CircleAlert, Info, X } from 'lucide-react'

type ToastKind = 'success' | 'error' | 'info'

interface Toast {
  id: number
  kind: ToastKind
  message: string
}

interface ToastState {
  push: (kind: ToastKind, message: string) => void
}

const ToastContext = createContext<ToastState | null>(null)

let nextId = 1

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const push = useCallback((kind: ToastKind, message: string) => {
    const id = nextId++
    setToasts((prev) => [...prev, { id, kind, message }])
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4600)
  }, [])

  const dismiss = (id: number) => setToasts((prev) => prev.filter((t) => t.id !== id))

  const icon = (kind: ToastKind) =>
    kind === 'success' ? (
      <CheckCircle2 size={16} className="text-success" />
    ) : kind === 'error' ? (
      <CircleAlert size={16} className="text-danger" />
    ) : (
      <Info size={16} className="text-info" />
    )

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="fixed bottom-6 right-6 z-[70] flex flex-col gap-2 items-end">
        {toasts.map((t) => (
          <div
            key={t.id}
            className="glass rounded-xl px-4 py-3 flex items-start gap-3 max-w-sm fade-up"
            role="status"
          >
            <span className="mt-0.5">{icon(t.kind)}</span>
            <p className="text-sm text-graphite leading-snug">{t.message}</p>
            <button
              onClick={() => dismiss(t.id)}
              className="text-faint hover:text-graphite transition-colors focus-ring rounded"
              aria-label="Dismiss"
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastState {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside ToastProvider')
  return ctx
}
