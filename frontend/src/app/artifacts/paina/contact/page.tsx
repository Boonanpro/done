"use client";

import * as React from "react";
import { ContactForm } from "../components/contact-form";
import { Reveal } from "../components/reveal";

export default function PainaContact() {
  return (
    <div>
      <section className="px-6 pb-24 pt-36 md:px-10 md:pb-32 md:pt-48">
        <div className="mx-auto max-w-[1180px]">
          <div className="grid gap-16 md:grid-cols-[0.9fr_1.1fr] md:gap-24">
            {/* Left: intro */}
            <div>
              <Reveal>
                <p className="kicker">Contact</p>
              </Reveal>
              <Reveal delay={120}>
                <h1 className="font-serif-jp mt-7 text-[2.4rem] leading-[1.32] text-[var(--paina-fg)] md:text-[3.2rem]">
                  お問い合わせ
                </h1>
              </Reveal>
              <Reveal delay={220}>
                <p className="lead mt-8 max-w-[42ch] text-[16px]">
                  ホームページ制作、ソフトウェア・ツールによるDX支援、
                  そのほかご相談など、どうぞお気軽にお寄せください。
                  内容を確認のうえ、担当より折り返しご連絡します。
                </p>
              </Reveal>
              <Reveal delay={300}>
                <div className="mt-12 border-t border-[var(--paina-border)] pt-8">
                  <p className="font-label text-[11px] uppercase tracking-[0.24em] text-[var(--paina-faint)]">
                    Email
                  </p>
                  <a
                    href="mailto:shub6923@gmail.com"
                    className="link-underline font-en mt-3 inline-block text-[18px] text-[var(--paina-fg)]"
                  >
                    shub6923@gmail.com
                  </a>
                  <p className="mt-6 text-[13px] leading-[1.9] text-[var(--paina-faint)]">
                    Done（ダン）の提供開始のご案内をご希望の方は、
                    事業内容ページのウェイティングリストもご利用いただけます。
                  </p>
                </div>
              </Reveal>
            </div>

            {/* Right: form */}
            <Reveal delay={180}>
              <div className="rounded-2xl border border-[var(--paina-border)] bg-[var(--paina-bg)] p-7 md:p-10">
                <ContactForm />
              </div>
            </Reveal>
          </div>
        </div>
      </section>
    </div>
  );
}
