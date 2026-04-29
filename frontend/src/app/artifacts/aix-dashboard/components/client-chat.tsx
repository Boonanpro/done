"use client";

import * as React from "react";
import { Send, Loader2, Sparkles, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
};

type Props = {
  clientId: string;
  clientName: string;
};

export function ClientChat({ clientId, clientName }: Props) {
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [input, setInput] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [sending, setSending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  // 履歴ロード
  React.useEffect(() => {
    let canceled = false;
    setLoading(true);
    fetch(`/api/v1/aix/clients/${clientId}/chat`, {
      credentials: "include",
    })
      .then((r) => (r.ok ? r.json() : []))
      .then((rows) => {
        if (canceled) return;
        setMessages(rows as ChatMessage[]);
      })
      .catch((e) => !canceled && setError(String(e)))
      .finally(() => !canceled && setLoading(false));
    return () => {
      canceled = true;
    };
  }, [clientId]);

  // 自動スクロール
  React.useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages.length]);

  const send = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setSending(true);
    setError(null);
    // 楽観的: ユーザーメッセージを即表示
    const tempUser: ChatMessage = {
      id: `temp-${Date.now()}`,
      role: "user",
      content: text,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUser]);
    setInput("");
    try {
      const res = await fetch(`/api/v1/aix/clients/${clientId}/chat`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
      const j = (await res.json()) as {
        user_message: ChatMessage;
        assistant_message: ChatMessage;
      };
      setMessages((prev) => {
        const without = prev.filter((m) => m.id !== tempUser.id);
        return [...without, j.user_message, j.assistant_message];
      });
    } catch (e) {
      setError(String(e));
      setMessages((prev) => prev.filter((m) => m.id !== tempUser.id));
    } finally {
      setSending(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="flex flex-col h-full border border-border rounded-lg bg-card overflow-hidden">
      {/* ヘッダー */}
      <div className="px-4 py-3 border-b border-border flex items-center gap-2 bg-accent/20">
        <Sparkles className="h-4 w-4 text-amber-400" />
        <div className="text-sm font-medium">
          {clientName} 担当ダンとのチャット
        </div>
      </div>

      {/* 履歴 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
        {loading && (
          <div className="text-xs text-muted-foreground text-center py-6">
            <Loader2 className="h-4 w-4 animate-spin mx-auto mb-1" />
            読み込み中…
          </div>
        )}
        {!loading && messages.length === 0 && (
          <div className="text-xs text-muted-foreground text-center py-12 leading-relaxed">
            <Sparkles className="h-6 w-6 text-amber-400 mx-auto mb-2" />
            このクライアント向けの会話はまだありません。<br />
            「修理進捗ページ作って」「新しい仮説出して」など話しかけてみてください。
          </div>
        )}
        {messages.map((m) => (
          <Bubble key={m.id} message={m} />
        ))}
        {sending && (
          <div className="text-xs text-muted-foreground flex items-center gap-2 pl-8">
            <Loader2 className="h-3 w-3 animate-spin" />
            ダンが考え中…
          </div>
        )}
        {error && (
          <div className="text-xs text-rose-400 text-center">エラー: {error}</div>
        )}
      </div>

      {/* 入力 */}
      <div className="border-t border-border p-3 bg-background">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="ダンに依頼する… (Enterで送信 / Shift+Enterで改行)"
            rows={2}
            disabled={sending}
            className="flex-1 resize-none bg-transparent border border-input rounded-md px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/40 min-h-[44px] max-h-[160px]"
          />
          <Button
            type="button"
            onClick={send}
            disabled={!input.trim() || sending}
            size="sm"
            className="self-end h-10"
          >
            {sending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
        <div className="text-[10px] text-muted-foreground mt-1.5">
          このクライアントの過去会話と現在の仮説・提案・タスクをダンが把握しています
        </div>
      </div>
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex gap-2", isUser ? "flex-row-reverse" : "flex-row")}>
      <div
        className={cn(
          "shrink-0 h-7 w-7 rounded-full flex items-center justify-center text-xs",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-amber-500/20 text-amber-400 border border-amber-500/30"
        )}
      >
        {isUser ? <User className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
      </div>
      <div
        className={cn(
          "max-w-[85%] rounded-lg px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-accent/50 text-foreground"
        )}
      >
        {message.content}
      </div>
    </div>
  );
}
