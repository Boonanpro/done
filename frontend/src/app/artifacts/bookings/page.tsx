'use client';

/**
 * 予約ブロックのデモ（美容室想定）。
 *
 * 再利用部品 <BookingCalendar> を config で設定して埋め込むだけ、という使い方の見本。
 * 業種を変えたい場合は config（services / staff / 営業時間 / 定休日 / askPartySize）を
 * 差し替えるだけで流用できる。スクロール出現は <FadeIn> 部品を使用。
 */
import { MapPin, Phone, Scissors } from 'lucide-react';

import { BookingCalendar } from '@/components/booking/booking-calendar';
import { FadeIn } from '@/components/motion';

export default function BookingsDemoPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* ヒーロー */}
      <header className="bg-muted/40 px-6 py-14 text-center">
        <FadeIn>
          <div className="mx-auto flex max-w-md flex-col items-center">
            <span className="mb-3 grid h-12 w-12 place-items-center rounded-full bg-primary/10 text-primary">
              <Scissors className="h-6 w-6" />
            </span>
            <h1 className="text-2xl font-bold tracking-tight">hair salon LumiÈre</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              ネット予約はこちらから。24時間いつでも受付中です。
            </p>
            <div className="mt-4 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <MapPin className="h-3.5 w-3.5" /> 米子市中町1-2-3
              </span>
              <span className="inline-flex items-center gap-1">
                <Phone className="h-3.5 w-3.5" /> 0859-00-0000
              </span>
            </div>
          </div>
        </FadeIn>
      </header>

      {/* 予約ブロック */}
      <main className="px-6 py-10">
        <FadeIn delay={0.1}>
          <BookingCalendar
            title="ご予約"
            config={{
              slug: 'bookings-demo',
              openTime: '10:00',
              closeTime: '19:00',
              slotMinutes: 60,
              services: ['カット', 'カラー', 'パーマ', 'トリートメント'],
              staff: ['佐藤', '鈴木', '高橋'],
              closedWeekdays: [2], // 火曜定休
            }}
          />
        </FadeIn>
        <p className="mx-auto mt-4 max-w-md text-center text-[11px] text-muted-foreground">
          ※ これは予約ブロックのデモです。`&lt;BookingCalendar&gt;` を config で設定して埋め込んでいます。
        </p>
      </main>
    </div>
  );
}
