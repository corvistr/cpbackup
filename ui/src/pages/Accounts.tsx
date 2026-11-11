import { useEffect, useMemo, useState } from "react"
import { api, formatBytes, panelHome, type BackupRun } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { StatusBadge } from "@/components/status-badge"
import { cn } from "@/lib/utils"

type DirectoryAccount = {
  user: string
  domain: string
  ip: string
  owner: string
  plan: string
  home: string
  suspended: boolean
  disk_bytes: number
  limit_bytes: number
  backups: number
  last_at: string | null
  last_status: string | null
  oversized: boolean
}

type Filter = "all" | "suspended" | "missing" | "oversized"

const filters: { id: Filter; label: string }[] = [
  { id: "all", label: "Tümü" },
  { id: "suspended", label: "Askıda" },
  { id: "missing", label: "Yedeği yok" },
  { id: "oversized", label: "Kota üstü" },
]

export function Accounts({ onNotify }: { onNotify: (message: string, error?: boolean) => void }) {
  const [rows, setRows] = useState<DirectoryAccount[]>([])
  const [query, setQuery] = useState("")
  const [filter, setFilter] = useState<Filter>("all")
  const [open, setOpen] = useState<string | null>(null)
  const [backups, setBackups] = useState<BackupRun[]>([])
  const [loadingBackups, setLoadingBackups] = useState(false)

  useEffect(() => {
    api<{ data: DirectoryAccount[] }>("accounts.directory")
      .then((result) => setRows(result.data))
      .catch((error: Error) => onNotify(error.message, true))
  }, [onNotify])

  const visible = useMemo(() => {
    const text = query.trim().toLowerCase()
    return rows.filter((row) => {
      if (filter === "suspended" && !row.suspended) return false
      if (filter === "missing" && row.backups > 0) return false
      if (filter === "oversized" && !row.oversized) return false
      if (!text) return true
      return [row.user, row.domain, row.ip, row.owner, row.plan].some((value) => value.toLowerCase().includes(text))
    })
  }, [filter, query, rows])

  async function toggle(user: string) {
    if (open === user) {
      setOpen(null)
      return
    }
    setOpen(user)
    setBackups([])
    setLoadingBackups(true)
    try {
      const result = await api<{ data: BackupRun[] }>("account.backups", undefined, `&user=${encodeURIComponent(user)}`)
      setBackups(result.data)
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Yedekler alınamadı", true)
    } finally {
      setLoadingBackups(false)
    }
  }

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          placeholder="Hesap, alan adı veya IP"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="max-w-xs"
        />
        {filters.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setFilter(item.id)}
            className={cn(
              "rounded-full border px-2.5 py-1 text-[11px]",
              filter === item.id ? "border-transparent bg-slate-900 text-white" : "bg-card text-muted-foreground",
            )}
          >
            {item.label}
          </button>
        ))}
        <p className="text-[11px] text-muted-foreground">{visible.length} / {rows.length} hesap</p>
      </div>
      <div className="overflow-hidden rounded-lg border bg-card">
        <div className="grid grid-cols-[minmax(8rem,1.1fr)_minmax(8rem,1.3fr)_7rem_6rem_6rem] gap-2 border-b px-3 py-2 text-[11px] text-muted-foreground">
          <span>Hesap</span>
          <span>Alan adı</span>
          <span>Disk</span>
          <span>Tam yedek</span>
          <span>Son durum</span>
        </div>
        {visible.length === 0 ? (
          <p className="px-3 py-4 text-xs text-muted-foreground">Bu süzgeçte hesap yok.</p>
        ) : visible.map((row) => {
          const expanded = open === row.user
          return (
            <div key={row.user} className={cn("border-t", row.suspended && "bg-red-50")}>
              <button
                type="button"
                onClick={() => toggle(row.user)}
                className="grid w-full grid-cols-[minmax(8rem,1.1fr)_minmax(8rem,1.3fr)_7rem_6rem_6rem] items-center gap-2 px-3 py-2 text-left text-xs"
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium">{row.user}</span>
                  <span className="block truncate text-[11px] text-muted-foreground">{row.ip}</span>
                </span>
                <span className="min-w-0 truncate">{row.domain}</span>
                <span className="truncate">
                  {formatBytes(row.disk_bytes)}
                  <span className="text-muted-foreground"> / {row.limit_bytes ? formatBytes(row.limit_bytes) : "sınırsız"}</span>
                </span>
                <span>{row.backups}</span>
                <span className="truncate text-[11px] text-muted-foreground">
                  {row.suspended ? "Askıda" : row.oversized ? "Kota üstü" : row.last_status ? "" : "Yedek yok"}
                  {!row.suspended && row.last_status ? <StatusBadge status={row.last_status} /> : null}
                </span>
              </button>
              {expanded ? (
                <div className="grid gap-3 border-t bg-white px-3 py-3">
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" className="border-transparent bg-[#ff6c2c] text-white hover:bg-[#e4561c] hover:text-white" asChild>
                      <a href={`${panelHome()}scripts/edituser?user=${encodeURIComponent(row.user)}&domain=${encodeURIComponent(row.domain)}`}>WHM'de aç</a>
                    </Button>
                  </div>
                  <div className="grid gap-1 text-[11px] text-muted-foreground sm:grid-cols-2">
                    <p>Ev dizini: <span className="text-foreground">{row.home}</span></p>
                    <p>Sahip: <span className="text-foreground">{row.owner || "—"}</span> · Plan: <span className="text-foreground">{row.plan || "—"}</span></p>
                    <p>Son yüklenen yedek: <span className="text-foreground">{row.last_at || "yok"}</span></p>
                    <p>{row.suspended ? "Askıdaki hesap yedek kuyruğuna girmez." : row.oversized ? "Boyut sınırı aşıldığı için bu tura alınmadı." : "Satıra basınca son yedekler açılır."}</p>
                  </div>
                  {loadingBackups ? <p className="text-xs text-muted-foreground">Yedekler yükleniyor…</p> : backups.length === 0 ? (
                    <p className="text-xs text-muted-foreground">Bu hesabın yedek kaydı yok.</p>
                  ) : (
                    <div className="grid gap-1">
                      {backups.map((item) => (
                        <div key={item.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-2 py-1.5 text-xs">
                          <span className="text-muted-foreground">{item.finished_at || item.created_at}</span>
                          <StatusBadge status={item.status} />
                          <span>{formatBytes(item.size_bytes)}</span>
                          {item.error ? <span className="w-full truncate text-[11px] text-red-700">{item.error}</span> : null}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}
