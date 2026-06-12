"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import {
  Search,
  ShoppingCart,
  Plus,
  Minus,
  Trash2,
  FileText,
  Send,
  Box,
  Truck,
  Sparkles,
  Wrench,
  Layers,
  RotateCcw,
  X,
  Check,
  AlertCircle,
  Info,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  CATEGORY_LABEL,
  MESH_LABEL,
  PARTS,
  STOCK_LABEL,
  VEHICLE_MODELS,
  type Part,
  type PartCategory,
  type PartMeshId,
} from "./mock-data";

// 3DビューアはSSR無効でロード
const ArmRollModel = dynamic(
  () => import("./components/armroll-model").then((m) => m.ArmRollModel),
  { ssr: false, loading: () => <ViewerLoader /> }
);

function ViewerLoader() {
  return (
    <div className="flex h-full w-full items-center justify-center bg-[#0b1220]">
      <div className="flex flex-col items-center gap-3 text-muted-foreground">
        <Box className="h-8 w-8 animate-pulse" />
        <span className="text-sm">3Dビューアを読み込み中…</span>
      </div>
    </div>
  );
}

const CATEGORY_TABS: { value: PartCategory | "all"; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "arm", label: "アーム" },
  { value: "hydraulic", label: "油圧" },
  { value: "jack", label: "ジャッキ" },
  { value: "frame", label: "フレーム" },
  { value: "electrical", label: "電装" },
  { value: "chassis", label: "シャシ" },
  { value: "accessory", label: "付属" },
];

type CartItem = { partId: string; quantity: number };

export default function ArmRollPage() {
  const [vehicleId, setVehicleId] = useState<string>("cca101-20");
  const [selectedMeshId, setSelectedMeshId] = useState<PartMeshId | null>(null);
  const [selectedPartId, setSelectedPartId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<PartCategory | "all">("all");
  const [cart, setCart] = useState<CartItem[]>([]);
  const [showQuoteDialog, setShowQuoteDialog] = useState(false);
  const [showOrderConfirm, setShowOrderConfirm] = useState(false);
  const [orderPlaced, setOrderPlaced] = useState(false);

  const vehicle = useMemo(
    () => VEHICLE_MODELS.find((v) => v.id === vehicleId) ?? VEHICLE_MODELS[0],
    [vehicleId]
  );

  const compatibleParts = useMemo(
    () => PARTS.filter((p) => p.modelCompat.includes(vehicle.modelCode)),
    [vehicle]
  );

  const filteredParts = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return compatibleParts.filter((p) => {
      if (categoryFilter !== "all" && p.category !== categoryFilter) return false;
      if (!q) return true;
      const hay = `${p.name} ${p.partNumber} ${p.nameRomaji ?? ""} ${
        p.imageRef ?? ""
      } ${MESH_LABEL[p.meshId]}`.toLowerCase();
      return hay.includes(q);
    });
  }, [compatibleParts, categoryFilter, searchQuery]);

  const highlightedMeshIds: PartMeshId[] = useMemo(() => {
    if (!searchQuery.trim() && categoryFilter === "all") return [];
    return Array.from(new Set(filteredParts.map((p) => p.meshId)));
  }, [filteredParts, searchQuery, categoryFilter]);

  // 部位(meshId)を選ぶと、その部位の先頭候補を選択部品にする
  const selectMesh = (meshId: PartMeshId | null) => {
    setSelectedMeshId(meshId);
    if (!meshId) {
      setSelectedPartId(null);
      return;
    }
    const first =
      filteredParts.find((p) => p.meshId === meshId) ??
      compatibleParts.find((p) => p.meshId === meshId);
    setSelectedPartId(first?.id ?? null);
  };

  const selectedPart = useMemo(() => {
    if (selectedPartId) {
      const byId = compatibleParts.find((p) => p.id === selectedPartId);
      if (byId && byId.meshId === selectedMeshId) return byId;
    }
    if (!selectedMeshId) return null;
    const fromFiltered = filteredParts.find((p) => p.meshId === selectedMeshId);
    if (fromFiltered) return fromFiltered;
    return compatibleParts.find((p) => p.meshId === selectedMeshId) ?? null;
  }, [selectedPartId, selectedMeshId, filteredParts, compatibleParts]);

  const meshCandidates = useMemo(() => {
    if (!selectedMeshId) return [];
    return compatibleParts.filter((p) => p.meshId === selectedMeshId);
  }, [selectedMeshId, compatibleParts]);

  const cartTotal = useMemo(() => {
    return cart.reduce((sum, item) => {
      const part = PARTS.find((p) => p.id === item.partId);
      return sum + (part?.price ?? 0) * item.quantity;
    }, 0);
  }, [cart]);

  const addToCart = (partId: string) => {
    setCart((prev) => {
      const existing = prev.find((item) => item.partId === partId);
      if (existing) {
        return prev.map((item) =>
          item.partId === partId ? { ...item, quantity: item.quantity + 1 } : item
        );
      }
      return [...prev, { partId, quantity: 1 }];
    });
  };

  const removeFromCart = (partId: string) => {
    setCart((prev) => prev.filter((item) => item.partId !== partId));
  };

  const updateQuantity = (partId: string, delta: number) => {
    setCart((prev) =>
      prev
        .map((item) =>
          item.partId === partId
            ? { ...item, quantity: Math.max(0, item.quantity + delta) }
            : item
        )
        .filter((item) => item.quantity > 0)
    );
  };

  const handlePlaceOrder = () => {
    setOrderPlaced(true);
    setTimeout(() => {
      setShowOrderConfirm(false);
      setOrderPlaced(false);
      setCart([]);
    }, 2000);
  };

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      {/* ヘッダー */}
      <header className="flex items-center justify-between border-b border-border bg-card/60 px-6 py-3 backdrop-blur">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-gradient-to-br from-orange-500 to-amber-600 text-white">
            <Truck className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-base font-semibold tracking-tight">
              ShinMaywa Parts 3D
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                10t アームロール 電子パーツカタログ (Prototype)
              </span>
            </h1>
            <p className="text-xs text-muted-foreground">
              機種 CCA101*-20 / 平面図から各部品を3D化・クリックで分解
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-amber-400 border-amber-400/30">
            <Sparkles className="mr-1 h-3 w-3" />
            実カタログ名称 + 仮品番
          </Badge>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowQuoteDialog(true)}
            disabled={cart.length === 0}
          >
            <FileText className="mr-2 h-4 w-4" />
            見積書 ({cart.length})
          </Button>
        </div>
      </header>

      {/* メイン3カラム */}
      <div className="grid min-h-0 flex-1 grid-cols-[320px_1fr_380px] grid-rows-[minmax(0,1fr)] overflow-hidden">
        {/* 左ペイン */}
        <aside className="flex min-h-0 flex-col overflow-hidden border-r border-border bg-card/30">
          <div className="space-y-3 border-b border-border p-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                機種選択
              </label>
              <Select value={vehicleId} onValueChange={setVehicleId}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {VEHICLE_MODELS.map((v) => (
                    <SelectItem key={v.id} value={v.id}>
                      {v.modelCode}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="mt-2 rounded-md bg-muted/40 p-2 text-xs">
                <div className="font-mono text-foreground">
                  パーツカタログNo: {vehicle.catalogCode}
                </div>
                <div className="mt-0.5 text-muted-foreground">{vehicle.series}</div>
                <div className="mt-0.5 text-muted-foreground">
                  {vehicle.description}
                </div>
              </div>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                部品検索
              </label>
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="部品名・符号(例 03-01)で検索"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9"
                />
                {searchQuery && (
                  <button
                    type="button"
                    onClick={() => setSearchQuery("")}
                    className="absolute right-2 top-2.5 text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>
              {searchQuery && (
                <p className="mt-1 text-xs text-blue-400">
                  該当部位を3Dビューアで青く表示中
                </p>
              )}
            </div>

            <Tabs
              value={categoryFilter}
              onValueChange={(v) => setCategoryFilter(v as PartCategory | "all")}
            >
              <TabsList className="grid w-full grid-cols-4 h-auto">
                {CATEGORY_TABS.slice(0, 4).map((tab) => (
                  <TabsTrigger key={tab.value} value={tab.value} className="text-xs">
                    {tab.label}
                  </TabsTrigger>
                ))}
              </TabsList>
              <TabsList className="mt-1 grid w-full grid-cols-4 h-auto">
                {CATEGORY_TABS.slice(4).map((tab) => (
                  <TabsTrigger key={tab.value} value={tab.value} className="text-xs">
                    {tab.label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          </div>

          <ScrollArea className="min-h-0 flex-1">
            <div className="space-y-1 p-2">
              {filteredParts.length === 0 && (
                <div className="flex flex-col items-center justify-center gap-2 py-12 text-muted-foreground">
                  <AlertCircle className="h-6 w-6" />
                  <p className="text-sm">該当部品なし</p>
                </div>
              )}
              {filteredParts.map((part) => (
                <PartListItem
                  key={part.id}
                  part={part}
                  isSelected={selectedPart?.id === part.id}
                  onClick={() => {
                    setSelectedMeshId(part.meshId);
                    setSelectedPartId(part.id);
                  }}
                />
              ))}
            </div>
          </ScrollArea>

          <div className="border-t border-border bg-muted/30 p-3 text-center text-xs text-muted-foreground">
            {compatibleParts.length}点中 {filteredParts.length}点を表示
          </div>
        </aside>

        {/* 中央: 3Dビューア */}
        <main className="relative min-h-0 overflow-hidden">
          <ArmRollModel
            selectedMeshId={selectedMeshId}
            highlightedMeshIds={highlightedMeshIds}
            onSelect={selectMesh}
          />

          <div className="pointer-events-none absolute left-4 top-4 space-y-1.5 text-xs text-white/70">
            <div className="rounded bg-black/40 px-2 py-1 backdrop-blur-sm">
              <span className="font-mono">ドラッグ</span> / 回転
            </div>
            <div className="rounded bg-black/40 px-2 py-1 backdrop-blur-sm">
              <span className="font-mono">ホイール</span> / ズーム
            </div>
            <div className="rounded bg-black/40 px-2 py-1 backdrop-blur-sm">
              <span className="font-mono">クリック</span> / 部品が分解
            </div>
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              selectMesh(null);
              setSearchQuery("");
              setCategoryFilter("all");
            }}
            className="absolute right-4 top-4 bg-black/40 backdrop-blur-sm hover:bg-black/60"
          >
            <RotateCcw className="mr-1 h-3 w-3" />
            リセット
          </Button>

          <div className="absolute bottom-4 left-4 flex items-center gap-3 rounded-md bg-black/40 px-3 py-2 text-xs text-white/80 backdrop-blur-sm">
            <div className="flex items-center gap-1.5">
              <div className="h-3 w-3 rounded-sm bg-amber-400" />
              選択中
            </div>
            <div className="flex items-center gap-1.5">
              <div className="h-3 w-3 rounded-sm bg-blue-400" />
              検索ヒット
            </div>
          </div>
        </main>

        {/* 右ペイン */}
        <aside className="flex min-h-0 flex-col overflow-hidden border-l border-border bg-card/30">
          <div className="min-h-0 flex-1 overflow-hidden">
            <PartDetail
              part={selectedPart}
              meshCandidates={meshCandidates}
              selectedMeshId={selectedMeshId}
              onAddToCart={addToCart}
              onSelectAlt={(partId) => setSelectedPartId(partId)}
            />
          </div>

          <Separator />

          <div className="flex flex-col bg-muted/20 p-4">
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ShoppingCart className="h-4 w-4 text-muted-foreground" />
                <span className="text-sm font-medium">見積カート</span>
                <Badge variant="secondary">{cart.length}</Badge>
              </div>
              {cart.length > 0 && (
                <button
                  type="button"
                  onClick={() => setCart([])}
                  className="text-xs text-muted-foreground hover:text-foreground"
                >
                  クリア
                </button>
              )}
            </div>

            {cart.length === 0 ? (
              <div className="rounded-md border border-dashed border-border py-4 text-center text-xs text-muted-foreground">
                部品を3Dから選んで追加
              </div>
            ) : (
              <ScrollArea className="max-h-48">
                <div className="space-y-1.5">
                  {cart.map((item) => {
                    const part = PARTS.find((p) => p.id === item.partId);
                    if (!part) return null;
                    return (
                      <div
                        key={item.partId}
                        className="flex items-center gap-2 rounded-md bg-card p-2 text-xs"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="truncate font-medium">{part.name}</div>
                          <div className="font-mono text-[10px] text-muted-foreground">
                            {part.partNumber}
                          </div>
                        </div>
                        <div className="flex items-center gap-0.5">
                          <button
                            type="button"
                            onClick={() => updateQuantity(item.partId, -1)}
                            className="rounded p-0.5 hover:bg-muted"
                          >
                            <Minus className="h-3 w-3" />
                          </button>
                          <span className="w-6 text-center font-mono">
                            {item.quantity}
                          </span>
                          <button
                            type="button"
                            onClick={() => updateQuantity(item.partId, 1)}
                            className="rounded p-0.5 hover:bg-muted"
                          >
                            <Plus className="h-3 w-3" />
                          </button>
                        </div>
                        <button
                          type="button"
                          onClick={() => removeFromCart(item.partId)}
                          className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-destructive"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    );
                  })}
                </div>
              </ScrollArea>
            )}

            <div className="mt-3 flex items-center justify-between border-t border-border pt-2">
              <span className="text-xs text-muted-foreground">合計</span>
              <span className="font-mono text-lg font-semibold">
                ¥{cartTotal.toLocaleString()}
              </span>
            </div>

            <div className="mt-2 grid grid-cols-2 gap-1.5">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowQuoteDialog(true)}
                disabled={cart.length === 0}
              >
                <FileText className="mr-1 h-3 w-3" />
                見積書
              </Button>
              <Button
                size="sm"
                onClick={() => setShowOrderConfirm(true)}
                disabled={cart.length === 0}
              >
                <Send className="mr-1 h-3 w-3" />
                発注
              </Button>
            </div>
          </div>
        </aside>
      </div>

      <QuoteDialog
        open={showQuoteDialog}
        onOpenChange={setShowQuoteDialog}
        cart={cart}
        cartTotal={cartTotal}
        vehicle={vehicle}
      />

      <Dialog open={showOrderConfirm} onOpenChange={setShowOrderConfirm}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{orderPlaced ? "発注完了" : "発注内容の確認"}</DialogTitle>
            <DialogDescription>
              {orderPlaced
                ? "新明和工業に発注を送信しました。"
                : "以下の内容で発注します。"}
            </DialogDescription>
          </DialogHeader>
          {orderPlaced ? (
            <div className="flex flex-col items-center gap-3 py-6">
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-emerald-500/20">
                <Check className="h-8 w-8 text-emerald-400" />
              </div>
              <div className="text-center">
                <div className="font-mono text-sm">
                  発注番号: ORD-{Date.now().toString().slice(-8)}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  納期通知メールが届きます
                </div>
              </div>
            </div>
          ) : (
            <>
              <div className="space-y-2 py-2">
                <div className="rounded-md bg-muted/50 p-3 text-sm">
                  <div className="font-medium">{vehicle.modelCode}</div>
                  <div className="text-xs text-muted-foreground">
                    {vehicle.catalogCode}
                  </div>
                </div>
                <div className="space-y-1 text-sm">
                  {cart.map((item) => {
                    const part = PARTS.find((p) => p.id === item.partId);
                    if (!part) return null;
                    return (
                      <div key={item.partId} className="flex justify-between text-xs">
                        <span>
                          {part.name} × {item.quantity}
                        </span>
                        <span className="font-mono">
                          ¥{(part.price * item.quantity).toLocaleString()}
                        </span>
                      </div>
                    );
                  })}
                </div>
                <Separator />
                <div className="flex justify-between text-sm">
                  <span>合計 (税抜)</span>
                  <span className="font-mono font-semibold">
                    ¥{cartTotal.toLocaleString()}
                  </span>
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setShowOrderConfirm(false)}>
                  キャンセル
                </Button>
                <Button onClick={handlePlaceOrder}>
                  <Send className="mr-2 h-4 w-4" />
                  確定して送信
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ──────────────────────────────────────────────
function PartListItem({
  part,
  isSelected,
  onClick,
}: {
  part: Part;
  isSelected: boolean;
  onClick: () => void;
}) {
  const stock = STOCK_LABEL[part.stock];
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-md border p-2 text-left text-xs transition ${
        isSelected
          ? "border-amber-400/50 bg-amber-400/10"
          : "border-transparent hover:border-border hover:bg-card"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            {part.imageRef && part.imageRef !== "—" && (
              <span className="shrink-0 rounded bg-muted px-1 font-mono text-[9px] text-muted-foreground">
                {part.imageRef}
              </span>
            )}
            <span className="truncate font-medium text-foreground">{part.name}</span>
          </div>
          <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">
            {part.partNumber}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Badge variant="outline" className={`${stock.color} text-[9px] px-1`}>
            {stock.label}
          </Badge>
          <span className="font-mono text-[10px] text-muted-foreground">
            {part.price > 0 ? `¥${part.price.toLocaleString()}` : "—"}
          </span>
        </div>
      </div>
    </button>
  );
}

// ──────────────────────────────────────────────
function PartDetail({
  part,
  meshCandidates,
  selectedMeshId,
  onAddToCart,
  onSelectAlt,
}: {
  part: Part | null;
  meshCandidates: Part[];
  selectedMeshId: PartMeshId | null;
  onAddToCart: (partId: string) => void;
  onSelectAlt: (partId: string) => void;
}) {
  if (!part || !selectedMeshId) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center text-muted-foreground">
        <Layers className="h-10 w-10" />
        <div>
          <p className="text-sm">3Dモデルから部品を選択</p>
          <p className="mt-1 text-xs">または左の検索・リストから選んでください</p>
        </div>
      </div>
    );
  }

  const stock = STOCK_LABEL[part.stock];
  const partLabel = MESH_LABEL[part.meshId];

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border bg-card/40 px-4 py-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Wrench className="h-3 w-3" />
          選択中の部位
        </div>
        <h2 className="mt-1 text-base font-semibold">{partLabel}</h2>
        <div className="mt-0.5 text-xs text-muted-foreground">
          カテゴリ: {CATEGORY_LABEL[part.category]}
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-3 p-4">
          {meshCandidates.length > 1 && (
            <Card className="border-blue-400/30 bg-blue-400/5">
              <CardHeader className="p-3 pb-1">
                <CardTitle className="text-xs font-medium text-blue-400">
                  この部位の候補 ({meshCandidates.length}件) — クリックで切替
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 p-3 pt-1">
                {meshCandidates.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => onSelectAlt(c.id)}
                    className={`w-full rounded-md border p-2 text-left text-xs transition ${
                      c.id === part.id
                        ? "border-amber-400/50 bg-amber-400/10"
                        : "border-border bg-card hover:border-blue-400/40 hover:bg-blue-400/5"
                    }`}
                  >
                    <div className="flex items-center gap-1.5">
                      {c.imageRef && c.imageRef !== "—" && (
                        <span className="rounded bg-muted px-1 font-mono text-[9px] text-muted-foreground">
                          {c.imageRef}
                        </span>
                      )}
                      <span className="font-medium">{c.name}</span>
                    </div>
                    <div className="mt-0.5 flex justify-between font-mono text-[10px] text-muted-foreground">
                      <span>{c.partNumber}</span>
                      <span>{c.price > 0 ? `¥${c.price.toLocaleString()}` : "—"}</span>
                    </div>
                  </button>
                ))}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardContent className="space-y-3 p-4">
              <div>
                <div className="text-xs text-muted-foreground">部品名</div>
                <div className="text-sm font-medium">{part.name}</div>
                {part.nameRomaji && (
                  <div className="font-mono text-[10px] text-muted-foreground">
                    {part.nameRomaji}
                  </div>
                )}
              </div>

              <Separator />

              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <div className="text-muted-foreground">
                    品番{part.provisional && " (仮)"}
                  </div>
                  <div className="mt-0.5 font-mono text-sm">{part.partNumber}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">カタログ符号</div>
                  <div className="mt-0.5 font-mono text-sm">{part.imageRef ?? "—"}</div>
                </div>
              </div>

              {part.remark && (
                <div className="flex items-start gap-1.5 rounded-md bg-amber-400/10 p-2 text-[11px] text-amber-300/90">
                  <Info className="mt-0.5 h-3 w-3 shrink-0" />
                  <span>{part.remark}</span>
                </div>
              )}

              <Separator />

              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <div className="text-muted-foreground">在庫</div>
                  <div className="mt-1">
                    <Badge variant="outline" className={stock.color}>
                      {stock.label}
                    </Badge>
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground">納期</div>
                  <div className="mt-0.5 text-sm">{part.leadTime}</div>
                </div>
              </div>

              <Separator />

              <div>
                <div className="text-xs text-muted-foreground">単価 (税抜)</div>
                <div className="mt-0.5 font-mono text-2xl font-semibold">
                  {part.price > 0 ? `¥${part.price.toLocaleString()}` : "—"}
                </div>
              </div>

              <Separator />

              <div>
                <div className="text-xs text-muted-foreground">説明</div>
                <p className="mt-1 text-xs leading-relaxed">{part.description}</p>
              </div>

              <Separator />

              <div>
                <div className="text-xs text-muted-foreground">対応機種</div>
                <div className="mt-1 flex flex-wrap gap-1">
                  {part.modelCompat.map((m) => (
                    <Badge key={m} variant="secondary" className="text-[10px]">
                      {m}
                    </Badge>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>

          <Button
            className="w-full"
            onClick={() => onAddToCart(part.id)}
            disabled={part.stock === "out_of_stock" || part.price === 0}
          >
            <Plus className="mr-2 h-4 w-4" />
            {part.price === 0 ? "シャシメーカー扱い (発注対象外)" : "見積カートに追加"}
          </Button>
        </div>
      </ScrollArea>
    </div>
  );
}

// ──────────────────────────────────────────────
function QuoteDialog({
  open,
  onOpenChange,
  cart,
  cartTotal,
  vehicle,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  cart: CartItem[];
  cartTotal: number;
  vehicle: (typeof VEHICLE_MODELS)[number];
}) {
  const tax = Math.round(cartTotal * 0.1);
  const total = cartTotal + tax;
  const quoteNo = `Q-${new Date().getFullYear()}${(new Date().getMonth() + 1)
    .toString()
    .padStart(2, "0")}${new Date().getDate().toString().padStart(2, "0")}-${Math.floor(
    Math.random() * 999
  )
    .toString()
    .padStart(3, "0")}`;

  const handlePrint = () => window.print();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center justify-between">
            <span>見積書プレビュー</span>
            <Button size="sm" variant="outline" onClick={handlePrint}>
              <FileText className="mr-2 h-4 w-4" />
              印刷 / PDF保存
            </Button>
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 rounded-md border bg-white p-6 text-black print:border-0">
          <div className="flex justify-between border-b-2 border-black pb-3">
            <div>
              <h2 className="text-2xl font-bold">御 見 積 書</h2>
              <div className="mt-2 text-sm">
                <div>見積番号: {quoteNo}</div>
                <div>発行日: {new Date().toLocaleDateString("ja-JP")}</div>
              </div>
            </div>
            <div className="text-right text-sm">
              <div className="font-semibold">○○ SS工場 御中</div>
              <div className="mt-3 text-xs">
                新明和工業株式会社
                <br />
                環境システム事業部 部品課
                <br />
                TEL: 0XX-XXXX-XXXX
              </div>
            </div>
          </div>

          <div className="rounded bg-gray-100 p-3 text-sm">
            <div className="font-semibold">対象機種</div>
            <div className="mt-1 font-mono">
              {vehicle.modelCode} / {vehicle.series}
            </div>
            <div className="text-xs text-gray-600">
              パーツカタログNo: {vehicle.catalogCode}
            </div>
          </div>

          <table className="w-full text-sm">
            <thead className="border-b border-black">
              <tr>
                <th className="py-2 text-left">符号</th>
                <th className="py-2 text-left">品番</th>
                <th className="py-2 text-left">品名</th>
                <th className="py-2 text-right">数量</th>
                <th className="py-2 text-right">単価</th>
                <th className="py-2 text-right">金額</th>
              </tr>
            </thead>
            <tbody>
              {cart.map((item) => {
                const part = PARTS.find((p) => p.id === item.partId);
                if (!part) return null;
                return (
                  <tr key={item.partId} className="border-b border-gray-200">
                    <td className="py-2 font-mono text-xs">{part.imageRef}</td>
                    <td className="py-2 font-mono text-xs">{part.partNumber}</td>
                    <td className="py-2">{part.name}</td>
                    <td className="py-2 text-right">{item.quantity}</td>
                    <td className="py-2 text-right font-mono">
                      ¥{part.price.toLocaleString()}
                    </td>
                    <td className="py-2 text-right font-mono">
                      ¥{(part.price * item.quantity).toLocaleString()}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <div className="ml-auto w-1/2 space-y-1 text-sm">
            <div className="flex justify-between">
              <span>小計</span>
              <span className="font-mono">¥{cartTotal.toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span>消費税 (10%)</span>
              <span className="font-mono">¥{tax.toLocaleString()}</span>
            </div>
            <div className="flex justify-between border-t-2 border-black pt-1 text-lg font-bold">
              <span>合計</span>
              <span className="font-mono">¥{total.toLocaleString()}</span>
            </div>
          </div>

          <div className="border-t border-gray-300 pt-3 text-xs text-gray-600">
            ※ 部品名・符号は実カタログ(F-3401-E0037)に準拠。品番・価格はデモ用の仮値です。
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            閉じる
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
