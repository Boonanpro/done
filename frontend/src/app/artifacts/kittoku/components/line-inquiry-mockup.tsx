"use client";

import { motion } from "framer-motion";
import { CheckCheck, Image as ImageIcon, Send } from "lucide-react";

const messages = [
  {
    side: "customer",
    delay: 0.25,
    text: "テールゲートリフターの点検をお願いできますか？",
    hasImage: false,
  },
  {
    side: "customer",
    delay: 1.25,
    text: "現車の写真を送ります。",
    hasImage: true,
  },
  {
    side: "shop",
    delay: 2.3,
    text: "ありがとうございます。症状を確認しました。本日中に担当より候補日をご連絡します。",
    hasImage: false,
  },
  {
    side: "customer",
    delay: 3.45,
    text: "助かります。よろしくお願いします。",
    hasImage: false,
  },
] as const;

export function LineInquiryMockup() {
  return (
    <div className="relative mx-auto w-full max-w-[360px]">
      <div className="absolute -inset-4 bg-[var(--yk-gold)]/10 blur-2xl" />
      <div className="relative overflow-hidden rounded-[28px] border border-white/15 bg-[#101820] p-2 shadow-2xl">
        <div className="overflow-hidden rounded-[22px] bg-[#8fb6d8]">
          <div className="flex items-center gap-3 bg-[#06c755] px-4 py-3 text-white">
            <div className="grid h-8 w-8 place-items-center rounded-full bg-white/20 text-xs font-black">
              吉
            </div>
            <div className="min-w-0">
              <div className="text-sm font-bold leading-none">吉川特装</div>
              <div className="mt-1 text-[10px] leading-none text-white/80">
                通常数分以内に確認
              </div>
            </div>
            <div className="ml-auto flex gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-white/75" />
              <span className="h-1.5 w-1.5 rounded-full bg-white/75" />
              <span className="h-1.5 w-1.5 rounded-full bg-white/75" />
            </div>
          </div>

          <div className="relative min-h-[360px] px-3 py-4">
            <div className="absolute inset-0 bg-[linear-gradient(135deg,rgba(255,255,255,0.15)_0,rgba(255,255,255,0)_48%)]" />
            <div className="relative space-y-3">
              {messages.map((message) => {
                const isCustomer = message.side === "customer";
                return (
                  <motion.div
                    key={`${message.delay}-${message.text}`}
                    className={`flex ${isCustomer ? "justify-end" : "justify-start"}`}
                    initial={{ opacity: 0, y: 14, scale: 0.96 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    transition={{
                      delay: message.delay,
                      duration: 0.45,
                      ease: [0.22, 1, 0.36, 1],
                    }}
                  >
                    <div
                      className={`max-w-[78%] rounded-2xl px-3.5 py-2.5 text-[12px] leading-relaxed shadow-sm ${
                        isCustomer
                          ? "rounded-br-sm bg-[#8de055] text-[#10210f]"
                          : "rounded-bl-sm bg-white text-[#142033]"
                      }`}
                    >
                      {message.text}
                      {message.hasImage ? (
                        <div className="mt-2 flex h-20 items-center justify-center rounded-lg bg-[#dce7ef] text-[#506172]">
                          <ImageIcon className="h-7 w-7" />
                        </div>
                      ) : null}
                      {isCustomer ? (
                        <div className="mt-1 flex justify-end text-[9px] text-[#4b6b3a]">
                          既読
                        </div>
                      ) : null}
                    </div>
                  </motion.div>
                );
              })}
            </div>

            <motion.div
              className="absolute bottom-3 left-3 right-3 flex items-center gap-2 rounded-full bg-white px-3 py-2 shadow-lg"
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 4.05, duration: 0.4 }}
            >
              <div className="h-2 flex-1 rounded-full bg-slate-200" />
              <CheckCheck className="h-4 w-4 text-[#06c755]" />
              <div className="grid h-7 w-7 place-items-center rounded-full bg-[#06c755] text-white">
                <Send className="h-3.5 w-3.5" />
              </div>
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  );
}
