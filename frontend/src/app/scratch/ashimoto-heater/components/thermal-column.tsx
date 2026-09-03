"use client";

import * as React from "react";
import { motion, useReducedMotion } from "framer-motion";

/**
 * 垂直の温度スケール。
 * 暖房された部屋の中で、床に近いほど温度が下がっていく（温度成層）ことを1枚で見せる。
 * 前作（置く床暖房）が部屋の平面図だったのに対し、こちらは縦断面で構造を変えている。
 *
 * 数値はエアコン暖房時の一般的な温度分布。設定温度どおりに暖まるのは人の頭の高さで、
 * 足元は室温より数℃低いままになる。この差そのものがこの製品の存在理由になる。
 */

type Level = {
  /** 床からの高さ（cm） */
  h: number;
  temp: number;
  label: string;
  note?: string;
  /** 足元＝この製品が解決する層 */
  target?: boolean;
};

const LEVELS: Level[] = [
  { h: 120, temp: 24, label: "頭のあたり", note: "設定温度どおり" },
  { h: 70, temp: 21, label: "机の高さ" },
  { h: 40, temp: 19, label: "ひざ下" },
  { h: 10, temp: 16, label: "足元", note: "室温より5〜8℃低い", target: true },
];

/** 高さ(cm) を SVG の y 座標に写す。0cm を下端、130cm を上端に置く */
function toY(h: number) {
  const top = 24;
  const bottom = 300;
  return bottom - (h / 130) * (bottom - top);
}

export function ThermalColumn() {
  const reduce = useReducedMotion();

  return (
    <figure className="w-full">
      <svg
        viewBox="0 0 404 340"
        className="w-full"
        role="img"
        aria-label="暖房中の部屋の高さごとの温度。頭のあたりは24℃だが、床から10cmの足元は16℃までしか上がらない。"
      >
        {/* 空気の温度勾配（上=暖 / 下=冷）。青は必ず熾火と対で出す */}
        <defs>
          <linearGradient id="ah-air" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--ah-ember)" stopOpacity="0.16" />
            <stop offset="45%" stopColor="var(--ah-ember)" stopOpacity="0.05" />
            <stop offset="72%" stopColor="var(--ah-cold)" stopOpacity="0.06" />
            <stop offset="100%" stopColor="var(--ah-cold)" stopOpacity="0.2" />
          </linearGradient>
        </defs>

        <rect
          x="18"
          y="24"
          width="150"
          height="276"
          fill="url(#ah-air)"
          stroke="var(--border)"
          strokeWidth="1"
        />

        {/* 床 */}
        <line
          x1="18"
          y1="300"
          x2="362"
          y2="300"
          stroke="var(--foreground)"
          strokeWidth="1.5"
        />
        <text
          x="18"
          y="318"
          className="font-num"
          fontSize="11"
          fill="var(--muted-foreground)"
          letterSpacing="0.08em"
        >
          FLOOR
        </text>

        {LEVELS.map((lv, i) => {
          const y = toY(lv.h);
          return (
            <motion.g
              key={lv.h}
              initial={reduce ? false : { opacity: 0, x: -10 }}
              whileInView={reduce ? undefined : { opacity: 1, x: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.5, delay: i * 0.1, ease: "easeOut" }}
            >
              {/* 高さの基準線 */}
              <line
                x1="18"
                y1={y}
                x2={lv.target ? 362 : 300}
                y2={y}
                stroke={lv.target ? "var(--ah-ember)" : "var(--border)"}
                strokeWidth={lv.target ? 1.25 : 1}
                strokeDasharray={lv.target ? undefined : "3 4"}
              />
              {/* 高さ表記 */}
              <text
                x="24"
                y={y - 8}
                className="font-num"
                fontSize="12"
                fill="var(--muted-foreground)"
              >
                {lv.h}cm
              </text>
              {/* 温度。足元の行だけ基準線が数字を貫くので、地の色で下敷きを敷いて抜く */}
              {lv.target && (
                <rect
                  x="180"
                  y={y - 26}
                  width="70"
                  height="36"
                  fill="var(--background)"
                />
              )}
              <text
                x="188"
                y={y + 7}
                className="font-num"
                fontSize={lv.target ? "30" : "24"}
                fill={lv.target ? "var(--ah-ember)" : "var(--foreground)"}
              >
                {lv.temp}
                <tspan fontSize="13" dy="-8" dx="1">
                  ℃
                </tspan>
              </text>
              {/* ラベル。
                  足元の行は基準線が全幅に伸び、床の線もすぐ下にあるため、
                  ラベルと注記をどちらも線の上側へ逃がして重なりを避ける。 */}
              <text
                x={lv.target ? 252 : 244}
                y={lv.target ? y - 10 : y + 4}
                fontSize="12"
                fill={lv.target ? "var(--foreground)" : "var(--muted-foreground)"}
                fontWeight={lv.target ? 700 : 400}
              >
                {lv.label}
              </text>
              {lv.note && (
                <text
                  x={lv.target ? 252 : 244}
                  y={lv.target ? y - 26 : y + 21}
                  fontSize="10.5"
                  fill="var(--muted-foreground)"
                >
                  {lv.note}
                </text>
              )}
            </motion.g>
          );
        })}

        {/* 足元だけが取り残されている、という帯 */}
        <motion.rect
          x="18"
          y={toY(10)}
          width="150"
          height={300 - toY(10)}
          fill="var(--ah-cold)"
          fillOpacity="0.14"
          initial={reduce ? false : { opacity: 0 }}
          whileInView={reduce ? undefined : { opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6, delay: 0.45 }}
        />
      </svg>
      <figcaption className="mt-4 text-xs leading-relaxed text-muted-foreground">
        エアコンで室温を24℃にしたときの、高さごとの温度の目安。暖かい空気は天井へ上がるため、
        床の近くだけが取り残されます。数値は木造住宅での一般的な例で、建物の断熱や外気温によって変わります。
      </figcaption>
    </figure>
  );
}
