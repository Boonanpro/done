"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Image from "next/image";
import { api, Issue } from "@/lib/api";
import { formatDate, formatRelativeTime } from "@/lib/utils";
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
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";

// Status configurations
const statusVariant: Record<string, "default" | "secondary" | "success" | "warning" | "destructive"> = {
  open: "destructive",
  investigating: "warning",
  resolved: "success",
  ignored: "secondary",
};

const statusLabel: Record<string, string> = {
  open: "Open",
  investigating: "Investigating",
  resolved: "Resolved",
  ignored: "Ignored",
};

const issueTypeLabel: Record<string, string> = {
  executor_missing: "Executor Missing",
  selector_outdated: "Selector Outdated",
  execution_failed: "Execution Failed",
  search_failed: "Search Failed",
  user_input_required: "User Input Required",
};

export default function IssueDetailPage() {
  const params = useParams();
  const router = useRouter();
  const issueId = params.id as string;

  const [issue, setIssue] = useState<Issue | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updating, setUpdating] = useState(false);

  // Image viewer state
  const [selectedImage, setSelectedImage] = useState<string | null>(null);

  // HTML viewer state
  const [htmlContent, setHtmlContent] = useState<string | null>(null);
  const [showHtmlViewer, setShowHtmlViewer] = useState(false);

  const fetchIssue = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api.getIssue(issueId);
      setIssue(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch issue");
    } finally {
      setLoading(false);
    }
  }, [issueId]);

  useEffect(() => {
    fetchIssue();
  }, [fetchIssue]);

  const handleStatusChange = async (newStatus: string) => {
    if (!issue) return;
    try {
      setUpdating(true);
      const result = await api.updateIssue(issueId, { status: newStatus });
      setIssue(result.issue);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update status");
    } finally {
      setUpdating(false);
    }
  };

  const handleViewHtml = async () => {
    if (!issue?.html_snapshot_path) return;

    try {
      // パス全体を渡す（例: a11b4568/issues/snapshot_xxx.html）
      const url = api.getHtmlUrl(issueId, issue.html_snapshot_path);
      const response = await fetch(url);
      if (!response.ok) throw new Error("Failed to load HTML");
      const html = await response.text();
      setHtmlContent(html);
      setShowHtmlViewer(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load HTML");
    }
  };

  if (loading) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (error || !issue) {
    return (
      <div className="container mx-auto py-6">
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <p className="text-destructive">{error || "Issue not found"}</p>
            <Button
              variant="outline"
              onClick={() => router.push("/")}
              className="mt-4"
            >
              Back to list
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="outline" onClick={() => router.push("/")}>
            Back
          </Button>
          <h1 className="text-xl font-bold">Issue Detail</h1>
        </div>
        <div className="flex items-center gap-4">
          <Select
            value={issue.status}
            onValueChange={handleStatusChange}
            disabled={updating}
          >
            <SelectTrigger className="w-[180px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="open">Open</SelectItem>
              <SelectItem value="investigating">Investigating</SelectItem>
              <SelectItem value="resolved">Resolved</SelectItem>
              <SelectItem value="ignored">Ignored</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Main Info */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Overview</CardTitle>
            <div className="flex items-center gap-2">
              <Badge variant={statusVariant[issue.status] || "default"}>
                {statusLabel[issue.status] || issue.status}
              </Badge>
              <Badge variant="outline">
                {issueTypeLabel[issue.issue_type] || issue.issue_type}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <h3 className="text-sm font-medium text-muted-foreground mb-1">
              Original Wish
            </h3>
            <p className="text-sm">{issue.original_wish}</p>
          </div>

          {issue.error_message && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-1">
                Error Message
              </h3>
              <pre className="text-sm bg-muted p-3 rounded-md overflow-x-auto">
                {issue.error_message}
              </pre>
            </div>
          )}

          {issue.page_url && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-1">
                Page URL
              </h3>
              <a
                href={issue.page_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-blue-400 hover:underline break-all"
              >
                {issue.page_url}
              </a>
            </div>
          )}

          {issue.fallback_action && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-1">
                Fallback Action
              </h3>
              <p className="text-sm">{issue.fallback_action}</p>
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 border-t border-border">
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-1">
                Service
              </h3>
              <p className="text-sm">{issue.service_name || "-"}</p>
            </div>
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-1">
                Priority
              </h3>
              <p className="text-sm">{issue.priority}</p>
            </div>
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-1">
                Created
              </h3>
              <p className="text-sm">{formatDate(issue.created_at)}</p>
            </div>
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-1">
                Last Occurred
              </h3>
              <p className="text-sm">
                {issue.last_occurred_at
                  ? formatRelativeTime(issue.last_occurred_at)
                  : "-"}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Screenshots */}
      {issue.screenshots && issue.screenshots.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Screenshots ({issue.screenshots.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              {issue.screenshots.map((screenshot, index) => {
                // パス全体を渡す（例: a11b4568/issues/issue_xxx.png）
                const imageUrl = api.getScreenshotUrl(issueId, screenshot);
                return (
                  <div
                    key={index}
                    className="relative aspect-video bg-muted rounded-md overflow-hidden cursor-pointer hover:ring-2 hover:ring-ring transition-all"
                    onClick={() => setSelectedImage(imageUrl)}
                  >
                    <Image
                      src={imageUrl}
                      alt={`Screenshot ${index + 1}`}
                      fill
                      className="object-cover"
                      unoptimized
                    />
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* HTML Snapshot */}
      {issue.html_snapshot_path && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>HTML Snapshot</CardTitle>
              <Button variant="outline" size="sm" onClick={handleViewHtml}>
                View HTML
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground break-all">
              {issue.html_snapshot_path}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Occurrences */}
      {issue.occurrences && issue.occurrences.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Occurrences ({issue.occurrences.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {issue.occurrences.map((occurrence) => (
                <div
                  key={occurrence.id}
                  className="p-3 bg-muted rounded-md space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">
                      {formatDate(occurrence.occurred_at)}
                    </span>
                    <span className="text-sm text-muted-foreground">
                      {formatRelativeTime(occurrence.occurred_at)}
                    </span>
                  </div>
                  {occurrence.error_message && (
                    <p className="text-sm text-muted-foreground">
                      {occurrence.error_message}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Image Viewer Dialog */}
      <Dialog open={!!selectedImage} onOpenChange={() => setSelectedImage(null)}>
        <DialogContent className="max-w-4xl max-h-[90vh]">
          <DialogHeader>
            <DialogTitle>Screenshot</DialogTitle>
          </DialogHeader>
          {selectedImage && (
            <div className="relative w-full h-[70vh]">
              <Image
                src={selectedImage}
                alt="Screenshot"
                fill
                className="object-contain"
                unoptimized
              />
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* HTML Viewer Dialog */}
      <Dialog open={showHtmlViewer} onOpenChange={setShowHtmlViewer}>
        <DialogContent className="max-w-5xl max-h-[90vh]">
          <DialogHeader>
            <DialogTitle>HTML Snapshot</DialogTitle>
          </DialogHeader>
          <ScrollArea className="h-[70vh]">
            <pre className="text-xs bg-muted p-4 rounded-md overflow-x-auto whitespace-pre-wrap">
              {htmlContent}
            </pre>
          </ScrollArea>
        </DialogContent>
      </Dialog>
    </div>
  );
}
