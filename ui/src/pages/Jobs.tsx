import { useCallback, useEffect, useMemo, useState } from "react"
import { Loader2, Play, Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Field } from "@/components/field"
import { api, CONTENT_BITS, FULL_CONTAINS, scheduleLabel, type Account, type Destination, type Job } from "@/lib/api"

type Draft = {
  id?: number
  name: string
  destination_id: string
  all_accounts: boolean
  accounts: string[]
  schedule: "manual" | "daily" | "weekly"
  hour: number
  minute: number
  weekday: number
  retention: number
  include_homedir: boolean
  include_db: boolean
  include_dns: boolean
  include_mailconfig: boolean
  skip_logs: boolean
  skip_suspended: boolean
  enabled: boolean
  max_account_gb: number
  contains: number
  email_contents: boolean
  exclude_junk: boolean
  exclude_databases: string
}

const emptyDraft = (): Draft => ({
  name: "",
  destination_id: "",
  all_accounts: true,
  accounts: [],
  schedule: "daily",
  hour: 2,
  minute: 30,
  weekday: 0,
  retention: 7,
  include_homedir: true,
  include_db: true,
  include_dns: true,
  include_mailconfig: true,
  skip_logs: true,
  skip_suspended: true,
  max_account_gb: 0,
  enabled: true,
  contains: FULL_CONTAINS,
  email_contents: true,
  exclude_junk: false,
  exclude_databases: "",
})

const days = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]

export function Jobs({ onNotify }: { onNotify: (message: string, error?: boolean) => void }) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [destinations, setDestinations] = useState<Destination[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<Draft>(emptyDraft())
  const [query, setQuery] = useState("")
  const [busy, setBusy] = useState(false)
  const [pressed, setPressed] = useState<number | null>(null)
  const [removeId, setRemoveId] = useState<number | null>(null)

  const load = useCallback(() => {
    Promise.all([
      api<{ data: Job[] }>("jobs"),
      api<{ data: Destination[] }>("destinations"),
    ])
      .then(([jobResult, destResult]) => {
        setJobs(jobResult.data)
        setDestinations(destResult.data)
      })
      .catch((error: Error) => onNotify(error.message, true))
  }, [onNotify])

  useEffect(() => {
    load()
    const timer = window.setInterval(load, 5000)
    return () => window.clearInterval(timer)
  }, [load])

  const filteredAccounts = useMemo(() => {
    const text = query.trim().toLowerCase()
    if (!text) return accounts
    return accounts.filter((account) => account.user.includes(text) || account.domain.toLowerCase().includes(text))
  }, [accounts, query])

  async function openForm(job?: Job) {
    if (accounts.length === 0) {
      try {
        const result = await api<{ data: Account[] }>("accounts")
        setAccounts(result.data)
      } catch (error) {
        onNotify(error instanceof Error ? error.message : "Hesaplar alınamadı", true)
      }
    }
    setDraft(
      job
        ? {
            id: job.id,
            name: job.name,
            destination_id: String(job.destination_id),
            all_accounts: job.all_accounts,
            accounts: job.accounts,
            schedule: job.schedule,
            hour: job.hour,
            minute: job.minute,
            weekday: job.weekday ?? 0,
            retention: job.retention,
            include_homedir: job.include_homedir,
            include_db: job.include_db,
            include_dns: job.include_dns,
            include_mailconfig: job.include_mailconfig,
            skip_logs: job.skip_logs,
            skip_suspended: job.skip_suspended,
            enabled: job.enabled,
            max_account_gb: job.max_account_gb || 0,
            contains: job.contains ?? FULL_CONTAINS,
            email_contents: job.email_contents !== false,
            exclude_junk: Boolean(job.exclude_junk),
            exclude_databases: (job.exclude_databases || []).join(", "),
          }
        : emptyDraft(),
    )
    setOpen(true)
  }

  function toggleAccount(user: string) {
    setDraft((current) => ({
      ...current,
      accounts: current.accounts.includes(user)
        ? current.accounts.filter((item) => item !== user)
        : [...current.accounts, user],
    }))
  }

  async function save() {
    setBusy(true)
    try {
      await api("job.save", {
        ...draft,
        destination_id: Number(draft.destination_id),
        weekday: draft.schedule === "weekly" ? draft.weekday : null,
        exclude_databases: draft.exclude_databases.split(",").map((item) => item.trim()).filter(Boolean),
      })
      setOpen(false)
      onNotify("Görev kaydedildi. Yedek kendiliğinden başlamaz; zamanı gelince veya elle çalışınca kuyruğa girer.")
      load()
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Kayıt başarısız", true)
    } finally {
      setBusy(false)
    }
  }

  async function run(id: number) {
    setPressed(id)
    setBusy(true)
    try {
      const result = await api<{ queued: number }>("job.run", { id })
      const jobResult = await api<{ data: Job[] }>("jobs")
      setJobs(jobResult.data)
      if (result.queued === 0) onNotify("Kuyruğa alınacak hesap yok.")
      else onNotify(`${result.queued} hesap kuyruğa alındı. Aynı anda tek hesap işlenir.`)
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Kuyruğa alınamadı", true)
    } finally {
      setPressed(null)
      setBusy(false)
    }
  }

  async function remove() {
    if (!removeId) return
    setBusy(true)
    try {
      await api("job.delete", { id: removeId })
      setRemoveId(null)
      onNotify("Görev silindi.")
      load()
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Silinemedi", true)
    } finally {
      setBusy(false)
    }
  }

  const destName = (id: number) => destinations.find((item) => item.id === id)?.name || `#${id}`

  return (
    <div className="grid gap-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">Zamanlanmış görev, saati geldikten sonra her hesap için bir kuyruk kaydı açar.</p>
        <Button onClick={() => openForm()} disabled={destinations.length === 0}>
          <Plus className="h-4 w-4" /> Görev ekle
        </Button>
      </div>
      {destinations.length === 0 ? <p className="text-sm text-muted-foreground">Önce bir FTP hedefi ekleyin.</p> : null}
      <Card>
        <CardContent className="px-0 py-0">
          {jobs.length === 0 ? (
            <p className="p-6 text-sm text-muted-foreground">Henüz görev yok.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Görev</TableHead>
                  <TableHead>Hedef</TableHead>
                  <TableHead>Zaman</TableHead>
                  <TableHead>Saklama</TableHead>
                  <TableHead>Durum</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {jobs.map((job) => {
                  const running = pressed === job.id || (job.active ?? 0) > 0
                  return (
                  <TableRow key={job.id}>
                    <TableCell>
                      <div className="font-medium">{job.name}</div>
                      <div className="text-xs text-muted-foreground">{job.all_accounts ? "Tüm hesaplar" : `${job.accounts.length} hesap`}</div>
                    </TableCell>
                    <TableCell>{destName(job.destination_id)}</TableCell>
                    <TableCell>{scheduleLabel(job)}</TableCell>
                    <TableCell>{job.retention}</TableCell>
                    <TableCell>{job.enabled ? <Badge>Etkin</Badge> : <Badge variant="outline">Kapalı</Badge>}</TableCell>
                    <TableCell className="space-x-1 text-right">
                      <Button variant="outline" size="sm" disabled={busy || !job.enabled || running} onClick={() => run(job.id)}>
                        {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                        {running ? "Çalıştırılıyor" : "Çalıştır"}
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => openForm(job)}>Düzenle</Button>
                      <Button variant="ghost" size="icon" onClick={() => setRemoveId(job.id)}><Trash2 className="h-4 w-4" /></Button>
                    </TableCell>
                  </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="w-[min(640px,calc(100%-2rem))]">
          <DialogHeader>
            <DialogTitle>{draft.id ? "Görevi düzenle" : "Yedek görevi"}</DialogTitle>
            <DialogDescription>Paket cPanel pkgacct ile alınır, FTP’ye yüklenir ve yerel kopya silinir.</DialogDescription>
          </DialogHeader>
          <Tabs defaultValue="genel">
            <TabsList>
              <TabsTrigger value="genel">Genel</TabsTrigger>
              <TabsTrigger value="kapsam">Kapsam</TabsTrigger>
            </TabsList>
            <TabsContent value="genel" className="grid gap-3">
              <Field label="Ad"><Input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></Field>
              <Field label="FTP hedefi">
                <Select value={draft.destination_id} onValueChange={(destination_id) => setDraft({ ...draft, destination_id })}>
                  <SelectTrigger><SelectValue placeholder="Hedef seçin" /></SelectTrigger>
                  <SelectContent>
                    {destinations.map((dest) => (
                      <SelectItem key={dest.id} value={String(dest.id)}>{dest.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Zamanlama">
                <Select value={draft.schedule} onValueChange={(schedule) => setDraft({ ...draft, schedule: schedule as Draft["schedule"] })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="manual">Yalnızca elle</SelectItem>
                    <SelectItem value="daily">Her gün</SelectItem>
                    <SelectItem value="weekly">Haftalık</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              {draft.schedule !== "manual" ? (
                <div className="grid grid-cols-3 gap-3">
                  <Field label="Saat"><Input type="number" min={0} max={23} value={draft.hour} onChange={(event) => setDraft({ ...draft, hour: Number(event.target.value) })} /></Field>
                  <Field label="Dakika"><Input type="number" min={0} max={59} value={draft.minute} onChange={(event) => setDraft({ ...draft, minute: Number(event.target.value) })} /></Field>
                  <Field label="Saklama"><Input type="number" min={1} max={365} value={draft.retention} onChange={(event) => setDraft({ ...draft, retention: Number(event.target.value) })} /></Field>
                </div>
              ) : (
                <Field label="Saklama adedi"><Input type="number" min={1} max={365} value={draft.retention} onChange={(event) => setDraft({ ...draft, retention: Number(event.target.value) })} /></Field>
              )}
              {draft.schedule === "weekly" ? (
                <Field label="Gün">
                  <Select value={String(draft.weekday)} onValueChange={(weekday) => setDraft({ ...draft, weekday: Number(weekday) })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {days.map((day, index) => <SelectItem key={day} value={String(index)}>{day}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </Field>
              ) : null}
              <Field label="En fazla hesap boyutu (GB)" hint="0 sınır koymaz. Bundan büyük hesaplar paketlenmez.">
                <Input type="number" min={0} max={10000} step={1} value={draft.max_account_gb} onChange={(event) => setDraft({ ...draft, max_account_gb: Number(event.target.value) })} />
              </Field>
              <div className="flex items-center justify-between rounded-md border px-3 py-2">
                <span className="text-sm">Görev etkin</span>
                <Switch checked={draft.enabled} onCheckedChange={(enabled) => setDraft({ ...draft, enabled })} />
              </div>
            </TabsContent>
            <TabsContent value="kapsam" className="grid gap-3">
              <div className="flex items-center justify-between rounded-md border px-3 py-2">
                <span className="text-sm">Tüm hesaplar</span>
                <Switch checked={draft.all_accounts} onCheckedChange={(all_accounts) => setDraft({ ...draft, all_accounts })} />
              </div>
              {!draft.all_accounts ? (
                <div className="grid gap-2">
                  <Input placeholder="Hesap veya alan adı ara" value={query} onChange={(event) => setQuery(event.target.value)} />
                  <div className="max-h-48 overflow-auto rounded-md border">
                    {filteredAccounts.map((account) => (
                      <label key={account.user} className="flex items-center gap-2 border-b px-3 py-2 text-sm last:border-0">
                        <input type="checkbox" checked={draft.accounts.includes(account.user)} onChange={() => toggleAccount(account.user)} />
                        <span className="font-medium">{account.domain}</span>
                        <span className="text-muted-foreground">{account.user}</span>
                      </label>
                    ))}
                  </div>
                </div>
              ) : null}
              <p className="text-sm font-medium">Yedek içeriği</p>
              {CONTENT_BITS.map(([bit, label]) => (
                <label key={bit} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={(draft.contains & bit) === bit}
                    onChange={() => setDraft({ ...draft, contains: draft.contains & bit ? draft.contains & ~bit : draft.contains | bit })}
                  />
                  {label}
                </label>
              ))}
              {(draft.contains & 8) === 8 ? (
                <div className="grid gap-2 pl-6">
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={draft.email_contents} onChange={() => setDraft({ ...draft, email_contents: !draft.email_contents })} />
                    İleti içeriğini dahil et
                  </label>
                  {draft.email_contents ? (
                    <label className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={draft.exclude_junk} onChange={() => setDraft({ ...draft, exclude_junk: !draft.exclude_junk })} />
                      Çöp, spam ve taslakları hariç tut
                    </label>
                  ) : null}
                </div>
              ) : null}
              {(draft.contains & 4) === 4 ? (
                <Field label="Hariç veritabanları" hint="Virgülle ayırın. Boşsa hepsi alınır.">
                  <Input value={draft.exclude_databases} onChange={(event) => setDraft({ ...draft, exclude_databases: event.target.value })} />
                </Field>
              ) : null}
              <p className="text-xs text-muted-foreground">Hepsi işaretliyken paket bugünkü tam yedeklemedir. Günlükler, API belirteçleri ve bant verisi her zaman dışarıda kalır. Eksik kutu, çalışan tur bitmeden etkinleşmez.</p>
            </TabsContent>
          </Tabs>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Vazgeç</Button>
            <Button onClick={save} disabled={busy || !draft.destination_id}>Kaydet</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={removeId !== null} onOpenChange={(next) => !next && setRemoveId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Görev silinsin mi?</DialogTitle>
            <DialogDescription>Geçmiş kayıtlar durur. Kuyrukta işlem varsa silme reddedilir.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemoveId(null)}>Vazgeç</Button>
            <Button variant="destructive" onClick={remove} disabled={busy}>Sil</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
