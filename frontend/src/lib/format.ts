/** Formatting helpers. */

export function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / Math.pow(1024, i)
  return `${value >= 10 || i === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[i]}`
}

export function formatDate(iso: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(undefined, {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso.slice(0, 16).replace('T', ' ')
  }
}

export function formatDateShort(iso: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return iso.slice(0, 10)
  }
}

export function relativeTime(iso: string): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return iso
  const diff = Date.now() - then
  const abs = Math.abs(diff)
  const mins = Math.round(abs / 60000)
  const suffix = diff > 0 ? 'ago' : 'from now'
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ${suffix}`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ${suffix}`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days}d ${suffix}`
  return formatDateShort(iso)
}

export function expiryLabel(iso: string): string {
  if (!iso) return 'Never'
  const diff = new Date(iso).getTime() - Date.now()
  if (diff <= 0) return 'Expired'
  const mins = Math.round(diff / 60000)
  if (mins < 60) return `${mins} min left`
  const hours = Math.round(mins / 60)
  if (hours < 48) return `${hours} h left`
  const days = Math.round(hours / 24)
  return `${days} d left`
}

export function eventLabel(type: string): string {
  const map: Record<string, string> = {
    login_success: 'Signed in',
    login_failure: 'Failed sign-in',
    logout: 'Signed out',
    otp_requested: 'Verification code requested',
    otp_success: 'MFA verified',
    otp_failure: 'MFA failed',
    password_reset: 'Password reset',
    registration_completed: 'Account created',
    document_uploaded: 'Document uploaded',
    document_viewed: 'Document viewed',
    document_downloaded: 'Document downloaded',
    document_renamed: 'Document renamed',
    document_deleted: 'Document deleted',
    document_updated: 'Document updated',
    share_created: 'Share link created',
    share_accessed: 'Share link accessed',
    share_revoked: 'Share link revoked',
    share_access_denied: 'Share access denied',
    profile_updated: 'Profile updated',
    visibility_changed: 'Visibility changed',
    ai_enabled: 'Personal AI enabled',
    ai_disabled: 'Personal AI disabled',
    ai_query: 'Asked OBSIDIAN Intelligence',
    student_lookup: 'Student ID lookup',
    group_created: 'Group created',
    group_updated: 'Group updated',
    group_deleted: 'Group deleted',
    group_viewed: 'Group opened',
    group_member_added: 'Student added to group',
    group_member_removed: 'Student removed from group',
    group_message_sent: 'Group message sent',
    authorization_denied: 'Access denied',
    rate_limit_triggered: 'Rate limit triggered',
    suspicious_activity: 'Security event',
    rag_index_started: 'Knowledge base indexing started',
    rag_index_completed: 'Knowledge base indexing completed',
    rag_index_failed: 'Knowledge base indexing failed',
  }
  return map[type] ?? type.replace(/_/g, ' ')
}

export function initials(name: string): string {
  if (!name) return '·'
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('')
}

export function truncate(text: string, len: number): string {
  if (text.length <= len) return text
  return text.slice(0, len - 1) + '…'
}
