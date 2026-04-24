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
  | "hook";

export const VEHICLES: Record<
  VehicleKey,
  { label: string; icon: LucideIcon; description: string }
> = {
  tailgate: {
    label: "テールゲートリフタ",
    icon: ArrowUpDown,
    description: "荷台昇降装置の油圧・電装系修理",
  },
  dump: {
    label: "ダンプトラック",
    icon: Truck,
    description: "架装・油圧シリンダ・サブフレーム修理",
  },
  garbage: {
    label: "塵芥車（パッカー車）",
    icon: Container,
    description: "回転板・圧縮板・油圧ユニット整備",
  },
  crane: {
    label: "CBクレーン／積載車",
    icon: Wrench,
    description: "ブーム・ウインチ・旋回部の整備",
  },
  tanker: {
    label: "タンク・ローリ車",
    icon: Droplets,
    description: "タンク本体・バルブ・配管の点検修理",
  },
  aerial: {
    label: "高所作業車",
    icon: Construction,
    description: "伸縮ブーム・バスケット・安全装置点検",
  },
  mixer: {
    label: "ミキサ車",
    icon: RotateCcw,
    description: "ドラム・減速機・シューターの整備",
  },
  feed: {
    label: "飼料運搬車",
    icon: Boxes,
    description: "排出スクリュー・シュート・駆動部",
  },
  hook: {
    label: "脱着車（アームロール）",
    icon: Package,
    description: "フック・アーム・油圧ユニット整備",
  },
};
