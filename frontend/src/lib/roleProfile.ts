/**
 * Role-specific profile fields — the frontend mirror of the backend
 * `profile_schema`. Onboarding and the profile page both render from here, so
 * a student never sees faculty fields and vice versa.
 */

export type Role = 'student' | 'faculty' | 'recruiter' | 'admin'

export type FieldKind = 'text' | 'select' | 'textarea' | 'list'

export interface FieldDef {
  name: string
  label: string
  kind: FieldKind
  required?: boolean
  placeholder?: string
  hint?: string
  options?: string[]
  /** Render full width on its own row. */
  wide?: boolean
}

export interface RoleForm {
  title: string
  subtitle: string
  fields: FieldDef[]
  /** Students (and only students) control lookup visibility. */
  hasVisibility: boolean
  note?: string
}

const EDUCATION_LEVELS = ['Secondary', 'Higher secondary', 'Diploma', "Bachelor's", "Master's", 'Doctorate']

export const DESIGNATIONS = [
  'Assistant Professor', 'Associate Professor', 'Professor', 'Lecturer',
  'Visiting Faculty', 'Research Scholar', 'Teaching Assistant',
  'Head of Department', 'Dean', 'Other',
]

export const ROLE_FORMS: Record<Role, RoleForm> = {
  student: {
    title: 'Complete your academic profile',
    subtitle: 'You can change any of this later. Only fields you expose appear on your profile.',
    hasVisibility: true,
    fields: [
      { name: 'full_name', label: 'Full name', kind: 'text', required: true, placeholder: 'Arjun Mehta' },
      { name: 'phone', label: 'Phone (optional)', kind: 'text', placeholder: '+91 …' },
      { name: 'institution', label: 'Institution', kind: 'text', required: true, placeholder: 'University / college' },
      { name: 'course', label: 'Course', kind: 'text', required: true, placeholder: 'B.Tech Computer Science' },
      { name: 'education_level', label: 'Education level', kind: 'select', required: true, options: EDUCATION_LEVELS },
      { name: 'department', label: 'Department', kind: 'text', required: true, placeholder: 'Computer Science' },
      { name: 'year', label: 'Year of study', kind: 'text', required: true, placeholder: '3rd year' },
      { name: 'graduation_year', label: 'Graduation year', kind: 'text', required: true, placeholder: '2027' },
      { name: 'cgpa', label: 'CGPA (optional)', kind: 'text', hint: '0 – 10', placeholder: '8.7' },
      { name: 'skills', label: 'Skills', kind: 'list', hint: 'Comma separated', placeholder: 'Python, Security, Figma' },
      { name: 'bio', label: 'Short bio', kind: 'textarea', wide: true, placeholder: 'A sentence or two about your focus and interests.' },
    ],
  },
  faculty: {
    title: 'Complete your faculty profile',
    subtitle: 'Your institutional profile. Students never see these details unless you share them.',
    hasVisibility: false,
    fields: [
      { name: 'full_name', label: 'Full name', kind: 'text', required: true, placeholder: 'Dr. Rao' },
      { name: 'faculty_id', label: 'Faculty / employee ID', kind: 'text', required: true, placeholder: 'FAC-10293' },
      { name: 'institution', label: 'Institution / university', kind: 'text', required: true, placeholder: 'State University' },
      { name: 'department', label: 'Department', kind: 'text', required: true, placeholder: 'Computer Science' },
      { name: 'designation', label: 'Designation', kind: 'select', required: true, options: DESIGNATIONS },
      { name: 'office_contact', label: 'Office contact (optional)', kind: 'text', placeholder: 'Block C, Room 214' },
      { name: 'expertise', label: 'Areas of expertise / subjects taught', kind: 'list', wide: true, hint: 'Comma separated', placeholder: 'Databases, Information Security' },
      { name: 'bio', label: 'Short bio', kind: 'textarea', wide: true, placeholder: 'A sentence or two about your teaching and research.' },
    ],
  },
  recruiter: {
    title: 'Complete your hiring profile',
    subtitle: 'Tell students who you are and what you hire for.',
    hasVisibility: false,
    fields: [
      { name: 'full_name', label: 'Full name', kind: 'text', required: true, placeholder: 'Dana Cole' },
      { name: 'company', label: 'Company / organization', kind: 'text', required: true, placeholder: 'Northwind' },
      { name: 'job_title', label: 'Job title / designation', kind: 'text', required: true, placeholder: 'Talent Partner' },
      { name: 'industry', label: 'Industry', kind: 'text', required: true, placeholder: 'Software' },
      { name: 'company_website', label: 'Company website (optional)', kind: 'text', placeholder: 'https://example.com' },
      { name: 'contact_number', label: 'Contact number (optional)', kind: 'text', placeholder: '+91 …' },
      { name: 'hiring_domains', label: 'Hiring domains / preferred skills', kind: 'list', wide: true, hint: 'Comma separated', placeholder: 'Backend, Security, Data' },
    ],
  },
  admin: {
    title: 'Administrative setup',
    subtitle: 'Platform administration. This account cannot be self-provisioned.',
    hasVisibility: false,
    note: 'Admin privileges are granted only through a trusted authorization process — they can never be selected during signup.',
    fields: [
      { name: 'full_name', label: 'Full name', kind: 'text', required: true, placeholder: 'System Admin' },
      { name: 'admin_designation', label: 'Admin / operations designation', kind: 'text', required: true, placeholder: 'Platform Administrator' },
      { name: 'organization', label: 'Organization / institution managed', kind: 'text', required: true, placeholder: 'State University' },
    ],
  },
}

export function roleForm(role: string | undefined): RoleForm {
  return ROLE_FORMS[(role as Role) ?? 'student'] ?? ROLE_FORMS.student
}
