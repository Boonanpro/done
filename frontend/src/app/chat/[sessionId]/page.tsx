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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}
