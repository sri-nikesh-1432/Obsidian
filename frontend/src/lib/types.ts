/** Shared API types (mirrors the backend contract). */

export type Role = 'student' | 'faculty' | 'recruiter' | 'admin'

export interface Profile {
  full_name: string
  student_id: string
  phone: string
  institution: string
  course: string
  education_level: string
  graduation_year: string
  department: string
  year: string
  bio: string
  skills: string[]
  achievements: string[]
  cgpa: string
  profile_visibility: 'public' | 'private'
  show_phone: boolean
  created_at?: string
  updated_at?: string
}

export interface StoragePlan {
  tier: number
  label: string
  total_gb: number
  added_gb: number
  price_inr: number
  price_paise: number
  total_bytes: number
}

export interface StorageStatus {
  used_bytes: number
  limit_bytes: number
  remaining_bytes: number
  percent_used: number
  tier: number
  total_gb: number
  exceeded: boolean
  near_limit: boolean
  next_plan?: StoragePlan
  plans?: StoragePlan[]
  payments?: { configured: boolean; key_id: string; currency: string }
}

export interface BillingOrder {
  order_id: string
  amount: number
  currency: string
  key_id: string
  plan: StoragePlan
  simulated: boolean
}

export interface BillingHistoryRow {
  order_id: string
  plan: string
  total_gb: number
  amount_inr: number
  status: string
  created_at: string
  paid_at: string
}

export interface Me {
  authenticated: boolean
  user_id?: string
  email?: string
  role?: Role
  mfa_enabled?: boolean
  ai_enabled?: boolean
  onboarding_complete?: boolean
  created_at?: string
  last_login_at?: string
  profile?: Profile
  storage?: StorageStatus
}

export interface DocumentList {
  documents: DocumentMeta[]
  total: number
  total_bytes: number
  storage?: StorageStatus
}

export interface DocumentMeta {
  document_id: string
  filename: string
  mime_type: string
  size_bytes: number
  visibility: 'public' | 'private'
  profile_visible: boolean
  rag_eligible: boolean
  rag_status: string
  encryption: string
  encrypted_at_rest: boolean
  integrity: string
  created_at: string
  updated_at: string
  owner_id: string
  share_count: number
  active_share_count: number
  extension: string
  is_text: boolean
  shared_with_me?: { permission: string }
}

export interface Share {
  share_id: string
  document_id: string
  filename: string
  mode: 'link' | 'restricted'
  permission: 'viewer' | 'editor'
  status: 'active' | 'expired' | 'revoked'
  created_at: string
  expires_at: string
  revoked_at: string
  access_count: number
  last_accessed_at: string
  grantee_email?: string
  url?: string
  token_preview?: string
}

export interface ActivityEvent {
  event_id: string
  event_type: string
  timestamp: string
  result: string
  resource_type: string
  resource_id: string
  metadata: Record<string, unknown>
}

export interface StudentProfileView {
  student_id: string
  full_name: string
  institution: string
  course: string
  education_level: string
  graduation_year: string
  department: string
  year: string
  bio: string
  skills: string[]
  achievements: string[]
  cgpa: string
  profile_visibility: string
  phone: string
  show_phone: boolean
}

export interface StudentLookup {
  student: StudentProfileView
  documents: {
    document_id: string
    filename: string
    mime_type: string
    size_bytes: number
    created_at: string
    visibility: string
  }[]
}

export interface IntelligenceStatus {
  enabled: boolean
  status: string
  chunk_count?: number
  document_count?: number
  profile_indexed?: boolean
  reason?: string
  model_mode?: string
  isolation?: string
}

export interface AdminAnalytics {
  users: { total: number; by_role: Record<string, number>; mfa_enabled: number; ai_enabled: number }
  documents: { total: number; storage_bytes: number; public: number; private: number; profile_visible: number }
  shares: { total: number; active: number; expired: number; revoked: number }
  groups?: { total: number; memberships: number; messages: number }
  security: Record<string, number>
  health: Record<string, string>
}

export interface GroupSummary {
  group_id: string
  name: string
  description: string
  owner_id: string
  owner_name: string
  member_count: number
  created_at: string
  updated_at: string
  role: 'owner' | 'member'
}

export interface GroupMember {
  user_id: string
  student_id: string
  full_name: string
  institution: string
  avatar_seed: string
  joined_at: string
}

export interface GroupMessage {
  message_id: string
  sender_id: string
  sender_name: string
  sender_role: string
  body: string
  created_at: string
}

export interface GroupDetail {
  group: GroupSummary
  members: GroupMember[]
  messages: GroupMessage[]
}
