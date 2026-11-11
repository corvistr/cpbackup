import { useEffect, useMemo, useState } from "react"
import { api, formatBytes, type BackupRun } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { StatusBadge } from "@/components/status-badge"
import { cn } from "@/lib/utils"

type AccountHit = {
  user: string
  domain: string
  suspended: boolean
}

export function Restore({ onNotify }: { onNotify: (message: string, error?: boolean) => void }) {
  const [accounts, setAccounts] = useState<AccountHit[]>([])
  const [query, setQuery] = useState("")
  const [picked, setPicked] = useState<AccountHit | null>(null)
  const [rows, setRows] = useState<BackupRun[]>([])
  const [loading, setLoading] = useState(false)
  const [restore, setRestore] = useState<BackupRun | null>(null)
  const [confirm, setConfirm] = useState("")
  const [force, setForce] = useState(false)
  const [busy, setBusy] = useState(false)
  const [piece, setPiece] = useState<BackupRun | null>(null)
  const [entries, setEntries] = useState<{ kind: string; path: string; size_bytes: number }[]>([])
  const [pickedPaths, setPickedPaths] = useState<string[]>([])
  const [preview, setPreview] = useState(true)
  const [pieceNote, setPieceNote] = useState("")
  const [pieceConfirm, setPieceConfirm] = useState("")

  useEffect(() => {
    api<{ data: AccountHit[] }>("accounts.directory")
      .then((result) => setAccounts(result.data))
      .catch((error: Error) => onNotify(error.message, true))
  }, [onNotify])

  const matches = useMemo(() => {
    const text = query.trim().toLowerCase()
    if (!text || picked) return []
    return accounts
      .filter((row) => row.user.includes(text) || row.domain.toLowerCase().includes(text))
      .slice(0, 8)
  }, [accounts, picked, query])

  async function choose(account: AccountHit) {
    setPicked(account)
    setQuery(account.user)
    setRows([])
    setLoading(true)
    try {
      const result = await api<{ data: BackupRun[] }>(
        "account.backups",
        undefined,
        `&user=${encodeURIComponent(account.user)}&limit=30`,
      )
      setRows(result.data)
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Yedekler alınamadı", true)
    } finally {
      setLoading(false)
    }
  }

  function clearPick() {
    setPicked(null)
    setQuery("")
    setRows([])
  }

  async function openPiece(row: BackupRun) {
    setPiece(row)
    setEntries([])
    setPickedPaths([])
    setPreview(true)
    setPieceConfirm("")
    setPieceNote("Liste hazırlanıyor. Eski yedekte arşiv bir kez indirilir; büyük hesapta bu uzun sürer.")
    try {
      const result = await api<{ items: { kind: string; path: string; size_bytes: number }[]; message?: string }>(
        "backup.entries",
        undefined,
        `&id=${row.id}`,
      )
      setEntries(result.items || [])
      setPieceNote(result.message || (result.items?.length ? "" : "Bu arşivde listelenecek parça yok."))
    } catch (error) {
      setPieceNote(error instanceof Error ? error.message : "Liste alınamadı")
    }
  }

  function togglePiece(path: string) {
    setPickedPaths((current) => current.includes(path) ? current.filter((item) => item !== path) : [...current, path])
  }

  async function startPiece() {
    if (!piece || !picked) return
    setBusy(true)
    try {
      await api("restore.partial", {
        id: piece.id,
        confirm: preview ? picked.user : pieceConfirm,
        preview,
        items: entries.filter((item) => pickedPaths.includes(item.path)).map((item) => ({ kind: item.kind, path: item.path })),
      })
      setPiece(null)
      onNotify(preview ? "Önizleme kuyruğa alındı. Dosyalar hesabın cpbackup-onizleme klasörüne çıkar." : "Parça geri yükleme kuyruğa alındı.")
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Parça geri yükleme başlatılamadı", true)
    } finally {
      setBusy(false)
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
      onNotify("Geri yükleme kuyruğa alındı. Hesap bitene kadar mevcut dosyalar durur.")
      if (picked) choose(picked)
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Geri yükleme başlatılamadı", true)
    } finally {
      setBusy(false)
    }
  }

  const ready = rows.filter((row) => row.status === "uploaded" && row.remote_path)

  return (
    <div className="grid gap-3">
      <div className="rounded-lg border bg-card px-4 py-4">
        <p className="text-sm font-medium">Hesap seçin</p>
        <p className="mt-1 text-[11px] text-muted-foreground">
          Yüklenmiş yedeği geri yükleyebilir veya tarayıcıya indirebilirsiniz. Geri yükleme o hesabın dosyalarını, veritabanlarını ve postasını seçilen arşivle değiştirir.
        </p>
        <div className="relative mt-3 max-w-md">
          <Input
            placeholder="Hesap veya alan adı"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              if (picked && event.target.value !== picked.user) setPicked(null)
            }}
          />
          {matches.length > 0 ? (
            <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-md border bg-card shadow-md">
              {matches.map((row) => (
                <button
                  key={row.user}
                  type="button"
                  onClick={() => choose(row)}
                  className={cn("flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-xs hover:bg-muted", row.suspended && "bg-red-50")}
                >
                  <span>
                    <span className="font-medium">{row.user}</span>
                    <span className="ml-2 text-muted-foreground">{row.domain}</span>
                  </span>
                  {row.suspended ? <span className="text-[11px] text-red-700">Askıda</span> : null}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      {picked ? (
        <div className="rounded-lg border bg-card">
          <div className="flex items-center justify-between gap-3 px-4 py-3">
            <div>
              <p className="text-sm font-medium">{picked.user}</p>
              <p className="text-[11px] text-muted-foreground">{picked.domain} · {ready.length} indirilebilir yedek</p>
            </div>
            <Button variant="outline" size="sm" onClick={clearPick}>Başka hesap</Button>
          </div>
          {loading ? <p className="border-t px-4 py-3 text-xs text-muted-foreground">Yedekler yükleniyor…</p> : rows.length === 0 ? (
            <p className="border-t px-4 py-3 text-xs text-muted-foreground">Bu hesabın yedek kaydı yok.</p>
          ) : rows.map((row) => {
            const canUse = row.status === "uploaded" && Boolean(row.remote_path)
            return (
              <div key={row.id} className="flex flex-wrap items-center justify-between gap-2 border-t px-4 py-2.5">
                <div className="min-w-0">
                  <p className="text-xs font-medium">{row.finished_at || row.created_at}</p>
                  <p className="text-[11px] text-muted-foreground">{formatBytes(row.size_bytes)}{row.error ? ` · ${row.error}` : ""}</p>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={row.status} />
                  {canUse ? (
                    <>
                      <Button variant="outline" size="sm" asChild>
                        <a href={`api.cgi?action=backup.download&id=${row.id}`}>İndir</a>
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => openPiece(row)}>Parça</Button>
                      <Button size="sm" onClick={() => { setRestore(row); setConfirm(""); setForce(false) }}>Geri yükle</Button>
                    </>
                  ) : null}
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <p className="text-[11px] text-muted-foreground">Aramaya hesap adı yazın. Askıdaki hesaplar kırmızı görünür; yedeği varsa yine indirilebilir.</p>
      )}

      <Dialog open={piece !== null} onOpenChange={(next) => !next && setPiece(null)}>
        <DialogContent className="max-h-[80vh] overflow-auto">
          <DialogHeader>
            <DialogTitle>Parça geri yükleme</DialogTitle>
            <DialogDescription>
              Seçilen dosya, veritabanı veya posta kutusu çıkarılır. Önizleme canlı siteyi ve postayı değiştirmez.
            </DialogDescription>
          </DialogHeader>
          {pieceNote ? <p className="text-sm text-muted-foreground">{pieceNote}</p> : null}
          <div className="max-h-64 overflow-auto rounded-md border">
            {entries.map((item) => (
              <label key={`${item.kind}:${item.path}`} className="flex items-center gap-2 border-b px-3 py-2 text-sm last:border-0">
                <input type="checkbox" checked={pickedPaths.includes(item.path)} onChange={() => togglePiece(item.path)} />
                <span className="text-xs text-muted-foreground">{item.kind === "database" ? "Veritabanı" : item.kind === "mailbox" ? "Posta" : item.kind === "dir" ? "Klasör" : "Dosya"}</span>
                <span className="min-w-0 flex-1 truncate">{item.path}</span>
                <span className="text-xs text-muted-foreground">{formatBytes(item.size_bytes)}</span>
              </label>
            ))}
          </div>
          <div className="flex items-center justify-between rounded-md border px-3 py-2">
            <span className="text-sm">Önizleme (cpbackup-onizleme)</span>
            <Switch checked={preview} onCheckedChange={setPreview} />
          </div>
          {!preview ? (
            <Input value={pieceConfirm} onChange={(event) => setPieceConfirm(event.target.value)} placeholder={picked?.user || "hesap adı"} />
          ) : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setPiece(null)}>Vazgeç</Button>
            <Button onClick={startPiece} disabled={busy || pickedPaths.length === 0 || (!preview && pieceConfirm !== picked?.user)}>Uygula</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={restore !== null} onOpenChange={(next) => !next && setRestore(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Geri yükleme</DialogTitle>
            <DialogDescription>
              {restore ? `${restore.account} hesabı bu yedekle değiştirilir. Onay için hesap adını yazın.` : ""}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <Input placeholder="Hesap adı" value={confirm} onChange={(event) => setConfirm(event.target.value)} />
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
    </div>
  )
}
