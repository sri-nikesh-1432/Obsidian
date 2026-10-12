import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowLeft, MessagesSquare, Plus, RefreshCw, Send, Trash2, UserPlus, Users, X,
} from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../store/auth'
import { useToast } from '../store/toast'
import type { GroupDetail, GroupMember, GroupMessage, GroupSummary } from '../lib/types'
import { initials, relativeTime } from '../lib/format'
import {
  Badge, Button, ConfirmDialog, EmptyState, ErrorState, Field, Input, Modal,
  PageHeader, Spinner, Textarea,
} from '../components/ui'

export default function Groups() {
  const { user } = useAuth()
  const toast = useToast()
  const isFaculty = user?.role === 'faculty'

  const [groups, setGroups] = useState<GroupSummary[] | null>(null)
  const [loadError, setLoadError] = useState(false)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [detail, setDetail] = useState<GroupDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const [createOpen, setCreateOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [saving, setSaving] = useState(false)

  const [addCode, setAddCode] = useState('')
  const [addBusy, setAddBusy] = useState(false)

  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)

  const [confirmDelete, setConfirmDelete] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  const loadGroups = useCallback(async () => {
    setLoadError(false)
    try {
      const data = await api<{ groups: GroupSummary[]; total: number }>('/groups')
      setGroups(data.groups)
      setActiveId((cur) => cur ?? data.groups[0]?.group_id ?? null)
    } catch (err) {
      setLoadError(true)
      toast.push('error', err instanceof ApiError ? err.message : 'Could not load groups.')
    }
  }, [toast])

  const loadDetail = useCallback(async (id: string) => {
    setDetailLoading(true)
    try {
      setDetail(await api<GroupDetail>(`/groups/${encodeURIComponent(id)}`))
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Could not open the group.')
      setDetail(null)
    } finally {
      setDetailLoading(false)
    }
  }, [toast])

  useEffect(() => { void loadGroups() }, [loadGroups])
  useEffect(() => {
    if (activeId) void loadDetail(activeId)
    else setDetail(null)
  }, [activeId, loadDetail])

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [detail?.messages.length, activeId])

  const active = useMemo(
    () => groups?.find((g) => g.group_id === activeId) ?? null,
    [groups, activeId],
  )

  const createGroup = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newName.trim()) return
    setSaving(true)
    try {
      const data = await api<{ group: GroupSummary }>('/groups', {
        method: 'POST',
        body: { name: newName.trim(), description: newDesc.trim() },
      })
      setCreateOpen(false)
      setNewName('')
      setNewDesc('')
      await loadGroups()
      setActiveId(data.group.group_id)
      toast.push('success', 'Group created.')
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Could not create the group.')
    } finally {
      setSaving(false)
    }
  }

  const addMember = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!activeId || !addCode.trim()) return
    setAddBusy(true)
    try {
      const data = await api<{ added: boolean }>(`/groups/${encodeURIComponent(activeId)}/members`, {
        method: 'POST',
        body: { student_id: addCode.trim().toUpperCase() },
      })
      setAddCode('')
      toast.push('success', data.added ? 'Student added.' : 'Student was already in the group.')
      await Promise.all([loadDetail(activeId), loadGroups()])
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Could not add that student.')
    } finally {
      setAddBusy(false)
    }
  }

  const removeMember = async (member: GroupMember) => {
    if (!activeId) return
    try {
      await api(`/groups/${encodeURIComponent(activeId)}/members/${encodeURIComponent(member.student_id)}`, {
        method: 'DELETE',
      })
      toast.push('success', `${member.full_name || member.student_id} removed.`)
      await Promise.all([loadDetail(activeId), loadGroups()])
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Could not remove that student.')
    }
  }

  const sendMessage = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!activeId || !draft.trim()) return
    const body = draft.trim()
    setSending(true)
    try {
      const data = await api<{ message: GroupMessage }>(
        `/groups/${encodeURIComponent(activeId)}/messages`,
        { method: 'POST', body: { body } },
      )
      setDraft('')
      setDetail((cur) => (cur ? { ...cur, messages: [...cur.messages, data.message] } : cur))
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Message not sent.')
    } finally {
      setSending(false)
    }
  }

  const deleteGroup = async () => {
    if (!activeId) return
    setSaving(true)
    try {
      await api(`/groups/${encodeURIComponent(activeId)}`, { method: 'DELETE' })
      setConfirmDelete(false)
      setActiveId(null)
      setDetail(null)
      toast.push('success', 'Group deleted.')
      await loadGroups()
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Could not delete the group.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fade-up">
      <PageHeader
        title="Groups"
        subtitle={
          isFaculty
            ? 'Create a group, add students by their code, and message the whole class at once.'
            : 'Groups your teachers have added you to. Read updates and reply to the class.'
        }
        actions={
          isFaculty ? (
            <Button variant="accent" onClick={() => setCreateOpen(true)}>
              <Plus size={15} /> New group
            </Button>
          ) : undefined
        }
      />

      {groups === null && !loadError && <Spinner label="Loading groups…" />}
      {loadError && <ErrorState message="We couldn't load your groups." onRetry={() => void loadGroups()} />}

      {groups !== null && groups.length === 0 && (
        <EmptyState
          icon={<Users size={22} />}
          title={isFaculty ? 'No groups yet' : 'You are not in any group'}
          description={
            isFaculty
              ? 'Create your first group to message a set of students at once.'
              : 'When a teacher adds you to a group, it will appear here.'
          }
          action={
            isFaculty ? (
              <Button variant="primary" onClick={() => setCreateOpen(true)}>
                <Plus size={15} /> Create a group
              </Button>
            ) : undefined
          }
        />
      )}

      {groups !== null && groups.length > 0 && (
        <div className="grid lg:grid-cols-[280px_1fr] gap-4">
          {/* group list */}
          <div className={`panel-solid rounded-2xl p-2 ${activeId ? 'hidden lg:block' : ''}`}>
            <div className="flex items-center justify-between px-3 pt-2 pb-1">
              <span className="eyebrow flex items-center gap-1.5"><Users size={12} /> Your groups</span>
              <button
                onClick={() => void loadGroups()}
                className="text-faint hover:text-charcoal p-1 rounded-md focus-ring"
                aria-label="Refresh groups"
              >
                <RefreshCw size={13} />
              </button>
            </div>
            <div className="space-y-1 max-h-[70vh] overflow-y-auto scrollbar-thin">
              {groups.map((g) => (
                <button
                  key={g.group_id}
                  onClick={() => setActiveId(g.group_id)}
                  className={`w-full text-left rounded-xl px-3 py-2.5 focus-ring transition-colors ${
                    g.group_id === activeId ? 'bg-charcoal text-[#f5f0e6]' : 'hover:bg-white/70'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium truncate">{g.name}</span>
                    <span className={`text-[11px] ${g.group_id === activeId ? 'text-[#f5f0e6]/70' : 'text-faint'}`}>
                      {g.member_count}
                    </span>
                  </div>
                  <div className={`text-[11px] truncate mt-0.5 ${g.group_id === activeId ? 'text-[#f5f0e6]/60' : 'text-faint'}`}>
                    {g.role === 'owner' ? 'You teach this' : `by ${g.owner_name || 'teacher'}`}
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* detail */}
          <div className={activeId ? '' : 'hidden lg:block'}>
            {detailLoading && !detail && <Spinner label="Opening group…" />}
            {active && detail && (
              <div className="glass rounded-2xl overflow-hidden">
                <div className="p-5 border-b hairline">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <button
                        className="lg:hidden text-faint hover:text-charcoal mb-1 flex items-center gap-1 text-[12px] focus-ring rounded"
                        onClick={() => { setActiveId(null); setDetail(null) }}
                      >
                        <ArrowLeft size={12} /> All groups
                      </button>
                      <div className="flex items-center gap-2 flex-wrap">
                        <h2 className="text-lg font-semibold text-editorial truncate">{detail.group.name}</h2>
                        <Badge tone={detail.group.role === 'owner' ? 'accent' : 'info'}>
                          {detail.group.role === 'owner' ? 'Teacher' : 'Member'}
                        </Badge>
                        <Badge tone="neutral" icon={<Users size={11} />}>{detail.group.member_count}</Badge>
                      </div>
                      {detail.group.description && (
                        <p className="text-sm text-muted mt-1">{detail.group.description}</p>
                      )}
                      {detail.group.role !== 'owner' && (
                        <p className="text-xs text-faint mt-1">Led by {detail.group.owner_name || 'your teacher'}</p>
                      )}
                    </div>
                    {isFaculty && detail.group.role === 'owner' && (
                      <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)}>
                        <Trash2 size={14} /> Delete
                      </Button>
                    )}
                  </div>

                  {/* roster */}
                  <div className="mt-4">
                    <div className="eyebrow">Students</div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {detail.members.length === 0 && (
                        <span className="text-sm text-muted">No students added yet.</span>
                      )}
                      {detail.members.map((m) => (
                        <span
                          key={m.user_id}
                          className="inline-flex items-center gap-1.5 rounded-full bg-white/80 border hairline pl-1 pr-2 py-0.5 text-[12.5px]"
                        >
                          <span className="w-5 h-5 rounded-full bg-cognac/12 text-cognac-deep text-[9px] font-semibold flex items-center justify-center">
                            {initials(m.full_name || m.student_id)}
                          </span>
                          {m.full_name || m.student_id}
                          {isFaculty && detail.group.role === 'owner' && (
                            <button
                              onClick={() => void removeMember(m)}
                              className="text-faint hover:text-danger focus-ring rounded"
                              aria-label={`Remove ${m.full_name || m.student_id}`}
                            >
                              <X size={11} />
                            </button>
                          )}
                        </span>
                      ))}
                    </div>

                    {isFaculty && detail.group.role === 'owner' && (
                      <form onSubmit={addMember} className="mt-3 flex gap-2 max-w-md">
                        <Input
                          value={addCode}
                          onChange={(e) => setAddCode(e.target.value.toUpperCase())}
                          placeholder="OBS-4F2K-9QW7ZP"
                          className="font-mono tracking-wider"
                          maxLength={20}
                          aria-label="Student code to add"
                        />
                        <Button type="submit" variant="soft" loading={addBusy} disabled={!addCode.trim()}>
                          <UserPlus size={14} /> Add
                        </Button>
                      </form>
                    )}
                  </div>
                </div>

                {/* chat */}
                <div className="px-5 pt-4">
                  <div className="eyebrow flex items-center gap-1.5"><MessagesSquare size={12} /> Group chat</div>
                </div>
                <div ref={scrollRef} className="px-5 py-3 space-y-3 max-h-[42vh] overflow-y-auto scrollbar-thin">
                  {detail.messages.length === 0 && (
                    <p className="text-sm text-muted py-4 text-center">
                      No messages yet. Say hello to the group.
                    </p>
                  )}
                  {detail.messages.map((m) => {
                    const mine = m.sender_id === user?.user_id
                    return (
                      <div key={m.message_id} className={`flex gap-2.5 ${mine ? 'flex-row-reverse' : ''}`}>
                        <span className="w-7 h-7 rounded-full bg-cognac/12 text-cognac-deep text-[10px] font-semibold flex items-center justify-center shrink-0">
                          {initials(m.sender_name || '?')}
                        </span>
                        <div className={`max-w-[78%] ${mine ? 'items-end' : ''}`}>
                          <div className={`text-[11px] text-faint mb-0.5 ${mine ? 'text-right' : ''}`}>
                            {mine ? 'You' : m.sender_name}
                            {m.sender_role === 'faculty' && !mine ? ' · Teacher' : ''}
                            {' · '}{relativeTime(m.created_at)}
                          </div>
                          <div
                            className={`rounded-2xl px-3.5 py-2 text-[13.5px] whitespace-pre-wrap break-words ${
                              mine ? 'bg-charcoal text-[#f5f0e6]' : 'bg-white/85 border hairline'
                            }`}
                          >
                            {m.body}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
                <form onSubmit={sendMessage} className="p-4 border-t hairline flex gap-2">
                  <Textarea
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    rows={1}
                    maxLength={2000}
                    placeholder="Message the group…"
                    className="flex-1 min-h-[42px] max-h-32"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        void sendMessage(e)
                      }
                    }}
                  />
                  <Button type="submit" variant="primary" loading={sending} disabled={!draft.trim()}>
                    <Send size={15} />
                  </Button>
                </form>
              </div>
            )}
          </div>
        </div>
      )}

      {/* create group modal */}
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="New group"
        subtitle="Give the group a name, then add students by their code."
      >
        <form onSubmit={createGroup} className="space-y-4">
          <Field label="Group name" htmlFor="gname">
            <Input
              id="gname"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="CS-301 · Information Security"
              maxLength={80}
              autoFocus
            />
          </Field>
          <Field label="Description (optional)" htmlFor="gdesc">
            <Textarea
              id="gdesc"
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              rows={3}
              maxLength={400}
              placeholder="What this group is for…"
            />
          </Field>
          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="ghost" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button type="submit" variant="primary" loading={saving} disabled={!newName.trim()}>
              Create group
            </Button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete this group?"
        message="The group, its student list, and all chat messages will be permanently removed."
        confirmLabel="Delete group"
        danger
        loading={saving}
        onConfirm={() => void deleteGroup()}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  )
}
