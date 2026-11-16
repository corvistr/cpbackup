import { useEffect, useState } from "react"
import { Activity, AlertTriangle, CalendarClock, CheckCircle2, DatabaseBackup, HardDrive, ListOrdered, LoaderCircle, Users } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { api, formatBytes, type BatchSummary, type PanelStatus } from "@/lib/api"

export function Dashboard({ onError }: { onError: (message: string) => void }) {
  const [status, setStatus] = useState<PanelStatus | null>(null)

  useEffect(() => {
    let active = true
    const load = () => {
      api<PanelStatus>("status")
        .then((data) => {
          if (active) setStatus(data)
        })
        .catch((error: Error) => onError(error.message))
    }
    load()
    const timer = window.setInterval(load, 8000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [onError])

  if (!status) {
    return <p className="text-sm text-muted-foreground">Özet yükleniyor…</p>
  }

  const diskTone = status.disk_percent >= 90
    ? "bg-red-50 text-red-600"
    : status.disk_percent >= 75
      ? "bg-amber-50 text-amber-700"
      : "bg-slate-100 text-slate-700"
  const cards: { label: string; value: string; hint?: string; icon: typeof Users; tone: string }[] = [
    { label: "Hesap", value: String(status.accounts), icon: Users, tone: "bg-sky-50 text-sky-700" },
    { label: "FTP hedefi", value: String(status.destinations), icon: DatabaseBackup, tone: "bg-orange-50 text-[#e4561c]" },
    { label: "Etkin görev", value: String(status.jobs), icon: CalendarClock, tone: "bg-violet-50 text-violet-700" },
    { label: "Kuyruk", value: String(status.queue), icon: ListOrdered, tone: "bg-amber-50 text-amber-700" },
    { label: "Çalışan", value: String(status.running), icon: LoaderCircle, tone: "bg-teal-50 text-teal-700" },
    { label: "24 saatte tamam", value: String(status.success_24h), icon: CheckCircle2, tone: "bg-emerald-50 text-emerald-700" },
    { label: "24 saatte hata", value: String(status.failed_24h), icon: AlertTriangle, tone: "bg-red-50 text-red-600" },
    {
      label: "Toplam disk",
      value: `${status.disk_percent}%`,
      hint: `${formatBytes(status.disk_used)} / ${formatBytes(status.disk_total)}`,
      icon: HardDrive,
      tone: diskTone,
    },
  ]

  return (
    <div className="grid gap-3">
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => {
          const Icon = card.icon
          return (
            <div key={card.label} className="flex items-center gap-3 rounded-lg border bg-card px-3 py-2.5">
              <div className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg", card.tone)}>
                <Icon className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <p className="text-lg font-semibold leading-none tracking-tight">{card.value}</p>
                <p className="mt-1 truncate text-[11px] text-muted-foreground">{card.label}</p>
                {card.hint ? <p className="truncate text-[11px] text-muted-foreground">{card.hint}</p> : null}
              </div>
            </div>
          )
        })}
      </div>
      <Overview status={status} />
      <div className="grid gap-2 lg:grid-cols-2">
        <div className="rounded-lg border bg-card px-3 py-2.5">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-medium">Sunucu</p>
            <p className="truncate text-[11px] text-muted-foreground">{status.hostname} · {status.now}</p>
          </div>
          <p className="mt-2 text-sm font-semibold leading-none">{formatBytes(status.spool_free)} <span className="text-[11px] font-normal text-muted-foreground">boş geçici alan</span></p>
          <p className="mt-1 text-[11px] text-muted-foreground">Paket FTP’ye gidince sunucudaki kopya silinir. Yük sınırı yukarıdaki kartta.</p>
        </div>
        <div className="rounded-lg border bg-card px-3 py-2.5">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-medium">Atlanan büyük hesaplar</p>
            <p className="text-[11px] text-muted-foreground">{status.oversized.length} hesap</p>
          </div>
          {status.oversized.length === 0 ? (
            <p className="mt-2 text-[11px] text-muted-foreground">Kota üstü hesap yok. Sınırı aşanlar yedeklenmez.</p>
          ) : (
            <>
              <p className="mt-1 text-[11px] text-muted-foreground">Boyut sınırının üstünde, bu tura alınmadı.</p>
              <p className="mt-1.5 text-xs leading-5">{status.oversized.slice(0, 8).join(", ")}{status.oversized.length > 8 ? ` +${status.oversized.length - 8}` : ""}</p>
            </>
          )}
        </div>
      </div>
      <div className="rounded-lg border bg-card">
        <div className="flex items-center justify-between px-3 py-2">
          <p className="text-xs font-medium">Son çalıştırmalar</p>
          <p className="text-[11px] text-muted-foreground">Hesap dökümü Geçmiş’te</p>
        </div>
        {status.recent_batches.length === 0 ? (
          <p className="px-3 pb-3 text-[11px] text-muted-foreground">Henüz yedek yok. Bir FTP hedefi ve görev ekleyin.</p>
        ) : status.recent_batches.map((batch) => (
          <div key={batch.id} className="flex flex-wrap items-center justify-between gap-2 border-t px-3 py-2">
            <div className="min-w-0">
              <p className="truncate text-xs font-medium">{batch.title}</p>
              <p className="text-[11px] text-muted-foreground">{batch.finished_at || batch.created_at}</p>
            </div>
            <BatchCounts batch={batch} />
          </div>
        ))}
      </div>
    </div>
  )
}

function Overview({ status }: { status: PanelStatus }) {
  const batch = status.active_batch
  const total = batch?.total || 0
  const segments = batch
    ? [
        { label: "yüklendi", count: batch.uploaded, color: "bg-emerald-500" },
        { label: "hata", count: batch.failed, color: "bg-red-500" },
        { label: "atlandı", count: batch.skipped, color: "bg-slate-400" },
        { label: "durduruldu", count: batch.cancelled, color: "bg-orange-400" },
        { label: "çalışan", count: batch.running, color: "bg-teal-500" },
        { label: "sırada", count: batch.queued, color: "bg-amber-300" },
        { label: "geri yüklendi", count: batch.restored, color: "bg-sky-500" },
        { label: "silindi", count: batch.deleted, color: "bg-zinc-500" },
      ].filter((part) => part.count > 0)
    : []
  const loadValue = status.load[0] ?? 0
  const loadHot = status.max_load > 0 && loadValue >= status.max_load * 0.8
  const loadFull = status.max_load > 0 && loadValue >= status.max_load
  return (
    <div className="grid gap-2">
      <div className="rounded-lg border bg-card px-3 py-2.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-xs font-medium">{batch ? batch.title : "Çalıştırma yok"}</p>
            <p className="text-[11px] text-muted-foreground">
              {batch ? (batch.live ? "Bu tur sürüyor" : "Son tur bitti") : "Henüz yedek alınmadı"}
              {batch ? ` · ${formatBytes(batch.bytes)} FTP’ye gitti` : ""}
            </p>
          </div>
          {batch ? <BatchCounts batch={batch} /> : null}
        </div>
        <div className="mt-2 flex h-1.5 overflow-hidden rounded-full bg-muted">
          {total > 0 ? segments.map((part) => (
            <div
              key={part.label}
              className={part.color}
              style={{ width: `${(part.count / total) * 100}%` }}
              title={`${part.count} ${part.label}`}
            />
          )) : null}
        </div>
        {segments.length > 0 ? (
          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
            {segments.map((part) => (
              <span key={part.label} className="inline-flex items-center gap-1">
                <span className={cn("h-2 w-2 rounded-full", part.color)} />
                {part.count} {part.label}
              </span>
            ))}
          </div>
        ) : null}
      </div>
      <div className="grid gap-2 lg:grid-cols-3">
        <div className="flex items-center gap-2.5 rounded-lg border bg-card px-3 py-2.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-violet-50 text-violet-700">
            <CalendarClock className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold leading-none">{status.next_run.label}</p>
            <p className="mt-1 truncate text-[11px] text-muted-foreground">Sonraki çalışma{status.next_run.job ? ` · ${status.next_run.job}` : ""}</p>
          </div>
        </div>
        <div className={cn("flex items-center gap-2.5 rounded-lg border bg-card px-3 py-2.5", loadFull && "border-red-200", loadHot && !loadFull && "border-amber-200")}>
          <div className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
            loadFull ? "bg-red-50 text-red-600" : loadHot ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700",
          )}>
            <Activity className="h-4 w-4" />
          </div>
          <div>
            <p className="text-sm font-semibold leading-none">{loadValue.toFixed(2)} <span className="font-normal text-muted-foreground">/ {status.max_load}</span></p>
            <p className="mt-1 text-[11px] text-muted-foreground">{loadFull ? "Yük sınırı aşıldı, paket bekler" : loadHot ? "Yük sınıra yakın" : "Yük rahat, yedek sürer"}</p>
          </div>
        </div>
        <div className="flex items-center gap-2.5 rounded-lg border bg-card px-3 py-2.5">
          <div className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
            status.last_error ? "bg-red-50 text-red-600" : "bg-emerald-50 text-emerald-700",
          )}>
            <AlertTriangle className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold leading-none">{status.last_error ? status.last_error.account : "Hata yok"}</p>
            <p className="mt-1 truncate text-[11px] text-muted-foreground">{status.last_error ? status.last_error.error : "Son çalıştırmada sorun görünmüyor"}</p>
          </div>
        </div>
      </div>
    </div>
  )
}

export function BatchCounts({ batch }: { batch: BatchSummary }) {
  const success = batch.uploaded + batch.restored
  const waiting = batch.queued + batch.running
  return (
    <div className="flex flex-wrap gap-1">
      <Badge variant="success">{success} başarılı</Badge>
      {batch.failed ? <Badge variant="destructive">{batch.failed} hata</Badge> : null}
      {waiting ? <Badge variant="secondary">{waiting} sırada</Badge> : null}
      {batch.cancelled ? <Badge variant="outline">{batch.cancelled} durduruldu</Badge> : null}
      {batch.skipped ? <Badge variant="outline">{batch.skipped} atlandı</Badge> : null}
    </div>
  )
}
