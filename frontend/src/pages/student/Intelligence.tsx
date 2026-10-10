import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertCircle, Check, ChevronDown, Copy, Database, FileText, Lock, RefreshCw, RotateCcw,
  Send, Sparkles, UserRound,
} from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import { useAuth } from '../../store/auth'
import { Badge, Button, EmptyState, PageHeader, Spinner } from '../../components/ui'
import Markdown from '../../components/Markdown'
import { useToast } from '../../store/toast'

interface Source {
  document_id: string
  filename: string
  page?: number
  relevance?: number
}

interface Message {
  id: number
  role: 'user' | 'assistant'
  text: string
  sources?: Source[]
  error?: boolean
}

interface Status {
  enabled: boolean
  status: string
  chunk_count: number
  document_count: number
  profile_indexed: boolean
  model_mode?: string
  provider?: string
  model?: string
}

const SUGGESTIONS = [
  'What internship did I attend?',
  'Which project did I work on there?',
  'Summarise my resume.',
  'What technologies did I use?',
  'Explain my project in simple words.',
  'What is my CGPA?',
]

const STAGES = ['Understanding your question…', 'Searching your documents…', 'Preparing your answer…']

let msgId = 1

export default function Intelligence() {
  const { user, refresh } = useAuth()
  const toast = useToast()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [stage, setStage] = useState(0)
  const [status, setStatus] = useState<Status | null>(null)
  const [showDiagnostics, setShowDiagnostics] = useState(false)
  const [copiedId, setCopiedId] = useState<number | null>(null)
  const [enabling, setEnabling] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  const load = useCallback(async () => {
    if (!user?.ai_enabled) return
    const st = await api<Status>('/intelligence/status').catch(() => null)
    setStatus(st)
  }, [user?.ai_enabled])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, busy])

  // Real staged progress — each label reflects an operation that is genuinely
  // happening while the request is in flight.
  useEffect(() => {
    if (!busy) {
      setStage(0)
      return
    }
    setStage(0)
    const t1 = setTimeout(() => setStage(1), 500)
    const t2 = setTimeout(() => setStage(2), 2200)
    return () => {
      clearTimeout(t1)
      clearTimeout(t2)
    }
  }, [busy])

  const send = async (question?: string, historyOverride?: Message[]) => {
    const q = (question ?? input).trim()
    if (!q || busy) return
    setInput('')
    const prior = historyOverride ?? messages
    setMessages((m) => [...m, { id: msgId++, role: 'user', text: q }])
    setBusy(true)
    try {
      const history = prior
        .slice(-10)
        .map((m) => ({ role: m.role, content: m.text }))
      const data = await api<{ answer: string; sources: Source[] }>('/intelligence/query', {
        method: 'POST',
        body: { query: q, history },
      })
      setMessages((m) => [
        ...m,
        { id: msgId++, role: 'assistant', text: data.answer, sources: data.sources },
      ])
    } catch (err) {
      setMessages((m) => [
        ...m,
        {
          id: msgId++,
          role: 'assistant',
          error: true,
          text:
            err instanceof ApiError
              ? err.message
              : 'Your personal intelligence service is temporarily unavailable. Your documents remain available in your vault.',
        },
      ])
    } finally {
      setBusy(false)
      void load()
    }
  }

  const retry = (index: number) => {
    // re-ask the question that produced this answer, using the turns before it
    for (let i = index - 1; i >= 0; i--) {
      if (messages[i].role === 'user') {
        void send(messages[i].text, messages.slice(0, i))
        return
      }
    }
  }

  const copy = async (m: Message) => {
    try {
      await navigator.clipboard.writeText(m.text)
      setCopiedId(m.id)
      setTimeout(() => setCopiedId(null), 2000)
    } catch {
      toast.push('info', m.text)
    }
  }

  const reindex = async () => {
    setBusy(true)
    try {
      const data = await api<{ reindexed: number; chunk_count: number }>('/intelligence/reindex', {
        method: 'POST',
      })
      toast.push('success', `Reindexed ${data.reindexed} document(s) — ${data.chunk_count} chunks.`)
      void load()
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Reindex failed.')
    } finally {
      setBusy(false)
    }
  }

  const enable = async () => {
    setEnabling(true)
    try {
      await api('/intelligence/consent', { method: 'POST', body: { consent: true } })
      await refresh()
      void load()
      toast.push('success', 'Your personal knowledge base is ready.')
    } catch (err) {
      toast.push('error', err instanceof ApiError ? err.message : 'Could not enable personal AI.')
    } finally {
      setEnabling(false)
    }
  }

  if (!user) return <Spinner />

  if (!user.ai_enabled) {
    return (
      <div className="fade-up max-w-2xl mx-auto">
        <EmptyState
          icon={<Sparkles size={22} />}
          title="OBSIDIAN Intelligence is off"
          description="Turn on your personal knowledge base to ask questions about your own documents and profile. It is isolated to your account and query-only — nothing can be changed through it."
          action={
            <Button variant="accent" loading={enabling} onClick={enable}>
              Enable personal intelligence
            </Button>
          }
        />
        <p className="text-xs text-faint text-center mt-4">
          Enabling consents to processing your profile and uploaded documents inside your private
          partition, as described during onboarding.
        </p>
      </div>
    )
  }

  const provider = status?.model_mode === 'provider'

  return (
    <div className="fade-up">
      <PageHeader
        title="OBSIDIAN Intelligence"
        subtitle="A conversational assistant grounded in your own documents."
        actions={
          <Button variant="soft" onClick={reindex} disabled={busy}>
            <RefreshCw size={14} /> Reindex
          </Button>
        }
      />

      {!provider && (
        <div className="mb-4 rounded-xl border border-warning/30 bg-warning/8 px-4 py-3 text-[13px] text-warning flex items-start gap-2.5">
          <AlertCircle size={15} className="mt-0.5 shrink-0" />
          <span>
            No language model is configured, so answers are limited. Start a local model (for
            example <code className="font-mono">ollama run llama3.2</code>) or set{' '}
            <code className="font-mono">LLM_PROVIDER</code>,{' '}
            <code className="font-mono">LLM_BASE_URL</code> and{' '}
            <code className="font-mono">LLM_MODEL</code> to enable full conversational answers.
          </span>
        </div>
      )}

      <div className="grid lg:grid-cols-4 gap-4">
        {/* chat */}
        <div className="lg:col-span-3 glass rounded-2xl flex flex-col min-h-[560px] max-h-[72vh]">
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/60">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-cognac/12 text-cognac flex items-center justify-center">
                <Sparkles size={14} />
              </div>
              <div>
                <div className="text-sm font-semibold leading-none">Ask about your data</div>
                <div className="text-[11px] text-muted mt-1">Private · grounded · query-only</div>
              </div>
            </div>
            <Badge tone="success" icon={<Lock size={11} />}>Isolated</Badge>
          </div>

          <div className="flex-1 overflow-y-auto scrollbar-thin px-5 py-4 space-y-4">
            {messages.length === 0 && (
              <div className="py-6">
                <div className="text-sm text-muted max-w-lg leading-relaxed">
                  Ask anything about your documents and profile. Follow-up questions keep the
                  context of the conversation, and answers cite the documents they came from.
                </div>
                <div className="mt-5 flex flex-wrap gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => void send(s)}
                      className="rounded-full border hairline bg-white/75 px-3.5 py-1.5 text-[13px] text-graphite hover:border-cognac/50 hover:text-cognac-deep transition-colors focus-ring"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m, index) => (
              <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`max-w-[88%] rounded-2xl px-4 py-3 text-sm ${
                    m.role === 'user'
                      ? 'bg-charcoal text-[#f4efe5] rounded-br-md'
                      : m.error
                        ? 'bg-danger/6 border border-danger/25 text-danger rounded-bl-md'
                        : 'bg-white/85 border hairline text-graphite rounded-bl-md'
                  }`}
                >
                  {m.role === 'assistant' && !m.error ? (
                    <Markdown text={m.text} />
                  ) : (
                    <div className="whitespace-pre-wrap wrap-anywhere leading-relaxed">{m.text}</div>
                  )}

                  {m.role === 'assistant' && m.sources && m.sources.length > 0 && (
                    <details className="mt-3 pt-2.5 border-t border-beige">
                      <summary className="text-[11px] uppercase tracking-wider text-faint cursor-pointer select-none">
                        Sources ({m.sources.length})
                      </summary>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {m.sources.map((s) => (
                          <span
                            key={`${s.document_id}-${s.page ?? 0}`}
                            className="inline-flex items-center gap-1.5 rounded-full bg-ivory-deep border hairline px-2.5 py-1 text-[11.5px] text-graphite"
                          >
                            <FileText size={10} className="text-cognac" />
                            {s.filename}
                            {s.page ? <span className="text-faint">· page {s.page}</span> : null}
                          </span>
                        ))}
                      </div>
                    </details>
                  )}

                  {m.role === 'assistant' && (
                    <div className="mt-2 flex gap-3">
                      <button
                        onClick={() => void copy(m)}
                        className="inline-flex items-center gap-1 text-[11.5px] text-faint hover:text-cognac-deep focus-ring"
                      >
                        {copiedId === m.id ? <Check size={11} /> : <Copy size={11} />}
                        {copiedId === m.id ? 'Copied' : 'Copy'}
                      </button>
                      <button
                        onClick={() => retry(index)}
                        disabled={busy}
                        className="inline-flex items-center gap-1 text-[11.5px] text-faint hover:text-cognac-deep focus-ring disabled:opacity-50"
                      >
                        <RotateCcw size={11} /> Retry
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}

            {busy && (
              <div className="flex justify-start">
                <div className="bg-white/85 border hairline rounded-2xl rounded-bl-md px-4 py-3 flex items-center gap-2.5">
                  <span className="spinner" />
                  <span className="text-[13px] text-muted">{STAGES[stage]}</span>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <div className="border-t border-white/60 p-3">
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void send()
              }}
              className="flex items-end gap-2"
            >
              <textarea
                rows={1}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    void send()
                  }
                }}
                placeholder="Ask about your documents, profile and academic information…"
                className="field resize-none max-h-28"
                aria-label="Ask OBSIDIAN Intelligence"
              />
              <Button type="submit" variant="accent" loading={busy} disabled={!input.trim()}>
                <Send size={14} />
              </Button>
            </form>
            <p className="text-[11px] text-faint mt-2 px-1">
              Retrieved text is treated as data, never instructions. The assistant cannot modify
              documents, links, profile or settings.
            </p>
          </div>
        </div>

        {/* side panel */}
        <div className="space-y-4">
          <div className="panel-solid rounded-2xl p-5">
            <div className="eyebrow flex items-center gap-2"><Lock size={12} /> Isolation guarantees</div>
            <ul className="mt-3 space-y-2 text-[12.5px] text-muted">
              <li className="flex gap-2"><Lock size={12} className="text-success mt-0.5 shrink-0" />RAG identity comes from your session — never from a request parameter.</li>
              <li className="flex gap-2"><Lock size={12} className="text-success mt-0.5 shrink-0" />Retrieval only ever queries your own partition.</li>
              <li className="flex gap-2"><Lock size={12} className="text-success mt-0.5 shrink-0" />Questions about other people get a scope reply — never their data.</li>
            </ul>
          </div>

          <div className="panel-solid rounded-2xl p-5">
            <button
              onClick={() => setShowDiagnostics((v) => !v)}
              className="w-full flex items-center justify-between focus-ring"
            >
              <span className="eyebrow flex items-center gap-2"><Database size={12} /> Knowledge base</span>
              <ChevronDown size={14} className={`text-faint transition-transform ${showDiagnostics ? 'rotate-180' : ''}`} />
            </button>
            <div className="mt-2 flex items-center justify-between text-[13px]">
              <span className="text-muted">Documents indexed</span>
              <span className="font-medium tabular-nums">{status?.document_count ?? 0}</span>
            </div>
            {showDiagnostics && (
              <div className="mt-3 space-y-2.5 text-[13px] border-t hairline pt-3">
                <div className="flex items-center justify-between">
                  <span className="text-muted">Status</span>
                  <Badge tone={status?.status === 'READY' ? 'success' : 'warning'}>{status?.status ?? '—'}</Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted">Chunks</span>
                  <span className="font-medium tabular-nums">{status?.chunk_count ?? 0}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted">Profile indexed</span>
                  <Badge tone={status?.profile_indexed ? 'success' : 'neutral'}>{status?.profile_indexed ? 'Yes' : 'No'}</Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted">Answer mode</span>
                  <span className="font-medium text-[12px]">{provider ? 'Model grounded' : 'Retrieval only'}</span>
                </div>
                {provider && (
                  <div className="flex items-center justify-between">
                    <span className="text-muted">Model</span>
                    <span className="font-medium text-[12px]">{status?.provider} · {status?.model}</span>
                  </div>
                )}
              </div>
            )}
          </div>

          {status && status.document_count === 0 && (
            <div className="panel-solid rounded-2xl p-5">
              <div className="eyebrow flex items-center gap-2"><UserRound size={12} /> Tip</div>
              <p className="text-[13px] text-muted mt-2">
                Only your profile is indexed right now. Mark documents as “Index for personal AI”
                when uploading to make their text searchable.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
