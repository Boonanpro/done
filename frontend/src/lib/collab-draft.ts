// Drafts belong to an invitation identity, not to every guest on this browser.
export interface CollabDraft {
  text: string;
  reply: { id: string; sender_name: string; sender_type: string; content: string } | null;
  private: boolean;
}

export function readDraft(key: string): CollabDraft | null {
  try {
    const value = JSON.parse(localStorage.getItem(`collab-draft:${key}`) || 'null');
    return value && typeof value.text === 'string' ? value : null;
  } catch { return null; }
}

export function writeDraft(key: string, value: CollabDraft) {
  try {
    if (!value.text && !value.reply && !value.private) localStorage.removeItem(`collab-draft:${key}`);
    else localStorage.setItem(`collab-draft:${key}`, JSON.stringify(value));
  } catch { /* Restricted storage must not stop typing or sending. */ }
}
