"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Send, Loader2 } from "lucide-react";

type Message = {
  role: "user" | "assistant";
  content: string;
};

type AIChatPanelProps = {
  scope: string;
  title?: React.ReactNode;
  description?: React.ReactNode;
  placeholder?: string;
  suggestions?: string[];
  systemContext?: string;
  endpoint?: string;
  className?: string;
};

export function AIChatPanel({
  scope,
  title = "AIに質問する",
  description,
  placeholder = "なんでも聞いてください",
  suggestions,
  systemContext,
  endpoint = "/api/v1/public-chat/messages",
  className,
}: AIChatPanelProps) {
  const [messages, setMessages] = React.useState<Message[]>([]);
  const [input, setInput] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const scrollRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, loading]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    setError(null);
    const next: Message[] = [...messages, { role: "user", content: trimmed }];
    setMessages(next);
    setInput("");
    setLoading(true);
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope,
          system_context: systemContext,
          messages: next.map((m) => ({ role: m.role, content: m.content })),
        }),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setMessages([
        ...next,
        { role: "assistant", content: data.content || "" },
      ]);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className={cn("flex flex-col overflow-hidden", className)}>
      <div className="px-5 py-4 border-b border-border/60">
        <div className="text-sm font-semibold text-foreground">{title}</div>
        {description && (
          <div className="text-xs text-muted-foreground mt-1">{description}</div>
        )}
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-5 py-4 space-y-4 min-h-[280px] max-h-[540px]"
      >
        {messages.length === 0 && suggestions && suggestions.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs text-muted-foreground">
              よくある質問
            </div>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((s, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => send(s)}
                  className="text-xs px-3 py-1.5 rounded-full border border-border/60 text-muted-foreground hover:text-foreground hover:border-border transition"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={cn(
              "flex",
              m.role === "user" ? "justify-end" : "justify-start",
            )}
          >
            <div
              className={cn(
                "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap",
                m.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-foreground",
              )}
            >
              {m.content}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="rounded-2xl px-4 py-2.5 bg-muted text-muted-foreground text-sm flex items-center gap-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              考え中…
            </div>
          </div>
        )}
        {error && (
          <div className="text-xs text-rose-500">
            エラー: {error}
          </div>
        )}
      </div>

      <form
        className="border-t border-border/60 p-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={placeholder}
          disabled={loading}
          className="flex-1 bg-transparent px-3 py-2 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-60"
        />
        <Button
          type="submit"
          size="sm"
          disabled={loading || !input.trim()}
          className="shrink-0"
        >
          <Send className="h-3.5 w-3.5" />
        </Button>
      </form>
    </Card>
  );
}
