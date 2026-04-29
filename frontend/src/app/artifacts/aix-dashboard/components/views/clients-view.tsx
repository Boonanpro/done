"use client";

import { useState } from "react";
import { Search, Building2, MapPin, Phone, User } from "lucide-react";
import { AddClientDialog } from "../add-client-dialog";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAix } from "../../data/store";
import { StageBadge, PriorityBadge } from "../ui-bits";

type Props = {
  onOpen: (id: string) => void;
};

export function ClientsView({ onOpen }: Props) {
  const { clients } = useAix();
  const [q, setQ] = useState("");
  const filtered = clients.filter(
    (c) =>
      !q ||
      c.name.includes(q) ||
      c.industry.includes(q) ||
      c.location.includes(q) ||
      c.tags.some((t) => t.includes(q)),
  );
  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">クライアント</h1>
          <p className="text-sm text-muted-foreground mt-1">
            DXで支援する企業の一覧。ダンが自律的に課題分析・提案を進めます。
          </p>
        </div>
        <AddClientDialog />
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between gap-3">
            <CardTitle className="text-sm font-medium">
              {filtered.length} 社
            </CardTitle>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="業種・地域・タグで検索"
                className="h-8 pl-8 w-64 rounded-sm"
              />
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[36%]">企業</TableHead>
                <TableHead>業種・規模</TableHead>
                <TableHead>担当</TableHead>
                <TableHead>優先度</TableHead>
                <TableHead>ステージ</TableHead>
                <TableHead>タグ</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((c) => (
                <TableRow
                  key={c.id}
                  className="cursor-pointer"
                  onClick={() => onOpen(c.id)}
                >
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <div className="h-8 w-8 rounded-md bg-accent flex items-center justify-center">
                        <Building2 className="h-4 w-4 text-muted-foreground" />
                      </div>
                      <div>
                        <div className="font-medium">{c.name}</div>
                        <div className="text-xs text-muted-foreground flex items-center gap-2 mt-0.5">
                          <MapPin className="h-3 w-3" />
                          {c.location}
                        </div>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="text-xs">
                    <div>{c.industry}</div>
                    <div className="text-muted-foreground">{c.size}</div>
                  </TableCell>
                  <TableCell className="text-xs">
                    {c.contactName !== "—" ? (
                      <div>
                        <div className="flex items-center gap-1.5">
                          <User className="h-3 w-3 text-muted-foreground" />
                          {c.contactName}
                        </div>
                        {c.contactPhone && (
                          <div className="flex items-center gap-1.5 text-muted-foreground mt-0.5 font-mono">
                            <Phone className="h-3 w-3" />
                            {c.contactPhone}
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className="text-muted-foreground">未登録</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <PriorityBadge priority={c.priority} />
                  </TableCell>
                  <TableCell>
                    <StageBadge stage={c.stage} />
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1 flex-wrap">
                      {c.tags.slice(0, 3).map((t) => (
                        <Badge
                          key={t}
                          variant="outline"
                          className="rounded-sm text-[10px] font-normal"
                        >
                          {t}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
