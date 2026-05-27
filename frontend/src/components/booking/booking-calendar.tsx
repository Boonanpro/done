'use client';

/**
 * <BookingCalendar /> — 予約・カレンダー機能ブロック（再利用）。
 *
 * クライアントHP/ツールに埋め込む。メニュー・スタッフ・営業時間・枠長・定員を
 * props (config) で渡すだけで、業種をまたいで使える（美容室/飲食/クリニック等）。
 * 配色はサイトのデザイントークン (bg-card / text-foreground / bg-primary ...) を
 * 継承するので、埋め込み先の雰囲気に自然に馴染む。
 *
 * 使い方:
 *   <BookingCalendar config={{
 *     slug: 'kittoku-salon',
 *     openTime: '10:00', closeTime: '19:00', slotMinutes: 60,
 *     services: ['カット', 'カラー', 'パーマ'],
 *     staff: ['佐藤', '鈴木'],
 *     closedWeekdays: [2],          // 火曜定休
 *   }} />
 */
import { useEffect, useMemo, useState } from 'react';
import { Calendar, Check, ChevronLeft, Clock, Loader2, User } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useBooking, type BookingConfig } from '@/hooks/use-booking';

const WD = ['日', '月', '火', '水', '木', '金', '土'];

function toISO(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function nextDays(n: number): Date[] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Array.from({ length: n }, (_, i) => {
    const d = new Date(today);
    d.setDate(today.getDate() + i);
    return d;
  });
}

type Step = 'pick' | 'form' | 'done';

export function BookingCalendar({
  config,
  className,
  title = 'ご予約',
  days = 14,
}: {
  config: BookingConfig;
  className?: string;
  title?: string;
  days?: number;
}) {
  const { slots, loadingSlots, submitting, loadSlots, book } = useBooking(config);
  const hasStaff = (config.staff?.length ?? 0) > 0;
  const hasServices = (config.services?.length ?? 0) > 0;
  const closed = useMemo(() => new Set(config.closedWeekdays ?? []), [config.closedWeekdays]);
  const dayList = useMemo(() => nextDays(days), [days]);

  const [step, setStep] = useState<Step>('pick');
  const [date, setDate] = useState('');
  const [staff, setStaff] = useState('');
  const [service, setService] = useState('');
  const [time, setTime] = useState('');
  const [name, setName] = useState('');
  const [contact, setContact] = useState('');
  const [partySize, setPartySize] = useState(1);
  const [notes, setNotes] = useState('');
  const [error, setError] = useState('');

  // 日付/スタッフが変わったら空き枠を読み込む
  useEffect(() => {
    if (date) loadSlots(date, hasStaff && staff ? staff : undefined);
  }, [date, staff, hasStaff, loadSlots]);

  const reset = () => {
    setStep('pick');
    setDate('');
    setTime('');
    setName('');
    setContact('');
    setNotes('');
    setPartySize(1);
    setError('');
  };

  const canSubmit = name.trim() && contact.trim() && !submitting;

  const confirm = async () => {
    setError('');
    const res = await book({
      date,
      time,
      name: name.trim(),
      contact: contact.trim(),
      service: hasServices ? service || undefined : undefined,
      staff: hasStaff ? staff || undefined : undefined,
      partySize: config.askPartySize ? partySize : 1,
      notes: notes.trim() || undefined,
    });
    if (res.ok) {
      setStep('done');
    } else {
      setError(res.error || '予約に失敗しました');
      // 満席等で枠状況が変わっている可能性があるので再取得
      if (date) loadSlots(date, hasStaff && staff ? staff : undefined);
    }
  };

  const labelFor = (iso: string) => {
    const d = new Date(`${iso}T00:00:00`);
    return `${d.getMonth() + 1}/${d.getDate()}`;
  };

  return (
    <div
      className={`mx-auto w-full max-w-md overflow-hidden rounded-2xl border border-border bg-card text-card-foreground shadow-sm ${className ?? ''}`}
    >
      <div className="flex items-center gap-2 border-b border-border bg-muted/40 px-5 py-4">
        <Calendar className="h-5 w-5 text-primary" />
        <h3 className="text-base font-semibold">{title}</h3>
      </div>

      {/* ===== 日付・枠選択 ===== */}
      {step === 'pick' && (
        <div className="space-y-5 p-5">
          {hasServices && (
            <div className="space-y-2">
              <Label className="text-sm text-muted-foreground">メニュー</Label>
              <div className="flex flex-wrap gap-2">
                {config.services!.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setService(s)}
                    className={`rounded-full border px-3 py-1.5 text-sm transition ${
                      service === s
                        ? 'border-primary bg-primary text-primary-foreground'
                        : 'border-border bg-background hover:bg-muted'
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {hasStaff && (
            <div className="space-y-2">
              <Label className="flex items-center gap-1 text-sm text-muted-foreground">
                <User className="h-3.5 w-3.5" /> 担当
              </Label>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setStaff('')}
                  className={`rounded-full border px-3 py-1.5 text-sm transition ${
                    staff === ''
                      ? 'border-primary bg-primary text-primary-foreground'
                      : 'border-border bg-background hover:bg-muted'
                  }`}
                >
                  指定なし
                </button>
                {config.staff!.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setStaff(s)}
                    className={`rounded-full border px-3 py-1.5 text-sm transition ${
                      staff === s
                        ? 'border-primary bg-primary text-primary-foreground'
                        : 'border-border bg-background hover:bg-muted'
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="space-y-2">
            <Label className="text-sm text-muted-foreground">日付</Label>
            <div className="flex gap-2 overflow-x-auto pb-1">
              {dayList.map((d) => {
                const iso = toISO(d);
                const isClosed = closed.has(d.getDay());
                const active = date === iso;
                return (
                  <button
                    key={iso}
                    type="button"
                    disabled={isClosed}
                    onClick={() => {
                      setDate(iso);
                      setTime('');
                    }}
                    className={`flex min-w-[3.25rem] shrink-0 flex-col items-center rounded-lg border px-2 py-2 text-sm transition ${
                      active
                        ? 'border-primary bg-primary text-primary-foreground'
                        : isClosed
                          ? 'cursor-not-allowed border-border bg-muted/40 text-muted-foreground/40'
                          : 'border-border bg-background hover:bg-muted'
                    }`}
                  >
                    <span className="text-[11px]">
                      {WD[d.getDay()]}
                    </span>
                    <span className="font-semibold">{labelFor(iso)}</span>
                    {isClosed && <span className="text-[10px]">休</span>}
                  </button>
                );
              })}
            </div>
          </div>

          {date && (
            <div className="space-y-2">
              <Label className="flex items-center gap-1 text-sm text-muted-foreground">
                <Clock className="h-3.5 w-3.5" /> 時間
              </Label>
              {loadingSlots ? (
                <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" /> 空き状況を確認中…
                </div>
              ) : (
                <div className="grid grid-cols-4 gap-2">
                  {slots.map((s) => (
                    <button
                      key={s.time}
                      type="button"
                      disabled={s.full}
                      onClick={() => {
                        setTime(s.time);
                        setStep('form');
                      }}
                      className={`rounded-lg border py-2 text-sm transition ${
                        s.full
                          ? 'cursor-not-allowed border-border bg-muted/40 text-muted-foreground/40 line-through'
                          : 'border-border bg-background hover:border-primary hover:bg-muted'
                      }`}
                    >
                      {s.time}
                    </button>
                  ))}
                  {slots.length === 0 && (
                    <p className="col-span-4 py-4 text-center text-sm text-muted-foreground">
                      この日は予約枠がありません
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ===== お客様情報フォーム ===== */}
      {step === 'form' && (
        <div className="space-y-4 p-5">
          <button
            type="button"
            onClick={() => {
              setStep('pick');
              setError('');
            }}
            className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ChevronLeft className="h-4 w-4" /> 日時を選び直す
          </button>

          <div className="rounded-lg border border-border bg-muted/40 px-4 py-3 text-sm">
            <div className="font-medium">
              {labelFor(date)}（{WD[new Date(`${date}T00:00:00`).getDay()]}） {time}
            </div>
            {(service || (hasStaff && staff)) && (
              <div className="mt-0.5 text-muted-foreground">
                {service && <span>{service}</span>}
                {service && hasStaff && staff && <span> ・ </span>}
                {hasStaff && staff && <span>担当: {staff}</span>}
              </div>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="bk-name">お名前</Label>
            <Input id="bk-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="山田 花子" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="bk-contact">電話番号 または メール</Label>
            <Input
              id="bk-contact"
              value={contact}
              onChange={(e) => setContact(e.target.value)}
              placeholder="090-1234-5678"
            />
          </div>
          {config.askPartySize && (
            <div className="space-y-1.5">
              <Label htmlFor="bk-party">人数</Label>
              <Input
                id="bk-party"
                type="number"
                min={1}
                max={20}
                value={partySize}
                onChange={(e) => setPartySize(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
              />
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="bk-notes">ご要望（任意）</Label>
            <textarea
              id="bk-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value.slice(0, 500))}
              rows={3}
              className="w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
            />
          </div>

          {error && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          )}

          <Button className="w-full" disabled={!canSubmit} onClick={confirm}>
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            この内容で予約する
          </Button>
        </div>
      )}

      {/* ===== 完了 ===== */}
      {step === 'done' && (
        <div className="flex flex-col items-center gap-3 p-8 text-center">
          <div className="grid h-16 w-16 place-items-center rounded-full bg-primary/10">
            <Check className="h-8 w-8 text-primary" />
          </div>
          <h4 className="text-lg font-semibold">予約が完了しました</h4>
          <p className="text-sm text-muted-foreground">
            {labelFor(date)}（{WD[new Date(`${date}T00:00:00`).getDay()]}） {time} にご予約を承りました。
          </p>
          <Button variant="outline" className="mt-2" onClick={reset}>
            別の予約をする
          </Button>
        </div>
      )}
    </div>
  );
}
