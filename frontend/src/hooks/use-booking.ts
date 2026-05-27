'use client';

/**
 * 予約ブロックの裏方フック。
 *
 * 営業時間・枠長・定員などの「設定」を受け取り、
 *  - loadSlots(date, staff?) : その日の空き枠を計算
 *  - book(input)             : 予約を作成（満席は API が 409 で弾く）
 * を提供する。空き枠の定義はここ（フロント）が持ち、API はステートレスに保つ。
 */
import { useCallback, useMemo, useState } from 'react';

export type BookingConfig = {
  /** artifact_slug — どの店舗/サイトの予約か（必須） */
  slug: string;
  /** 営業開始 'HH:MM' */
  openTime: string;
  /** 営業終了 'HH:MM'（この時刻ちょうどの枠は作らない） */
  closeTime: string;
  /** 1枠の長さ（分） */
  slotMinutes: number;
  /** 1枠の定員（スタッフ指名なし時）。default 1 */
  capacityPerSlot?: number;
  /** メニュー一覧（指定すると選択UIが出る） */
  services?: string[];
  /** スタッフ一覧（指定すると指名UIが出る。指名ありは枠定員=1） */
  staff?: string[];
  /** 定休日 (0=日..6=土) */
  closedWeekdays?: number[];
  /** 人数入力を出す（飲食向け）。default false */
  askPartySize?: boolean;
};

export type SlotInfo = { time: string; remaining: number; full: boolean };

export type BookInput = {
  date: string;
  time: string;
  name: string;
  contact: string;
  service?: string;
  staff?: string;
  partySize?: number;
  notes?: string;
};

type SlotBooking = {
  start_time: string;
  staff?: string | null;
  party_size: number;
  status: string;
};

function buildSlotTimes(open: string, close: string, step: number): string[] {
  const toMin = (s: string) => {
    const [h, m] = s.split(':').map(Number);
    return h * 60 + m;
  };
  const pad = (n: number) => String(n).padStart(2, '0');
  const out: string[] = [];
  if (!open || !close || step <= 0) return out;
  for (let t = toMin(open); t + step <= toMin(close); t += step) {
    out.push(`${pad(Math.floor(t / 60))}:${pad(t % 60)}`);
  }
  return out;
}

export function useBooking(config: BookingConfig) {
  const capacity = config.capacityPerSlot ?? 1;
  const slotTimes = useMemo(
    () => buildSlotTimes(config.openTime, config.closeTime, config.slotMinutes),
    [config.openTime, config.closeTime, config.slotMinutes],
  );
  const [slots, setSlots] = useState<SlotInfo[]>([]);
  const [loadingSlots, setLoadingSlots] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const loadSlots = useCallback(
    async (date: string, staff?: string) => {
      setLoadingSlots(true);
      try {
        const res = await fetch(
          `/api/v1/bookings/slots?slug=${encodeURIComponent(config.slug)}&date=${encodeURIComponent(date)}`,
        );
        const existing: SlotBooking[] = res.ok ? await res.json() : [];
        const info: SlotInfo[] = slotTimes.map((time) => {
          const at = existing.filter(
            (b) => b.start_time === time && (staff ? b.staff === staff : true),
          );
          // 指名ありなら「そのスタッフは1枠1件」、指名なしなら定員（人数合算）
          const cap = staff ? 1 : capacity;
          const used = staff
            ? at.length
            : at.reduce((n, b) => n + (b.party_size || 1), 0);
          return { time, remaining: Math.max(0, cap - used), full: used >= cap };
        });
        setSlots(info);
      } catch {
        // 取得失敗時は全枠を空き扱いにして予約を妨げない（API 側で最終チェック）
        setSlots(slotTimes.map((time) => ({ time, remaining: capacity, full: false })));
      } finally {
        setLoadingSlots(false);
      }
    },
    [config.slug, slotTimes, capacity],
  );

  const book = useCallback(
    async (input: BookInput): Promise<{ ok: boolean; error?: string }> => {
      setSubmitting(true);
      try {
        const res = await fetch('/api/v1/bookings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            artifact_slug: config.slug,
            customer_name: input.name,
            contact: input.contact,
            booking_date: input.date,
            start_time: input.time,
            service: input.service ?? null,
            staff: input.staff ?? null,
            party_size: input.partySize ?? 1,
            notes: input.notes ?? null,
            duration_min: config.slotMinutes,
            capacity: input.staff ? 1 : capacity,
          }),
        });
        if (!res.ok) {
          const j = (await res.json().catch(() => ({}))) as { detail?: string };
          return { ok: false, error: j.detail || '予約に失敗しました' };
        }
        return { ok: true };
      } catch {
        return { ok: false, error: '通信に失敗しました。時間をおいて再度お試しください' };
      } finally {
        setSubmitting(false);
      }
    },
    [config.slug, config.slotMinutes, capacity],
  );

  return { slots, loadingSlots, submitting, loadSlots, book };
}
