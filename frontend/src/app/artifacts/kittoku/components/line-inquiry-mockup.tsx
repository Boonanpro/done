"use client";

import { useEffect, useState } from "react";
import {
  AnimatePresence,
  motion,
  useReducedMotion,
  type Variants,
} from "framer-motion";
import { CheckCheck, Image as ImageIcon } from "lucide-react";

const messages = [
  {
    side: "customer",
    text: "テールゲートリフターの点検をお願いできますか？",
    time: "10:12",
    hasImage: false,
  },
  {
    side: "customer",
    text: "現車の写真を送ります。",
    time: "10:13",
    hasImage: true,
  },
  {
    side: "shop",
    text: "ありがとうございます。症状を確認しました。本日中に担当より候補日をご連絡します。",
    time: "10:15",
    hasImage: false,
  },
  {
    side: "customer",
    text: "助かります。よろしくお願いします。",
    time: "10:16",
    hasImage: false,
  },
] as const;

const bubbleVariants: Variants = {
  hidden: { opacity: 0, y: 18, scale: 0.96 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { duration: 0.45, ease: [0.22, 1, 0.36, 1] },
  },
  exit: {
    opacity: 0,
    y: -8,
    scale: 0.98,
    transition: { duration: 0.18 },
  },
};

export function LineInquiryMockup() {
  const reduceMotion = useReducedMotion();
  const [visibleCount, setVisibleCount] = useState(
    reduceMotion ? messages.length : 0,
  );

  useEffect(() => {
    if (reduceMotion) {
      return;
    }

    const delays = [900, 2400, 2600, 2800, 7200];
    const timer = window.setTimeout(() => {
      setVisibleCount((current) =>
        current >= messages.length ? 0 : current + 1,
      );
    }, delays[Math.min(visibleCount, delays.length - 1)]);

    return () => window.clearTimeout(timer);
  }, [visibleCount, reduceMotion]);

  const messageCount = reduceMotion ? messages.length : visibleCount;
  const visibleMessages = messages.slice(0, messageCount);
  const nextMessage = messages[messageCount];
  const showTyping = !reduceMotion && messageCount > 0 && Boolean(nextMessage);

  return (
    <div className="relative mx-auto h-[544px] w-[min(360px,calc(100vw-32px))]">
      <motion.div
        className="absolute -inset-4 bg-[var(--yk-gold)]/10 blur-2xl"
        animate={reduceMotion ? undefined : { opacity: [0.55, 0.85, 0.55] }}
        transition={{ duration: 3.4, repeat: Infinity, ease: "easeInOut" }}
      />
      <div className="relative h-full overflow-hidden rounded-[28px] border border-white/15 bg-[#101820] p-2 shadow-2xl">
        <div className="h-full overflow-hidden rounded-[22px] bg-[#8fb6d8]">
          <div className="flex items-center gap-3 bg-[#06c755] px-4 py-3 text-white">
            <div className="grid h-8 w-8 place-items-center rounded-full bg-white/20 text-xs font-black">
              吉
            </div>
            <div className="min-w-0">
              <div className="text-sm font-bold leading-none">吉川特装</div>
              <div className="mt-1 text-[10px] leading-none text-white/80">
                LINEでかんたん相談
              </div>
            </div>
          </div>

          <div className="relative h-[470px] overflow-hidden px-3 py-5">
            <div className="absolute inset-0 bg-[linear-gradient(135deg,rgba(255,255,255,0.15)_0,rgba(255,255,255,0)_48%)]" />
            <div className="relative space-y-3">
              <AnimatePresence initial={false}>
                {visibleMessages.map((message, index) => {
                  const isCustomer = message.side === "customer";
                  return (
                    <motion.div
                      key={`${message.time}-${message.text}`}
                      className={`flex ${isCustomer ? "justify-end" : "justify-start"}`}
                      variants={bubbleVariants}
                      initial="hidden"
                      animate="visible"
                      exit="exit"
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
                        <div
                          className={`mt-1 flex items-center gap-1 text-[9px] ${
                            isCustomer
                              ? "justify-end text-[#4b6b3a]"
                              : "justify-start text-slate-400"
                          }`}
                        >
                          {isCustomer && index < visibleMessages.length ? (
                            <CheckCheck className="h-3 w-3" />
                          ) : null}
                          <span>{message.time}</span>
                        </div>
                      </div>
                    </motion.div>
                  );
                })}
              </AnimatePresence>

              <AnimatePresence>
                {showTyping ? (
                  <motion.div
                    className={`flex ${nextMessage?.side === "customer" ? "justify-end" : "justify-start"}`}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -4 }}
                  >
                    <div className="flex items-center gap-1.5 rounded-2xl rounded-bl-sm bg-white px-3.5 py-3 shadow-sm">
                      {[0, 1, 2].map((dot) => (
                        <motion.span
                          key={dot}
                          className="h-1.5 w-1.5 rounded-full bg-slate-400"
                          animate={{ y: [0, -4, 0] }}
                          transition={{
                            duration: 0.7,
                            repeat: Infinity,
                            delay: dot * 0.12,
                          }}
                        />
                      ))}
                    </div>
                  </motion.div>
                ) : null}
              </AnimatePresence>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
