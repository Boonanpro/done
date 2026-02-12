'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

/**
 * /chat/[sessionId] - 後方互換リダイレクト
 * 旧URLを /chat にリダイレクト
 */
export default function ChatSessionRedirect() {
  const router = useRouter();

  useEffect(() => {
    router.replace('/chat');
  }, [router]);

  return null;
}
