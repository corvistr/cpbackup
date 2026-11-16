import { useCallback, useEffect, useState } from "react"
import { ArrowLeft } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { StatusBadge } from "@/components/status-badge"
import { BatchCounts } from "@/pages/Dashboard"
import { api, formatBytes, type BackupRun, type BatchSummary } from "@/lib/api"

export function History({ onNotify }: { onNotify: (message: string, error?: boolean) => void }) {
  const [rows, setRows] = useState<BatchSummary[]>([])
  const [limit, setLimit] = useState(50)
  const [query, setQuery] = useState("")
  const [selected, setSelected] = useState<number | null>(null)
  const [batch, setBatch] = useState<BatchSummary | null>(null)
  const [accounts, setAccounts] = useState<BackupRun[]>([])
  const [accountQuery, setAccountQuery] = useState("")
  const [log, setLog] = useState("")
  const [logOpen, setLogOpen] = useState(false)
  const [restore, setRestore] = useState<BackupRun | null>(null)
  const [confirm, setConfirm] = useState("")
  const [force, setForce] = useState(false)
  const [busy, setBusy] = useState(false)
  const [remove, setRemove] = useState<BackupRun | null>(null)
  const [wipeStep, setWipeStep] = useState<0 | 1 | 2>(0)

  const load = useCallback(() => {
    const q = query.trim() ? `&q=${encodeURIComponent(query.trim())}` : ""
    api<{ data: BatchSummary[] }>("batches", undefined, `&limit=${limit}${q}`)
      .then((result) => setRows(result.data))
      .catch((error: Error) => onNotify(error.message, true))
  }, [limit, onNotify, query])

  const loadDetail = useCallback(() => {
    if (selected === null) return
    api<{ data: { batch: BatchSummary; runs: BackupRun[] } }>("batch", undefined, `&id=${selected}`)
      .then((result) => {
        setBatch(result.data.batch)
        setAccounts(result.data.runs)
      })
      .catch((error: Error) => onNotify(error.message, true))
  }, [onNotify, selected])

  useEffect(() => {
    if (selected !== null) return
    load()
    const timer = window.setInterval(load, 8000)
    return () => window.clearInterval(timer)
  }, [load, selected])

  useEffect(() => {
    if (selected === null) return
    loadDetail()
    const timer = window.setInterval(loadDetail, 8000)
    return () => window.clearInterval(timer)
  }, [loadDetail, selected])

  const visibleAccounts = accounts.filter((row) => {
    const text = accountQuery.trim().toLowerCase()
    if (!text) return true
    return row.account.toLowerCase().includes(text) || (row.error || "").toLowerCase().includes(text)
  })

  async function openLog(row: BackupRun) {
    try {
      const result = await api<{ data: BackupRun }>("run.log", { id: row.id })
      setLog(result.data.log || row.error || "Günlük boş.")
      setLogOpen(true)
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Günlük alınamadı", true)
    }
  }

  async function startRestore() {
    if (!restore) return
    setBusy(true)
    try {
      await api("restore", { id: restore.id, confirm, force })
      setRestore(null)
      setConfirm("")
      setForce(false)
      onNotify("Geri yükleme kuyruğa alındı.")
      loadDetail()
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Geri yükleme başlatılamadı", true)
    } finally {
      setBusy(false)
    }
  }

  async function wipeRemote() {
    if (selected === null) return
    setBusy(true)
    try {
      const result = await api<{ deleted: number; busy: number }>("batch.delete_remote", {
        id: selected,
        confirm: "evet",
        sure: "evet",
      })
      setWipeStep(0)
      const waiting = result.busy ? ` ${result.busy} hesap hâlâ sürüyor, onlara dokunulmadı.` : ""
      onNotify(`${result.deleted} yedek FTP'den silindi.${waiting}`)
      loadDetail()
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "FTP silme tamamlanamadı", true)
    } finally {
      setBusy(false)
    }
  }

  async function stopBatch() {
    if (selected === null || !batch) return
    setBusy(true)
    try {
      const result = await api<{ cancelled: number }>("batch.stop", { id: selected, stop: true })
      const runningNote = batch.running > 0 ? " Süren hesap yüklenmeden kapatılıyor." : ""
      onNotify(
        result.cancelled
          ? `${result.cancelled} bekleyen hesap iptal edildi. Diğer yedekler sürer.${runningNote}`
          : `Bekleyen hesap yok. Diğer yedekler sürer.${runningNote}`,
      )
      loadDetail()
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Durdurma kaydedilemedi", true)
    } finally {
      setBusy(false)
    }
  }

  async function deleteRemote() {
    if (!remove) return
    setBusy(true)
    try {
      await api("run.delete_remote", { id: remove.id })
      setRemove(null)
      onNotify("Uzak dosya silindi.")
      loadDetail()
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Silinemedi", true)
    } finally {
      setBusy(false)
    }
  }

  if (selected !== null) {
    return (
      <div className="grid gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Button variant="outline" size="sm" onClick={() => { setSelected(null); setAccountQuery("") }}>
              <ArrowLeft className="h-4 w-4" /> Liste
            </Button>
            <div>
              <h2 className="text-base font-semibold">{batch?.title || "Çalıştırma"}</h2>
              <p className="text-xs text-muted-foreground">{batch?.created_at}{batch?.finished_at ? ` · bitti ${batch.finished_at}` : ""}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {batch && batch.failed > 0 ? (
              <Button variant="outline" size="sm" disabled={busy} onClick={async () => {
                setBusy(true)
                try {
                  const result = await api<{ queued: number }>("batch.retry_failed", { id: batch.id })
                  onNotify(result.queued ? `${result.queued} hatalı hesap yeniden kuyruğa alındı.` : "Yeniden denenecek hatalı hesap yok.")
                  loadDetail()
                } catch (error) {
                  onNotify(error instanceof Error ? error.message : "Yeniden deneme açılamadı", true)
                } finally {
                  setBusy(false)
                }
              }}>Hatalıları yeniden dene</Button>
            ) : null}
            {batch && !batch.stop_requested && (batch.queued + batch.running) > 0 ? (
              <Button variant="outline" size="sm" disabled={busy} onClick={stopBatch}>
                Durdur
              </Button>
            ) : null}
            {batch?.stop_requested ? (
              <span className="text-xs text-muted-foreground">
                Bu çalıştırma kapatıldı. Bekleyenler iptal edildi; diğer yedekler sürer.
                {batch.running > 0 ? " Süren hesap yüklenmeden kapatılıyor." : ""}
              </span>
            ) : null}
            {batch ? <BatchCounts batch={batch} /> : null}
          </div>
        </div>
        {batch && batch.uploaded > 0 ? (
          <div className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 rounded-md border border-red-200 bg-red-50 px-4 py-3">
            <p className="text-sm text-red-950">
              Bu çalıştırmada FTP'ye yüklenmiş {batch.uploaded} yedek var. Satırdaki “Uzak dosya” yalnızca o hesabı siler.
            </p>
            <Button className="bg-red-600 text-white hover:bg-red-700" size="sm" disabled={busy} onClick={() => setWipeStep(1)}>
              FTP'den bu işlemin yedeklerini sil
            </Button>
          </div>
        ) : null}
        <Input placeholder="Hesap ara" value={accountQuery} onChange={(event) => setAccountQuery(event.target.value)} className="max-w-xs" />
        <Card>
          <CardContent className="px-0 py-0">
            {visibleAccounts.length === 0 ? (
              <p className="p-6 text-sm text-muted-foreground">Bu çalıştırmada kayıt yok.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Hesap</TableHead>
                    <TableHead>Tür</TableHead>
                    <TableHead>Durum</TableHead>
                    <TableHead>Boyut</TableHead>
                    <TableHead>Zaman</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visibleAccounts.map((row) => (
                    <TableRow key={row.id}>
                      <TableCell className="font-medium">{row.account}</TableCell>
                      <TableCell>{row.kind === "restore" ? "Geri yükleme" : "Yedek"}</TableCell>
                      <TableCell>
                        <StatusBadge status={row.status} />
                        {row.error ? <p className="mt-1 max-w-xs text-xs text-red-700">{row.error}</p> : null}
                      </TableCell>
                      <TableCell>{formatBytes(row.size_bytes)}</TableCell>
                      <TableCell>{row.finished_at || row.created_at}</TableCell>
                      <TableCell className="space-x-1 text-right">
                        <Button variant="ghost" size="sm" onClick={() => openLog(row)}>Günlük</Button>
                        {row.kind === "backup" && row.status === "uploaded" ? (
                          <Button variant="outline" size="sm" onClick={() => { setRestore(row); setConfirm(""); setForce(false) }}>Geri yükle</Button>
                        ) : null}
                        {row.remote_path && row.status === "uploaded" ? (
                          <Button variant="ghost" size="sm" onClick={async () => {
                            try {
                              await api("run.lock", { id: row.id, locked: !row.locked })
                              onNotify(row.locked ? "Kilit kalktı. Eski çalışan tur bu kilidi görmez." : "Kopya kilitlendi. Yeni tur bunu saklama sayısından çıkarır.")
                              loadDetail()
                            } catch (error) {
                              onNotify(error instanceof Error ? error.message : "Kilit yazılamadı", true)
                            }
                          }}>{row.locked ? "Kilidi aç" : "Kilitle"}</Button>
                        ) : null}
                        {row.remote_path && row.status !== "queued" && row.status !== "running" && row.status !== "deleted" ? (
                          <Button variant="ghost" size="sm" onClick={() => setRemove(row)}>Uzak dosya</Button>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
        {dialogs()}
      </div>
    )
  }

  return (
    <div className="grid gap-4">
      <Input placeholder="Görev veya hesap ara" value={query} onChange={(event) => setQuery(event.target.value)} className="max-w-xs" />
      <Card>
        <CardContent className="px-0 py-0">
          {rows.length === 0 ? (
            <p className="p-6 text-sm text-muted-foreground">Kayıt yok.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Çalıştırma</TableHead>
                  <TableHead>Hesap</TableHead>
                  <TableHead>Sonuç</TableHead>
                  <TableHead>Zaman</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id} className="cursor-pointer" onClick={() => setSelected(row.id)}>
                    <TableCell className="font-medium">{row.title}</TableCell>
                    <TableCell>{row.total}</TableCell>
                    <TableCell><BatchCounts batch={row} /></TableCell>
                    <TableCell>{row.finished_at || row.created_at}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      {rows.length >= limit ? (
        <Button variant="outline" onClick={() => setLimit((value) => value + 50)}>Daha eski kayıtlar</Button>
      ) : null}
      {dialogs()}
    </div>
  )

  function dialogs() {
    return (
      <>
        <Dialog open={wipeStep === 1} onOpenChange={(open) => !open && setWipeStep(0)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Silmeyi onaylıyor musunuz?</DialogTitle>
              <DialogDescription>
                {batch ? `${batch.title} çalıştırmasında FTP'ye yüklenmiş ${batch.uploaded} yedek silinir. Üç kopyalık saklama kuralı ayrı çalışır.` : ""}
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setWipeStep(0)}>Vazgeç</Button>
              <Button onClick={() => setWipeStep(2)}>Evet</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Dialog open={wipeStep === 2} onOpenChange={(open) => !open && setWipeStep(0)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Emin misiniz?</DialogTitle>
              <DialogDescription>Silinen dosyalar FTP'den geri gelmez.</DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setWipeStep(0)}>Vazgeç</Button>
              <Button variant="destructive" disabled={busy} onClick={wipeRemote}>Evet, sil</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Dialog open={logOpen} onOpenChange={setLogOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>İşlem günlüğü</DialogTitle>
              <DialogDescription>Son kayıtlar aşağıdadır.</DialogDescription>
            </DialogHeader>
            <Textarea readOnly value={log} className="min-h-[240px] font-mono text-xs" />
          </DialogContent>
        </Dialog>

        <Dialog open={restore !== null} onOpenChange={(next) => !next && setRestore(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Geri yükleme</DialogTitle>
              <DialogDescription>
                {restore ? `${restore.account} hesabının dosyaları, veritabanları ve yapılandırması bu yedekle değiştirilebilir.` : ""}
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-3">
              <Input placeholder="Onay için hesap adını yazın" value={confirm} onChange={(event) => setConfirm(event.target.value)} />
              <div className="flex items-center justify-between rounded-md border px-3 py-2">
                <span className="text-sm">Mevcut hesabın üzerine yaz</span>
                <Switch checked={force} onCheckedChange={setForce} />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setRestore(null)}>Vazgeç</Button>
              <Button variant="destructive" disabled={busy || confirm !== restore?.account} onClick={startRestore}>Kuyruğa al</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Dialog open={remove !== null} onOpenChange={(next) => !next && setRemove(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Uzak yedek silinsin mi?</DialogTitle>
              <DialogDescription>{remove?.remote_path}</DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setRemove(null)}>Vazgeç</Button>
              <Button variant="destructive" disabled={busy} onClick={deleteRemote}>Sil</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </>
    )
  }
}
