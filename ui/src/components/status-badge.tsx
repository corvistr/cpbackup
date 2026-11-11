import { Badge } from "@/components/ui/badge"
import { statusLabel } from "@/lib/api"

export function StatusBadge({ status }: { status: string }) {
  const variant =
    status === "failed"
      ? "destructive"
      : status === "uploaded" || status === "restored"
        ? "success"
        : status === "running"
          ? "default"
          : status === "deleted" || status === "skipped"
            ? "outline"
            : "secondary"
  return <Badge variant={variant}>{statusLabel(status)}</Badge>
}
