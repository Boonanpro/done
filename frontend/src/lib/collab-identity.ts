import type { CollabMessageResponse } from './api-client';

export function guestIdentity(token: string | null): string {
  try { return JSON.parse(atob((token || '').split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))).sub || ''; }
  catch { return ''; }
}

export function isOwnGuestMessage(message: CollabMessageResponse, id: string, name: string): boolean {
  if (message.sender_type !== 'guest') return false;
  const sender = message.metadata?.sender_id;
  // Older messages predate stable identities; keep their original name fallback.
  return sender ? sender === id : message.sender_name === name;
}
