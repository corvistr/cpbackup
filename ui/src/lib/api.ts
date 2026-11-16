export type Destination = {
  id: number
  name: string
  kind: "ftp" | "s3" | "s3compat" | "gdrive" | "dropbox" | "onedrive"
  host: string
  port: number
  username: string
  path: string
  passive: boolean
  tls: boolean
  region: string
  prefix: string
  has_refresh: boolean
  created_at: string
  updated_at: string
}

export const CONTENT_BITS = [
  [1, "Panel yapılandırması"],
  [2, "Ana dizin dosyaları"],
  [4, "Veritabanları"],
  [128, "Veritabanı kullanıcıları"],
  [8, "E-posta hesapları"],
  [256, "FTP hesapları"],
  [16, "Cron işleri"],
  [32, "Alan adları"],
  [64, "SSL sertifikaları"],
] as const

export const FULL_CONTAINS = 511

export type Job = {
  id: number
  name: string
  destination_id: number
  all_accounts: boolean
  accounts: string[]
  schedule: "manual" | "daily" | "weekly"
  hour: number
  minute: number
  weekday: number | null
  retention: number
  include_homedir: boolean
  include_db: boolean
  include_dns: boolean
  include_mailconfig: boolean
  skip_logs: boolean
  skip_suspended: boolean
  enabled: boolean
  last_run: string | null
  active: number
  max_account_gb: number
  contains: number
  exclude_databases: string[]
  email_contents: boolean
  exclude_junk: boolean
}

export type BatchSummary = {
  id: number
  job_id: number | null
  destination_id: number | null
  title: string
  kind: "backup" | "restore"
  created_at: string
  finished_at: string | null
  total: number
  uploaded: number
  failed: number
  skipped: number
  cancelled: number
  queued: number
  running: number
  restored: number
  deleted: number
  stop_requested: boolean
}

export type BackupRun = {
  id: number
  job_id: number | null
  destination_id: number | null
  account: string
  kind: "backup" | "restore" | "partial"
  locked: boolean
  status: string
  remote_path: string | null
  size_bytes: number | null
  started_at: string | null
  finished_at: string | null
  error: string | null
  force: boolean
  created_at: string
  log?: string
}

export type Account = {
  user: string
  domain: string
  diskused: string
  suspended: boolean
  plan: string
}

export type PanelStatus = {
  ok: boolean
  version: string
  hostname: string
  accounts: number
  destinations: number
  jobs: number
  queue: number
  running: number
  success_24h: number
  failed_24h: number
  spool_free: number
  spool: string
  disk_total: number
  disk_used: number
  disk_percent: number
  load: number[]
  max_load: number
  notify_email: string
  allow_user_restore: boolean
  summary_mail: boolean
  history_days: number
  account_gap: number
  nice_level: number
  ionice_level: number
  restore_times: number
  restore_hours: number
  owner_fail_mail: boolean
  owner_ok_mail: boolean
  cloud_ready: boolean
  timezone: string
  now: string
  recent_batches: BatchSummary[]
  next_run: { manual: boolean; label: string; at: string | null; job: string | null }
  active_batch: (BatchSummary & { live: boolean; bytes: number }) | null
  last_error: { account: string; error: string; finished_at: string | null } | null
  oversized: string[]
}

export function panelHome() {
  const match = window.location.pathname.match(/\/cpsess[^/]+/)
  if (!match) return "../../"
  return `${match[0]}/`
}

export async function api<T>(action: string, body?: unknown, query = ""): Promise<T> {
  const response = await fetch(`api.cgi?action=${encodeURIComponent(action)}${query}`, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json", "X-CPBackup": "1" },
    body: body ? JSON.stringify(body) : undefined,
  })
  let payload: { ok?: boolean; error?: string } & T
  try {
    payload = (await response.json()) as { ok?: boolean; error?: string } & T
  } catch {
    throw new Error("Sunucu yanıtı okunamadı.")
  }
  if (!payload.ok) throw new Error(payload.error || "İşlem başarısız.")
  return payload
}

export function formatBytes(size: number | null | undefined) {
  if (size == null) return "—"
  let value = size
  const units = ["B", "KB", "MB", "GB", "TB"]
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  const digits = index === 0 || value >= 10 ? 0 : 1
  return `${value.toFixed(digits)} ${units[index]}`
}

export function statusLabel(status: string) {
  const labels: Record<string, string> = {
    queued: "Kuyrukta",
    running: "Çalışıyor",
    packaging: "Paketleniyor",
    packaged: "Yüklenecek",
    uploading: "Yükleniyor",
    uploaded: "Yüklendi",
    failed: "Hata",
    deleted: "Silindi",
    restored: "Geri yüklendi",
    skipped: "Atlandı",
    cancelled: "Durduruldu",
  }
  return labels[status] || status
}

export function scheduleLabel(job: Pick<Job, "schedule" | "hour" | "minute" | "weekday">) {
  const clock = `${String(job.hour).padStart(2, "0")}:${String(job.minute).padStart(2, "0")}`
  if (job.schedule === "daily") return `Her gün ${clock}`
  if (job.schedule === "weekly") {
    const days = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    return `${days[job.weekday ?? 0]} ${clock}`
  }
  return "Yalnızca elle"
}
