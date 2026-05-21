import { ArtifactLink as Link } from "@/components/artifacts/artifact-link";
import { Clock, Mail, MapPin, Phone } from "lucide-react";
import { Logo } from "./logo";

export function SiteFooter() {
  return (
    <div className="w-full bg-[var(--yk-navy-dark)] text-white">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 py-14 sm:py-20">
        <div className="grid grid-cols-1 gap-10 md:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
          <div className="space-y-4">
            <Logo size="md" variant="dark" />
            <p className="max-w-sm text-sm leading-relaxed text-white/70">
              取扱メーカー各社の指定工場として、山陰・中国地方の特装車修理を支えています。
            </p>
          </div>

          <div className="space-y-3">
            <div className="text-xs font-eyebrow text-[var(--yk-gold)]">
              Contact
            </div>
            <a
              href="tel:0859-27-4885"
              className="flex items-center gap-2 text-white transition-colors hover:text-[var(--yk-gold)]"
            >
              <Phone className="h-4 w-4 shrink-0" />
              <span className="font-mono-data text-xl font-bold">
                0859-27-4885
              </span>
            </a>
            <div className="flex items-start gap-2 text-sm text-white/80">
              <Clock className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <div>月〜土 9:00〜17:00</div>
                <div className="text-xs text-white/60">定休日：日祝・毎月第2土曜</div>
              </div>
            </div>
            <Link
              href="/artifacts/kittoku/contact"
              className="inline-flex items-center gap-2 text-sm text-white transition-colors hover:text-[var(--yk-gold)]"
            >
              <Mail className="h-4 w-4" />
              LINE / お電話で問い合わせ
            </Link>
          </div>

          <div className="space-y-3">
            <div className="text-xs font-eyebrow text-[var(--yk-gold)]">
              Access
            </div>
            <div className="flex items-start gap-2 text-sm text-white/80">
              <MapPin className="mt-0.5 h-4 w-4 shrink-0" />
              <div className="space-y-1">
                <div>〒689-3537</div>
                <div>鳥取県米子市古豊千775-6</div>
              </div>
            </div>
            <div className="rounded-sm border border-white/10 bg-white/[0.04] p-4 text-xs leading-relaxed text-white/60">
              JR米子駅より車で約10分 / 山陰道 米子ICより約5分
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

        <div className="mt-14 flex flex-col justify-between gap-2 border-t border-white/10 pt-6 text-xs text-white/50 sm:flex-row">
          <div>© {new Date().getFullYear()} 有限会社吉川特装自動車</div>
          <div className="font-eyebrow">Authorized Service Facility</div>
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
      className="text-sm text-white/70 transition-colors hover:text-white"
    >
      {children}
    </Link>
  );
}
