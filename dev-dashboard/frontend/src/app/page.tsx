"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api, Issue, IssueFilters, FilterOptions, Stats } from "@/lib/api";
import { formatRelativeTime, truncate } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";

// Status badge variant mapping
const statusVariant: Record<string, "default" | "secondary" | "success" | "warning" | "destructive"> = {
  open: "destructive",
  investigating: "warning",
  resolved: "success",
  ignored: "secondary",
};

// Status label mapping
const statusLabel: Record<string, string> = {
  open: "Open",
  investigating: "Investigating",
  resolved: "Resolved",
  ignored: "Ignored",
};

// Issue type label mapping
const issueTypeLabel: Record<string, string> = {
  executor_missing: "Executor Missing",
  selector_outdated: "Selector Outdated",
  execution_failed: "Execution Failed",
  search_failed: "Search Failed",
  user_input_required: "User Input Required",
};

export default function HomePage() {
  const router = useRouter();
  const [issues, setIssues] = useState<Issue[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [filterOptions, setFilterOptions] = useState<FilterOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [filters, setFilters] = useState<IssueFilters>({
    limit: 20,
    offset: 0,
    sort_by: "created_at",
    sort_order: "desc",
  });

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [issuesRes, statsRes, optionsRes] = await Promise.all([
        api.getIssues(filters),
        api.getStats(),
        api.getFilterOptions(),
      ]);
      setIssues(issuesRes.issues);
      setStats(statsRes);
      setFilterOptions(optionsRes);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch data");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleFilterChange = (key: keyof IssueFilters, value: string | null) => {
    setFilters((prev) => ({
      ...prev,
      [key]: value === "all" ? null : value,
      offset: 0, // Reset pagination on filter change
    }));
  };

  const handleRowClick = (issueId: string) => {
    router.push(`/issues/${issueId}`);
  };

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Dev Dashboard</h1>
        <Button variant="outline" onClick={fetchData} disabled={loading}>
          Refresh
        </Button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Total Issues
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="text-2xl font-bold">{stats?.total || 0}</div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Open
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="text-2xl font-bold text-red-500">
                {stats?.by_status?.open || 0}
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Investigating
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="text-2xl font-bold text-amber-500">
                {stats?.by_status?.investigating || 0}
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Resolved
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="text-2xl font-bold text-green-500">
                {stats?.by_status?.resolved || 0}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-wrap gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm text-muted-foreground">Status</label>
              <Select
                value={filters.status || "all"}
                onValueChange={(value) => handleFilterChange("status", value)}
              >
                <SelectTrigger className="w-[180px]">
                  <SelectValue placeholder="All statuses" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  {filterOptions?.statuses.map((status) => (
                    <SelectItem key={status} value={status}>
                      {statusLabel[status] || status}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-sm text-muted-foreground">Site</label>
              <Select
                value={filters.site || "all"}
                onValueChange={(value) => handleFilterChange("site", value)}
              >
                <SelectTrigger className="w-[180px]">
                  <SelectValue placeholder="All sites" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All sites</SelectItem>
                  {filterOptions?.sites.map((site) => (
                    <SelectItem key={site} value={site}>
                      {site}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-sm text-muted-foreground">Type</label>
              <Select
                value={filters.issue_type || "all"}
                onValueChange={(value) => handleFilterChange("issue_type", value)}
              >
                <SelectTrigger className="w-[180px]">
                  <SelectValue placeholder="All types" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All types</SelectItem>
                  {filterOptions?.types.map((type) => (
                    <SelectItem key={type} value={type}>
                      {issueTypeLabel[type] || type}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Error State */}
      {error && (
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <p className="text-destructive">{error}</p>
          </CardContent>
        </Card>
      )}

      {/* Issue List */}
      <Card>
        <CardContent className="pt-6">
          {loading ? (
            <div className="space-y-4">
              {[...Array(5)].map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : issues.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No issues found
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Status</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead className="w-[40%]">Description</TableHead>
                  <TableHead>Site</TableHead>
                  <TableHead>Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {issues.map((issue) => (
                  <TableRow
                    key={issue.id}
                    className="cursor-pointer"
                    onClick={() => handleRowClick(issue.id)}
                  >
                    <TableCell>
                      <Badge variant={statusVariant[issue.status] || "default"}>
                        {statusLabel[issue.status] || issue.status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <span className="text-sm text-muted-foreground">
                        {issueTypeLabel[issue.issue_type] || issue.issue_type}
                      </span>
                    </TableCell>
                    <TableCell>
                      <div className="space-y-1">
                        <div className="font-medium">
                          {truncate(issue.original_wish, 60)}
                        </div>
                        {issue.error_message && (
                          <div className="text-sm text-muted-foreground">
                            {truncate(issue.error_message, 80)}
                          </div>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className="text-sm">
                        {issue.service_name || "-"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className="text-sm text-muted-foreground">
                        {formatRelativeTime(issue.created_at)}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
