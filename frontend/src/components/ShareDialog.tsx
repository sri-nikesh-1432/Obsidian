import { useCallback, useEffect, useState } from 'react'
import { Check, Copy, Link2, Mail, ShieldOff, Timer, Trash2 } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { DocumentMeta, Share } from '../lib/types'
import { expiryLabel, formatDate } from '../lib/format'
import { Badge, Button, ChoiceRow, Field, Input, Modal, Spinner } from './ui'
import { useToast } from '../store/toast'

interface Props {
  open: boolean
  doc: DocumentMeta | null
  onClose: () => void
}

type ExpiryChoice = '3600' | '86400' | '604800' | 'custom' | 'never'

const EXPIRY_LABELS: Record<ExpiryChoice, string> = {
  '3600': '1 hour',
  '86400': '24 hours',
  '604800': '7 days',
  custom: 'Custom',
  never: 'Never',
}

export default function ShareDialog({ open, doc, onClose }: Props) {
  const toast = useToast()
  const [mode, setMode] = useState<'link' | 'restricted'>('link')
  const [permission, setPermission] = useState<'viewer' | 'editor'>('viewer')
  const [expiry, setExpiry] = useState<ExpiryChoice>('86400')
  const [customAt, setCustomAt] = useState('')
  const [grantee, setGrantee] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [created, setCreated] = useState<Share | null>(null)
  const [copied, setCopied] = useState(false)
  const [shares, setShares] = useState<Share[] | null>(null)

  const loadShares = useCallback(async () => {
    if (!doc) return
    try {
      const data = await api<{ shares: Share[] }>(`/documents/${doc.document_id}/shares`)
      setShares(data.shares)
    } catch {
      setShares([])
    }
  }, [doc])

  useEffect(() => {
    if (open && doc) {
      setMode('link')
      setPermission('viewer')
      setExpiry('86400')
      setCustomAt('')
      setGrantee('')
      setError('')
      setCreated(null)
      setCopied(false)
      void loadShares()
    }
  }, [open, doc, loadShares])

  if (!doc) return null

  const create = async () => {
    setBusy(true)
    setError('')
    try {
      let expires_in: number | null = null
      if (expiry === 'custom') {
        const ts = new Date(customAt).getTime()
        if (Number.isNaN(ts) || ts <= Date.now()) {
          setError('Choose a future expiry time.')
          setBusy(false)
          return
        }
        expires_in = Math.floor((ts - Date.now()) / 1000)
      } else if (expiry !== 'never') {
        expires_in = Number(expiry)
      }

      const body: Record<string, unknown> = { mode, permission, expires_in }
      if (mode === 'restricted') body.grantee_email = grantee.trim()

      const data = await api<{ share: Share }>(`/documents/${doc.document_id}/shares`, {
        method: 'POST',
        body,
      })
      setCreated(data.share)
      toast.push('success', mode === 'link' ? 'Secure link created.' : 'Document shared with recipient.')
      void loadShares()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create the share.')
    } finally {
      setBusy(false)
    }
  }

  const revoke = async (shareId: string) => {
    try {
      await api(`/shares/${shareId}`, { method: 'DELETE' })
      toast.push('success', 'Link revoked — access ends immediately.')
      if (created?.share_id === shareId) setCreated(null)
      void loadShares()
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Revoke failed.')
    }
  }

  const copy = async () => {
    if (!created?.url) return
    const full = `${window.location.origin}${created.url}`
    try {
      await navigator.clipboard.writeText(full)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.push('info', full)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Share document"
      subtitle={doc.filename}
      width="max-w-xl"
    >
      {!created ? (
        <div className="space-y-5">
          <div>
            <span className="text-[13px] font-medium text-graphite">Access</span>
            <div className="mt-2">
              <ChoiceRow
                name="mode"
                value={mode}
                onChange={setMode}
                options={[
                  { value: 'restricted', label: 'Restricted', description: 'Only a specific OBSIDIAN account you name.' },
                  { value: 'link', label: 'Anyone with this link', description: 'High-entropy token, hashed at rest, expirable and revocable.' },
                ]}
              />
            </div>
          </div>

          {mode === 'restricted' && (
            <Field label="Recipient email" htmlFor="grantee" hint="Must have an OBSIDIAN account.">
              <Input
                id="grantee"
                type="email"
                required
                placeholder="classmate@university.edu"
                value={grantee}
                onChange={(e) => setGrantee(e.target.value)}
              />
            </Field>
          )}

          <div>
            <span className="text-[13px] font-medium text-graphite">Permission</span>
            <div className="mt-2">
              <ChoiceRow
                name="permission"
                value={permission}
                onChange={setPermission}
                options={[
                  { value: 'viewer', label: 'Viewer', description: 'Can view and download.' },
                  {
                    value: 'editor',
                    label: 'Editor',
                    description: doc.is_text
                      ? 'Can also edit this text document through the link.'
                      : 'Only available for text documents.',
                  },
                ]}
              />
            </div>
          </div>

          <div>
            <span className="text-[13px] font-medium text-graphite">Link expiration</span>
            <div className="mt-2 grid grid-cols-2 sm:grid-cols-5 gap-2">
              {(Object.keys(EXPIRY_LABELS) as ExpiryChoice[]).map((choice) => (
                <button
                  key={choice}
                  type="button"
                  onClick={() => setExpiry(choice)}
                  className={`rounded-xl border px-2 py-2.5 text-[13px] transition-all focus-ring ${
                    expiry === choice
                      ? 'border-cognac/70 bg-cognac/6 text-cognac-deep shadow-[0_0_0_3px_rgba(162,96,58,0.10)]'
                      : 'border-beige bg-white/70 text-graphite hover:border-faint/60'
                  }`}
                >
                  {EXPIRY_LABELS[choice]}
                </button>
              ))}
            </div>
            {expiry === 'custom' && (
              <input
                type="datetime-local"
                className="field mt-2"
                value={customAt}
                onChange={(e) => setCustomAt(e.target.value)}
              />
            )}
          </div>

          {permission === 'editor' && doc.is_text && (
            <div className="rounded-xl bg-warning/8 border border-warning/25 px-4 py-2.5 text-[13px] text-warning">
              Anyone with this link will be able to edit the document's content.
            </div>
          )}

          {error && (
            <div className="rounded-xl border border-danger/25 bg-danger/6 px-4 py-3 text-sm text-danger">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button
              variant="accent"
              loading={busy}
              disabled={mode === 'restricted' && !grantee.trim()}
              onClick={create}
            >
              {mode === 'link' ? 'Create secure link' : 'Share with recipient'}
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-5">
          <div className="rounded-2xl border border-success/25 bg-success/6 p-4">
            <div className="text-sm font-semibold text-success flex items-center gap-2">
              <ShieldOff size={15} /> {created.mode === 'link' ? 'Secure link created' : 'Recipient granted access'}
            </div>
            {created.url ? (
              <>
                <div className="mt-3 flex items-center gap-2">
                  <input readOnly className="field text-[13px] font-mono" value={`${window.location.origin}${created.url}`} />
                  <Button variant={copied ? 'soft' : 'primary'} onClick={copy} className="shrink-0">
                    {copied ? <Check size={14} /> : <Copy size={14} />}
                    {copied ? 'Copied' : 'Copy'}
                  </Button>
                </div>
                <p className="text-xs text-muted mt-2">
                  The raw token is shown exactly once — only its SHA-256 hash is stored.
                </p>
              </>
            ) : (
              <p className="text-sm text-graphite mt-2">
                Shared with <span className="font-medium">{created.grantee_email}</span> as {created.permission}.
              </p>
            )}
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted">
              <Badge tone="accent">{created.permission}</Badge>
              <Badge tone={created.expires_at ? 'warning' : 'neutral'} icon={<Timer size={11} />}>
                {created.expires_at ? `Expires ${formatDate(created.expires_at)}` : 'Never expires'}
              </Badge>
            </div>
          </div>

          <div className="flex justify-between gap-2">
            <Button variant="danger" onClick={() => revoke(created.share_id)}>
              <Trash2 size={14} /> Revoke link
            </Button>
            <div className="flex gap-2">
              <Button variant="soft" onClick={() => setCreated(null)}>Create another</Button>
              <Button variant="primary" onClick={onClose}>Done</Button>
            </div>
          </div>
        </div>
      )}

      {/* existing shares */}
      <div className="mt-6 pt-5 border-t hairline">
        <div className="eyebrow flex items-center gap-2">
          <Link2 size={12} /> Existing shares
        </div>
        {shares === null ? (
          <Spinner label="Loading shares…" />
        ) : shares.length === 0 ? (
          <p className="text-sm text-muted mt-3">No shares yet. This document is visible only to you.</p>
        ) : (
          <div className="mt-3 space-y-2">
            {shares.map((s) => (
              <div key={s.share_id} className="rounded-xl border hairline bg-white/70 px-3.5 py-2.5 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[13px] font-medium flex items-center gap-2">
                    {s.mode === 'link' ? <Link2 size={12} className="text-cognac" /> : <Mail size={12} className="text-cognac" />}
                    {s.mode === 'link' ? 'Anyone with link' : s.grantee_email || 'Restricted'}
                  </div>
                  <div className="text-xs text-faint">
                    {s.permission} · created {formatDate(s.created_at)} · {s.access_count} accesses
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <Badge tone={s.status === 'active' ? 'success' : s.status === 'expired' ? 'warning' : 'danger'}>
                    {s.status === 'active' && s.expires_at ? expiryLabel(s.expires_at) : s.status}
                  </Badge>
                  {s.status === 'active' && (
                    <button
                      onClick={() => revoke(s.share_id)}
                      className="btn btn-danger btn-sm focus-ring"
                      title="Revoke"
                    >
                      Revoke
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Modal>
  )
}
