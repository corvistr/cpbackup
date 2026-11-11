import { useCallback, useEffect, useState } from "react"
import { Archive, ArrowLeft, DatabaseBackup, PanelLeftClose, PanelLeftOpen } from "lucide-react"
import { Logo } from "@/components/logo"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { StatusBadge } from "@/components/status-badge"
import { CONTENT_BITS, FULL_CONTAINS, formatBytes, panelHome } from "@/lib/api"
import { cn } from "@/lib/utils"

type Item = {
  id: number
  kind: "backup" | "restore"
  status: string
  size_bytes: number | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  error: string | null
  manual: boolean
  expires_at: string | null
}

type ListResponse = {
  ok: boolean
  account: string
  allow_restore: boolean
  items: Item[]
  error?: string
}

type Page = "create" | "list"

const activeStatus = new Set(["queued", "running", "packaging", "packaged", "uploading"])

async function userApi<T>(action: string, body?: unknown, query = ""): Promise<T> {
  const response = await fetch(`index.cgi?action=${encodeURIComponent(action)}${query}`, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json", "X-CPBackup": "1" },
    body: body ? JSON.stringify(body) : undefined,
  })
  const payload = (await response.json()) as { ok?: boolean; error?: string } & T
  if (!payload.ok) throw new Error(payload.error || "İşlem başarısız.")
  return payload
}

function readCollapsed() {
  try {
    return localStorage.getItem("cpbackup-user-nav") === "icons"
  } catch {
    return false
  }
}

export function UserApp() {
  const [page, setPage] = useState<Page>("list")
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [data, setData] = useState<ListResponse | null>(null)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [target, setTarget] = useState<Item | null>(null)
  const [remove, setRemove] = useState<Item | null>(null)
  const [confirm, setConfirm] = useState("")
  const [summary, setSummary] = useState("")
  const [busy, setBusy] = useState(false)
  const [mode, setMode] = useState<"full" | "partial">("full")
  const [contains, setContains] = useState(FULL_CONTAINS)
  const [emailContents, setEmailContents] = useState(true)
  const [excludeJunk, setExcludeJunk] = useState(false)
  const [piece, setPiece] = useState<Item | null>(null)
  const [entries, setEntries] = useState<{ kind: string; path: string; size_bytes: number }[]>([])
  const [pickedPaths, setPickedPaths] = useState<string[]>([])
  const [preview, setPreview] = useState(true)
  const [pieceNote, setPieceNote] = useState("")
  const [pieceConfirm, setPieceConfirm] = useState("")

  const load = useCallback(() => {
    userApi<ListResponse>("list")
      .then((result) => {
        setData(result)
        setError("")
      })
      .catch((reason: Error) => setError(reason.message))
  }, [])

  useEffect(() => {
    load()
    const timer = window.setInterval(load, 8000)
    return () => window.clearInterval(timer)
  }, [load])

  useEffect(() => {
    try {
      localStorage.setItem("cpbackup-user-nav", collapsed ? "icons" : "full")
    } catch {
      /* tarayıcı saklamayı kapattıysa menü yine çalışır */
    }
  }, [collapsed])

  async function openSummary(item: Item) {
    try {
      const result = await userApi<{ summary: string }>("log", { id: item.id })
      setSummary(result.summary)
    } catch (reason) {
      setSummary(reason instanceof Error ? reason.message : "Özet alınamadı.")
    }
  }

  async function removeBackup() {
    if (!remove) return
    setBusy(true)
    try {
      await userApi("delete", { id: remove.id })
      setRemove(null)
      setNotice("Yedek uzak sunucudan silindi. Kapladığı yer boşaldı.")
      setError("")
      load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Yedek silinemedi.")
    } finally {
      setBusy(false)
    }
  }

  async function restore() {
    if (!target) return
    setBusy(true)
    try {
      await userApi("restore", { id: target.id, confirm })
      setTarget(null)
      setConfirm("")
      setNotice("Geri yükleme kuyruğa alındı. Ekran kapansa da sürer.")
      setError("")
      load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Geri yükleme başlatılamadı.")
    } finally {
      setBusy(false)
    }
  }

  async function openPiece(item: Item) {
    setPiece(item)
    setEntries([])
    setPickedPaths([])
    setPreview(true)
    setPieceConfirm("")
    setPieceNote("Liste hazırlanıyor.")
    try {
      const result = await userApi<{ items: { kind: string; path: string; size_bytes: number }[]; pending?: boolean; message?: string }>(
        "entries",
        undefined,
        `&id=${item.id}`,
      )
      setEntries(result.items || [])
      setPieceNote(result.pending ? (result.message || "İç liste henüz yok.") : "")
    } catch (reason) {
      setPieceNote(reason instanceof Error ? reason.message : "Liste alınamadı.")
    }
  }

  async function startPiece() {
    if (!piece) return
    setBusy(true)
    try {
      await userApi("partial", {
        id: piece.id,
        confirm: preview ? data?.account : pieceConfirm,
        preview,
        items: entries.filter((item) => pickedPaths.includes(item.path)).map((item) => ({ kind: item.kind, path: item.path })),
      })
      setPiece(null)
      setNotice(preview ? "Önizleme kuyruğa alındı. Dosyalar cpbackup-onizleme klasörüne çıkar." : "Parça geri yükleme kuyruğa alındı.")
      setError("")
      load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Parça geri yükleme başlatılamadı.")
    } finally {
      setBusy(false)
    }
  }

  async function startBackup() {
    setBusy(true)
    setNotice("")
    try {
      const result = await userApi<{ expires_at: string }>("backup", mode === "full"
        ? { contains: FULL_CONTAINS, email_contents: true, exclude_junk: false, exclude_databases: [] }
        : { contains, email_contents: emailContents, exclude_junk: excludeJunk, exclude_databases: [] })
      setNotice(`Yedek kuyruğa alındı. Hazır olunca 48 saat durur, ${result.expires_at} tarihinde silinir.`)
      setError("")
      setPage("list")
      load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Yedek başlatılamadı.")
    } finally {
      setBusy(false)
    }
  }

  const items = data?.items || []
  const running = items.find((item) => item.kind === "backup" && activeStatus.has(item.status))

  return (
    <div className="flex h-screen w-full overflow-hidden bg-slate-100">
      <aside className={cn("flex shrink-0 flex-col bg-slate-950 text-slate-100 transition-[width] duration-200", collapsed ? "w-[4.5rem]" : "w-56")}>
        <div className={cn("flex items-center px-3 pt-3", collapsed ? "justify-center" : "justify-end")}>
          <button
            type="button"
            title={collapsed ? "Menüyü genişlet" : "Menüyü daralt"}
            onClick={() => setCollapsed((value) => !value)}
            className="flex h-8 w-8 items-center justify-center rounded-md text-slate-300 hover:bg-white/10 hover:text-white"
          >
            {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </button>
        </div>
        <div className={cn("flex items-center gap-3 px-4 py-3", collapsed && "justify-center px-2")}>
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white">
            <Logo className="h-8 w-8" />
          </div>
          <div className={cn("min-w-0", collapsed && "hidden")}>
            <p className="truncate text-sm font-semibold">cPBackup</p>
            <p className="truncate text-[11px] text-slate-400">{data?.account || "Hesabım"}</p>
          </div>
        </div>
        <nav className="flex flex-1 flex-col gap-1 px-3 pb-3">
          <button
            type="button"
            title="Yedek al"
            onClick={() => setPage("create")}
            className={cn("flex items-center gap-2 rounded-md px-3 py-2 text-left text-sm", collapsed && "justify-center px-2", page === "create" ? "bg-[#ff6c2c] text-white" : "text-slate-300 hover:bg-white/5")}
          >
            <DatabaseBackup className="h-4 w-4 shrink-0" />
            <span className={cn(collapsed && "sr-only")}>Yedek al</span>
          </button>
          <button
            type="button"
            title="Yedeklerim"
            onClick={() => setPage("list")}
            className={cn("flex items-center gap-2 rounded-md px-3 py-2 text-left text-sm", collapsed && "justify-center px-2", page === "list" ? "bg-sky-600 text-white" : "text-slate-300 hover:bg-white/5")}
          >
            <Archive className="h-4 w-4 shrink-0" />
            <span className={cn(collapsed && "sr-only")}>Yedeklerim</span>
          </button>
        </nav>
        <div className={cn("px-3 py-3", collapsed && "flex justify-center px-2")}>
          <a
            href={panelHome()}
            title="cPanel'e dön"
            className={cn(
              "flex h-9 items-center justify-center gap-2 rounded-md bg-[#ff6c2c] text-xs font-medium text-white hover:bg-[#e4561c]",
              collapsed ? "w-10" : "w-full",
            )}
          >
            <ArrowLeft className={cn("h-4 w-4", collapsed ? "block" : "hidden")} />
            <span className={cn(collapsed && "sr-only")}>cPanel'e dön</span>
          </a>
        </div>
      </aside>
      <main className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 border-b bg-card px-6 py-4">
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold">{page === "create" ? "Yedek al" : "Yedeklerim"}</h1>
            <p className="truncate text-xs text-muted-foreground">{data?.account || "Hesabım"} · cPanel</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button size="sm" className="border-transparent bg-[#ff6c2c] text-white hover:bg-[#e4561c] hover:text-white" asChild>
              <a href={panelHome()}>cPanel'e dön</a>
            </Button>
            <Button variant="outline" size="sm" onClick={() => setPage(page === "create" ? "list" : "create")}>
              {page === "create" ? "Yedeklerim" : "Yedek al"}
            </Button>
          </div>
        </header>
        <div className="flex min-h-0 flex-1 flex-col gap-3 p-4 md:p-6">
        {error ? <p className="rounded-md border border-red-200 bg-gradient-to-r from-red-50 to-orange-50 px-3 py-2 text-sm text-red-800">{error}</p> : null}
        {notice ? <p className="rounded-md border border-emerald-200 bg-gradient-to-r from-emerald-50 to-teal-50 px-3 py-2 text-sm text-emerald-900">{notice}</p> : null}
        {page === "create" ? (
          <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border bg-white shadow-sm">
            <div className="bg-[#ff6c2c] px-4 py-3 text-white">
              <h1 className="text-base font-semibold">Yedek al</h1>
              <p className="text-xs text-white/90">Tam yedek hesabın tamamını alır. Parça parça seçince yalnız işaretlediklerin paketlenir.</p>
            </div>
            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-4">
              <p className="rounded-lg border border-amber-200 bg-gradient-to-r from-amber-50 to-orange-50 px-3 py-2 text-sm text-amber-950">
                Elle aldığınız yedek <strong>48 saat</strong> tutulur, süre dolunca silinir. Zamanlanmış yedekler bu süreye bağlı değildir.
              </p>
              <div className="grid gap-2 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={() => setMode("full")}
                  className={`rounded-lg border px-3 py-3 text-left ${mode === "full" ? "border-[#ff6c2c] bg-orange-50" : "border-slate-200 bg-white"}`}
                >
                  <p className="text-sm font-semibold">Tam yedek</p>
                  <p className="text-xs text-muted-foreground">Dosyalar, veritabanı, posta ve panel birlikte alınır.</p>
                </button>
                <button
                  type="button"
                  onClick={() => setMode("partial")}
                  className={`rounded-lg border px-3 py-3 text-left ${mode === "partial" ? "border-[#ff6c2c] bg-orange-50" : "border-slate-200 bg-white"}`}
                >
                  <p className="text-sm font-semibold">Parça parça</p>
                  <p className="text-xs text-muted-foreground">Yalnız seçtiğin parçalar paketlenir.</p>
                </button>
              </div>
              {mode === "partial" ? (
                <>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {CONTENT_BITS.map(([bit, label]) => (
                      <label key={bit} className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={(contains & bit) === bit}
                          onChange={() => setContains((current) => (current & bit ? current & ~bit : current | bit))}
                        />
                        {label}
                      </label>
                    ))}
                  </div>
                  {(contains & 8) === 8 ? (
                    <div className="grid gap-2">
                      <label className="flex items-center gap-2 text-sm">
                        <input type="checkbox" checked={emailContents} onChange={() => setEmailContents((value) => !value)} />
                        İleti içeriğini dahil et
                      </label>
                      {emailContents ? (
                        <label className="flex items-center gap-2 text-sm">
                          <input type="checkbox" checked={excludeJunk} onChange={() => setExcludeJunk((value) => !value)} />
                          Çöp, spam ve taslakları hariç tut
                        </label>
                      ) : null}
                    </div>
                  ) : null}
                </>
              ) : null}
              {running ? (
                <p className="mt-3 rounded-lg bg-sky-50 px-3 py-2 text-sm text-sky-900">Şu an bir yedeğiniz sürüyor. Bitince yenisini alabilirsiniz.</p>
              ) : (
                <Button className="mt-4 border-transparent bg-slate-900 text-white hover:bg-slate-700" disabled={busy || !data || (mode === "partial" && contains === 0)} onClick={startBackup}>
                  Yedek al
                </Button>
              )}
            </div>
          </section>
        ) : (
          <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border bg-white shadow-sm">
            <div className="bg-sky-700 px-4 py-3 text-white">
              <h1 className="text-base font-semibold">Yedeklerim</h1>
              <p className="mt-1 text-[11px] text-sky-100">
                Elle aldığınız yedeği Sil ile hemen kaldırabilirsiniz. Dosya uzak sunucudan da silinir. Dokunmazsanız 48 saat sonra kendiliğinden kalkar.
              </p>
              {data && !data.allow_restore ? (
                <p className="mt-2 text-[11px] text-sky-100">Geri yükleme yöneticiniz tarafından kapatıldı.</p>
              ) : null}
            </div>
            {!data ? (
              <p className="border-t px-4 py-3 text-sm text-muted-foreground">Yükleniyor…</p>
            ) : items.length === 0 ? (
              <p className="border-t px-4 py-3 text-sm text-muted-foreground">Henüz yedeğiniz yok.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Kaynak</TableHead>
                    <TableHead>Durum</TableHead>
                    <TableHead>Boyut</TableHead>
                    <TableHead>Zaman</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.id} className={item.kind === "restore" ? "bg-violet-50/70" : item.manual ? "bg-amber-50/80" : "bg-sky-50/40"}>
                      <TableCell>
                        <p>{item.kind === "restore" ? "Geri yükleme" : item.manual ? "Elle yedek" : "Zamanlanmış"}</p>
                        {item.manual && item.expires_at && item.status === "uploaded" ? (
                          <p className="text-[11px] text-muted-foreground">48 saat · silinir {item.expires_at}</p>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={item.status} />
                        {item.error ? <p className="mt-1 max-w-xs text-xs text-red-700">{item.error}</p> : null}
                      </TableCell>
                      <TableCell>{formatBytes(item.size_bytes)}</TableCell>
                      <TableCell>{item.finished_at || item.created_at}</TableCell>
                      <TableCell className="space-x-2 text-right">
                        <Button variant="ghost" size="sm" onClick={() => openSummary(item)}>Özet</Button>
                        {item.manual && item.kind === "backup" && item.status === "uploaded" ? (
                          <Button size="sm" variant="destructive" onClick={() => setRemove(item)}>Sil</Button>
                        ) : null}
                        {data.allow_restore && item.kind === "backup" && item.status === "uploaded" ? (
                          <>
                            <Button size="sm" variant="outline" onClick={() => openPiece(item)}>Parça</Button>
                            <Button size="sm" className="border-transparent bg-slate-900 text-white hover:bg-slate-700" onClick={() => { setTarget(item); setConfirm("") }}>Geri yükle</Button>
                          </>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </section>
        )}
        </div>
      </main>
      <Dialog open={summary !== ""} onOpenChange={(open) => !open && setSummary("")}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Yedek özeti</DialogTitle>
            <DialogDescription>{summary}</DialogDescription>
          </DialogHeader>
        </DialogContent>
      </Dialog>
      <Dialog open={piece !== null} onOpenChange={(open) => !open && setPiece(null)}>
        <DialogContent className="max-h-[80vh] overflow-auto">
          <DialogHeader>
            <DialogTitle>Parça geri yükleme</DialogTitle>
            <DialogDescription>Önizleme canlı siteyi ve postayı değiştirmez. Üzerine yazma hesap adını ister.</DialogDescription>
          </DialogHeader>
          {pieceNote ? <p className="text-sm text-muted-foreground">{pieceNote}</p> : null}
          <div className="max-h-64 overflow-auto rounded-md border">
            {entries.map((item) => (
              <label key={`${item.kind}:${item.path}`} className="flex items-center gap-2 border-b px-3 py-2 text-sm last:border-0">
                <input
                  type="checkbox"
                  checked={pickedPaths.includes(item.path)}
                  onChange={() => setPickedPaths((current) => current.includes(item.path) ? current.filter((path) => path !== item.path) : [...current, item.path])}
                />
                <span className="min-w-0 flex-1 truncate">{item.path}</span>
              </label>
            ))}
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={preview} onChange={() => setPreview((value) => !value)} />
            Önizleme (cpbackup-onizleme)
          </label>
          {!preview ? <Input value={pieceConfirm} onChange={(event) => setPieceConfirm(event.target.value)} placeholder={data?.account || "hesap adı"} /> : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setPiece(null)}>Vazgeç</Button>
            <Button disabled={busy || pickedPaths.length === 0 || (!preview && pieceConfirm !== data?.account)} onClick={startPiece}>Uygula</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={remove !== null} onOpenChange={(open) => !open && setRemove(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Yedeği sil</DialogTitle>
            <DialogDescription>
              Bu elle alınan yedek uzak sunucudan silinir ve kapladığı yer boşalır. Geri getirilemez.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemove(null)}>Vazgeç</Button>
            <Button variant="destructive" disabled={busy} onClick={removeBackup}>Sil</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={target !== null} onOpenChange={(open) => !open && setTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Hesabı geri yükle</DialogTitle>
            <DialogDescription>
              Bu işlem mevcut hesabın üzerine yazılır. Onay için <Badge variant="outline">{data?.account}</Badge> yazın.
            </DialogDescription>
          </DialogHeader>
          <Input value={confirm} onChange={(event) => setConfirm(event.target.value)} placeholder="Hesap adı" autoComplete="off" />
          <DialogFooter>
            <Button variant="outline" onClick={() => setTarget(null)}>Vazgeç</Button>
            <Button variant="destructive" disabled={busy || confirm !== data?.account} onClick={restore}>Kuyruğa al</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
