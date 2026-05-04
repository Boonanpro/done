import {
  Truck,
  Container,
  ArrowUpDown,
  Wrench,
  Droplets,
  Construction,
  RotateCcw,
  Boxes,
  Package,
  Snowflake,
  Wind,
  type LucideIcon,
} from "lucide-react";

export type VehicleKey =
  | "tailgate"
  | "dump"
  | "garbage"
  | "crane"
  | "tanker"
  | "aerial"
  | "mixer"
  | "feed"
  | "hook"
  | "snowplow"
  | "vacuum";

export const VEHICLES: Record<
  VehicleKey,
  { label: string; icon: LucideIcon; image: string; description: string }
> = {
  tailgate: {
    label: "テールゲートリフタ",
    icon: ArrowUpDown,
    image: "/kikkawa/vehicles/tailgate.png",
    description: "荷台昇降装置の油圧・電装系修理",
  },
  dump: {
    label: "ダンプトラック",
    icon: Truck,
    image: "/kikkawa/vehicles/dump.png",
    description: "架装・油圧シリンダ・サブフレーム修理",
  },
  garbage: {
    label: "塵芥車（パッカー車）",
    icon: Container,
    image: "/kikkawa/vehicles/garbage.png",
    description: "回転板・圧縮板・油圧ユニット整備",
  },
  crane: {
    label: "CBクレーン／積載車",
    icon: Wrench,
    image: "/kikkawa/vehicles/crane.png",
    description: "ブーム・ウインチ・旋回部の整備",
  },
  tanker: {
    label: "タンク・ローリ車",
    icon: Droplets,
    image: "/kikkawa/vehicles/tanker.png",
    description: "タンク本体・バルブ・配管の点検修理",
  },
  aerial: {
    label: "高所作業車",
    icon: Construction,
    image: "/kikkawa/vehicles/aerial.png",
    description: "伸縮ブーム・バスケット・安全装置点検",
  },
  mixer: {
    label: "ミキサ車",
    icon: RotateCcw,
    image: "/kikkawa/vehicles/mixer.png",
    description: "ドラム・減速機・シューターの整備",
  },
  feed: {
    label: "飼料運搬車",
    icon: Boxes,
    image: "/kikkawa/vehicles/feed.png",
    description: "排出スクリュー・シュート・駆動部",
  },
  hook: {
    label: "脱着車（アームロール）",
    icon: Package,
    image: "/kikkawa/vehicles/hook.png",
    description: "フック・アーム・油圧ユニット整備",
  },
  snowplow: {
    label: "圧雪車",
    icon: Snowflake,
    image: "/kikkawa/vehicles/snowplow.png",
    description: "ブレード・ローラー・油圧駆動部の整備",
  },
  vacuum: {
    label: "吸引車",
    icon: Wind,
    image: "/kikkawa/vehicles/vacuum.png",
    description: "真空ポンプ・タンク・配管の点検修理",
  },
};
