"use client";

import * as React from "react";
import { motion, useReducedMotion } from "framer-motion";

/**
 * 消費電力の横バー比較。
 * この製品の訴求は「大きさ」ではなく「小ささ」なので、バーが極端に短いこと自体が主張になる。
 *
 * 比較はすべて定格消費電力どうし。実際の使用時は機器ごとに運転が変わるため、
 * 「定格どうしの比較」であることを図の外に必ず明記する（景表法）。
 * 電気代は 31円/kWh（公益社団法人 全国家庭電気製品公正取引協議会の目安単価）で計算。
 */

const RATE_YEN_PER_KWH = 31;

type Row = {
  name: string;
  watt: number;
  note?: string;
  self?: boolean;
};

const ROWS: Row[] = [
  { name: "セラミックファンヒーター", watt: 1200 },
  { name: "エアコン暖房（10畳用）", watt: 1000, note: "暖房時の定格消費電力" },
  { name: "電気ストーブ", watt: 800 },
  { name: "足元パネルヒーター", watt: 150, note: "この製品", self: true },
];

const MAX = 1200;

/**
 * 1時間あたりの電気代。
 * toFixed だけに任せると 4.65 が浮動小数点の都合で 4.6 に落ち、
 * 本文に書いた「1時間4.7円」と表の数字がずれる。先に丸めてから桁を固定する。
 */
function yen(watt: number) {
  // 先に整数どうしで掛けてから割る。150/1000*31 の順だと 4.65 が 4.6499… になり、
  // 四捨五入で 4.6 に落ちて本文の「1時間4.7円」とずれる。
  return (Math.round((watt * RATE_YEN_PER_KWH) / 100) / 10).toFixed(1);
}

export function PowerCompare() {
  const reduce = useReducedMotion();

  return (
    <div className="w-full">
      <div className="divide-y divide-border border-y border-border">
        {ROWS.map((r, i) => (
          <div key={r.name} className="py-6 sm:py-7">
            <div className="flex items-baseline justify-between gap-4">
              <div>
                <div
                  className={
                    r.self
                      ? "text-sm font-bold text-foreground sm:text-base"
                      : "text-sm text-muted-foreground"
                  }
                >
                  {r.name}
                </div>
                {r.note && (
                  <div className="mt-1 text-[11px] text-muted-foreground">
                    {r.note}
                  </div>
                )}
              </div>
              <div className="shrink-0 text-right">
                <div
                  className={
                    r.self
                      ? "font-num text-3xl leading-none text-primary sm:text-4xl"
                      : "font-num text-2xl leading-none text-muted-foreground sm:text-3xl"
                  }
                >
                  {r.watt.toLocaleString()}
                  <span className="ml-0.5 align-top text-[0.5em]">W</span>
                </div>
                <div
                  className={
                    r.self
                      ? "mt-1.5 text-xs font-medium text-foreground"
                      : "mt-1.5 text-xs text-muted-foreground"
                  }
                >
                  1時間 {yen(r.watt)}円
                </div>
              </div>
            </div>

            {/* 下地を border 色にして、行の区切り罫線とバーを見分けられるようにする */}
            <div className="mt-5 h-[5px] w-full bg-border/70">
              <motion.div
                className="h-full"
                style={{
                  backgroundColor: r.self
                    ? "var(--ah-ember)"
                    : "var(--muted-foreground)",
                  opacity: r.self ? 1 : 0.5,
                }}
                initial={reduce ? false : { width: 0 }}
                whileInView={
                  reduce ? undefined : { width: `${(r.watt / MAX) * 100}%` }
                }
                viewport={{ once: true, margin: "-60px" }}
                transition={{ duration: 0.8, delay: i * 0.08, ease: "easeOut" }}
              />
            </div>
          </div>
        ))}
      </div>

      <p className="mt-5 text-xs leading-[1.9] text-muted-foreground">
        いずれもカタログ上の定格消費電力どうしの比較です。実際の電気の使い方は、部屋の広さ・外気温・
        運転のしかたで変わります。電気代は1kWhあたり31円で計算した目安です。
      </p>
    </div>
  );
}
