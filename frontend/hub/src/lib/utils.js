import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

// Merge conditional class names, letting later Tailwind utilities win.
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

// Initials for an avatar fallback: "Jane Mary Doe" -> "JD", falling back to the
// email's first two characters when no name is on file.
export function getInitials(name, email) {
  if (name) {
    const parts = name.trim().split(' ').filter(Boolean);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }
    return name.substring(0, 2).toUpperCase();
  }
  if (email) {
    return email.substring(0, 2).toUpperCase();
  }
  return '??';
}

// Format an ISO/date string as e.g. "Jun 24, 2026".
export function formatDate(value, options = { month: 'short', day: 'numeric', year: 'numeric' }) {
  if (!value) return '';
  return new Date(value).toLocaleDateString('en-US', options);
}

// The title the API stores: whitespace collapsed, every word Title-Cased
// (mirrors sessions.services.normalize_title and the Hub's normalizeTitle).
export function normalizeTitle(raw) {
  return (raw || '')
    .trim()
    .replace(/\s+/g, ' ')
    .split(' ')
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1).toLowerCase() : w))
    .join(' ');
}

// Validators shared by the invitation / staff forms.
export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export const MEET_RE = /^https:\/\/meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}$/;
