import Link from "next/link";
import { Phone, MapPin, Mail, Clock } from "lucide-react";
import { Logo } from "./logo";

export function SiteFooter() {
  return (
    <div className="w-full bg-[var(--yk-navy-dark)] text-white">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 py-14 sm:py-20">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-10">
          <div className="lg:col-span-1 space-y-4">
            <Logo size="md" variant="dark" />
            <p className="text-sm text-white/70 leading-relaxed">
              新明和工業 認定修理工場として山陰・中国地方の特装車修理を支えています。
            </p>
          </div>

          <div className="space-y-3">
            <div className="text-xs font-eyebrow text-[var(--yk-gold)]">
              Contact
            </div>
            <a
              href="tel:0859-27-4885"
              className="flex items-center gap-2 text-white hover:text-[var(--yk-gold)] transition-colors"
            >
              <Phone className="h-4 w-4 shrink-0" />
              <span className="font-mono-data text-xl font-bold">
                0859-27-4885
              </span>
            </a>
            <div className="flex items-start gap-2 text-sm text-white/80">
              <Clock className="h-4 w-4 shrink-0 mt-0.5" />
              <div>
                <div>平日 8:00〜17:00</div>
                <div className="text-xs text-white/60">土日祝休</div>
              </div>
            </div>
            <Link
              href="/artifacts/kittoku/contact"
              className="inline-flex items-center gap-2 text-sm text-white hover:text-[var(--yk-gold)] transition-colors"
            >
              <Mail className="h-4 w-4" />
              Webからお問い合わせ
            </Link>
          </div>

          <div className="space-y-3">
            <div className="text-xs font-eyebrow text-[var(--yk-gold)]">
              Access
            </div>
            <div className="flex items-start gap-2 text-sm text-white/80">
              <MapPin className="h-4 w-4 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <div>〒689-3537</div>
                <div>鳥取県米子市古豊千775-6</div>
              </div>
            </div>
          </div>

          <div className="space-y-3">
            <div className="text-xs font-eyebrow text-[var(--yk-gold)]">
              Sitemap
            </div>
            <div className="flex flex-col gap-2">
              <FooterLink href="/artifacts/kittoku">ホーム</FooterLink>
              <FooterLink href="/artifacts/kittoku/services">
                事業・サービス
              </FooterLink>
              <FooterLink href="/artifacts/kittoku/company">
                会社情報
              </FooterLink>
              <FooterLink href="/artifacts/kittoku/careers">
                採用情報
              </FooterLink>
              <FooterLink href="/artifacts/kittoku/contact">
                お問い合わせ
              </FooterLink>
            </div>
          </div>
        </div>

        <div className="mt-14 pt-6 border-t border-white/10 flex flex-col sm:flex-row justify-between gap-2 text-xs text-white/50">
          <div>© {new Date().getFullYear()} 有限会社吉川特装自動車</div>
          <div className="font-eyebrow">
            Shinmeiwa Certified Repair Facility
          </div>
        </div>
      </div>
    </div>
  );
}

function FooterLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className="text-sm text-white/70 hover:text-white transition-colors"
    >
      {children}
    </Link>
  );
}
