import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';

// Shared by rewrites AND streaming route handlers. A picker and a send must
// reach the same generation gateway, not different copies of Dan.
export function backendUrl(role: 'core' | 'sandbox'): string {
  const override = role === 'core' ? process.env.CORE_BACKEND_URL : process.env.BACKEND_URL;
  if (override) return override;
  const generations = !process.env.VERCEL && existsSync(path.join(homedir(), '.dan/generations/enabled'));
  const port = role === 'core' ? (generations ? 9100 : 9000) : (generations ? 8100 : 8000);
  return `http://127.0.0.1:${port}`;
}
