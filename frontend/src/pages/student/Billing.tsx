import { useCallback, useEffect, useState } from 'react'
import { BadgeCheck, Check, HardDrive, Lock, Sparkles } from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import type { BillingHistoryRow, BillingOrder, StorageStatus } from '../../lib/types'
import { formatBytes, formatDateShort } from '../../lib/format'
import { openCheckout, razorpayAvailable } from '../../lib/razorpay'
import { Badge, Button, Card, ErrorState, PageHeader, Spinner } from '../../components/ui'
import StorageMeter from '../../components/StorageMeter'
import { useAuth } from '../../store/auth'
import { useToast } from '../../store/toast'

function inr(amount: number): string {
  return `₹${amount.toLocaleString('en-IN')}`
}

export default function Billing() {
  const { user, refresh } = useAuth()
  const toast = useToast()
  const [status, setStatus] = useState<StorageStatus | null>(null)
  const [orders, setOrders] = useState<BillingHistoryRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyTier, setBusyTier] = useState<number | null>(null)

  const load = useCallback(async () => {
    setError('')
    try {
      const [s, h] = await Promise.all([
        api<StorageStatus>('/billing/status'),
        api<{ orders: BillingHistoryRow[] }>('/billing/history'),
      ])
      setStatus(s)
      setOrders(h.orders)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load your storage plan.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const creditOrder = async (orderId: string, payment: Record<string, string>) => {
    const res = await api<{ ok: boolean; credited?: boolean; already_paid?: boolean }>(
      '/billing/verify',
      { method: 'POST', body: { razorpay_order_id: orderId, ...payment } },
    )
    if (res.credited || res.already_paid) {
      toast.push('success', 'Storage added to your account.')
    }
    await Promise.all([load(), refresh()])
  }

  const upgrade = async () => {
    if (!status?.next_plan) return
    setBusyTier(status.next_plan.tier)
    try {
      const order = await api<BillingOrder>('/billing/orders', { method: 'POST', body: {} })

      // No Razorpay key configured (local demo): the server simulates the
      // charge only in explicit dev mode.
      if (order.simulated) {
        await creditOrder(order.order_id, { razorpay_payment_id: 'simulated', razorpay_signature: 'dev' })
        return
      }

      if (!razorpayAvailable()) {
        throw new ApiError(0, 'CHECKOUT_UNAVAILABLE', 'The payment window could not be opened. Please retry.')
      }

      const opened = openCheckout({
        key: order.key_id,
        amount: order.amount,
        currency: order.currency,
        name: 'OBSIDIAN',
        description: `${order.plan.total_gb} GB storage`,
        order_id: order.order_id,
        prefill: { name: user?.profile?.full_name, email: user?.email },
        theme: { color: '#a2603a' },
        handler: (response) => {
          void creditOrder(order.order_id, {
            razorpay_payment_id: response.razorpay_payment_id,
            razorpay_signature: response.razorpay_signature,
          }).catch((err) =>
            toast.push('error', err instanceof ApiError ? err.message : 'Payment could not be confirmed.'),
          )
        },
        modal: {
          ondismiss: () => setBusyTier(null),
        },
      })
      if (!opened) throw new Error('checkout')
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Could not start the upgrade.')
    } finally {
      setBusyTier(null)
    }
  }

  if (loading) return <Spinner label="Checking your storage plan…" />
  if (error || !status) return <ErrorState message={error || 'Storage plan unavailable.'} onRetry={load} />

  const plans = status.plans ?? []
  const paidOrders = orders.filter((o) => o.status === 'paid')

  return (
    <div className="space-y-6">
      <PageHeader
        title="Storage & billing"
        subtitle="Your vault starts at 5 GB free. Every upgrade adds another 10 GB, permanently."
        actions={
          <Badge tone={status.exceeded ? 'danger' : status.near_limit ? 'warning' : 'success'}
            icon={<HardDrive size={12} />}>
            {status.total_gb} GB plan
          </Badge>
        }
      />

      <StorageMeter storage={status} onUpgrade={() => void upgrade()} />

      {/* current + next plan spotlight */}
      <div className="grid lg:grid-cols-3 gap-5">
        <Card glass className="p-6 lg:col-span-2">
          <div className="flex items-center gap-2 text-[11px] font-semibold tracking-[0.28em] text-cognac">
            <Sparkles size={13} /> STORAGE UPGRADES
          </div>
          <h2 className="text-lg font-semibold mt-3">
            {status.next_plan
              ? `Add 10 GB for ${inr(status.next_plan.price_inr)}`
              : 'You are on the highest plan'}
          </h2>
          <p className="text-sm text-muted mt-1.5 leading-relaxed">
            Pay once through Razorpay and the space stays with your account forever. Delete files
            any time — your entitlement never shrinks.
          </p>

          {status.next_plan && (
            <div className="mt-5 flex flex-wrap items-center gap-4">
              <div className="rounded-2xl border hairline bg-white/70 px-5 py-4">
                <div className="text-[11px] uppercase tracking-widest text-faint">New balance</div>
                <div className="text-3xl font-semibold tracking-tight mt-1">
                  {status.next_plan.total_gb}<span className="text-lg text-muted"> GB</span>
                </div>
              </div>
              <div className="rounded-2xl border hairline bg-white/70 px-5 py-4">
                <div className="text-[11px] uppercase tracking-widest text-faint">One-time</div>
                <div className="text-3xl font-semibold tracking-tight mt-1">
                  {inr(status.next_plan.price_inr)}
                </div>
              </div>
              <Button variant="accent" size="lg" loading={busyTier === status.next_plan.tier}
                onClick={() => void upgrade()}>
                Pay with Razorpay
              </Button>
            </div>
          )}

          <p className="mt-4 text-xs text-faint flex items-center gap-2">
            <Lock size={12} className="text-success" />
            Payments run in Razorpay {status.payments?.configured ? 'test/live' : 'simulated (dev)'} mode.
            Your card details never touch OBSIDIAN.
          </p>
        </Card>

        <Card glass className="p-6">
          <div className="text-[11px] font-semibold tracking-[0.28em] text-faint">USAGE</div>
          <div className="mt-3 space-y-3 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-muted">Used</span>
              <span className="font-medium tabular-nums">{formatBytes(status.used_bytes)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted">Entitlement</span>
              <span className="font-medium tabular-nums">{status.total_gb} GB</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted">Remaining</span>
              <span className={`font-medium tabular-nums ${status.exceeded ? 'text-danger' : ''}`}>
                {formatBytes(status.remaining_bytes)}
              </span>
            </div>
            <div className="h-px bg-beige/70" />
            <div className="flex items-center justify-between">
              <span className="text-muted">Purchases</span>
              <span className="font-medium tabular-nums">{paidOrders.length}</span>
            </div>
          </div>
        </Card>
      </div>

      {/* plan ladder */}
      <div>
        <h2 className="text-sm font-semibold text-graphite mb-3">Plan ladder</h2>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {plans.map((plan) => {
            const current = plan.tier === status.tier
            const isNext = plan.tier === status.next_plan?.tier
            return (
              <div
                key={plan.tier}
                className={`glass rounded-2xl p-5 relative transition-transform ${
                  isNext ? 'ring-2 ring-cognac/40 -translate-y-0.5' : ''
                }`}
              >
                {current && (
                  <span className="absolute top-4 right-4">
                    <Badge tone="success" icon={<Check size={11} />}>Current</Badge>
                  </span>
                )}
                {isNext && !current && (
                  <span className="absolute top-4 right-4">
                    <Badge tone="accent">Next</Badge>
                  </span>
                )}
                <div className="text-[11px] uppercase tracking-[0.22em] text-faint">
                  {plan.tier === 0 ? 'Included' : `Tier ${plan.tier}`}
                </div>
                <div className="text-3xl font-semibold tracking-tight mt-2">
                  {plan.total_gb}<span className="text-base text-muted"> GB</span>
                </div>
                <div className="text-sm text-muted mt-1">
                  {plan.tier === 0 ? 'Free forever' : `${inr(plan.price_inr)} one-time`}
                </div>
                {plan.tier > 0 && (
                  <div className="text-xs text-faint mt-2">adds {plan.added_gb} GB</div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* history */}
      <Card glass className="p-6">
        <h2 className="text-sm font-semibold text-graphite mb-4 flex items-center gap-2">
          <BadgeCheck size={15} className="text-success" /> Payment history
        </h2>
        {orders.length === 0 ? (
          <p className="text-sm text-muted">No purchases yet — your free 5 GB is active.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wider text-faint">
                  <th className="pb-2 font-medium">Plan</th>
                  <th className="pb-2 font-medium">Amount</th>
                  <th className="pb-2 font-medium">Status</th>
                  <th className="pb-2 font-medium">Date</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => (
                  <tr key={o.order_id} className="border-t hairline">
                    <td className="py-2.5">{o.plan} · {o.total_gb} GB</td>
                    <td className="py-2.5 tabular-nums">{inr(o.amount_inr)}</td>
                    <td className="py-2.5">
                      <Badge tone={o.status === 'paid' ? 'success' : o.status === 'failed' ? 'danger' : 'neutral'}>
                        {o.status}
                      </Badge>
                    </td>
                    <td className="py-2.5 text-muted">{formatDateShort(o.paid_at || o.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
