import { useCallback, useEffect, useState } from "react"
import { Plus, RefreshCw, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Field } from "@/components/field"
import { api, type Destination } from "@/lib/api"

type Kind = "ftp" | "s3" | "s3compat" | "gdrive" | "dropbox" | "onedrive"

type Draft = {
  id?: number
  name: string
  kind: Kind
  host: string
  port: number
  username: string
  password: string
  path: string
  passive: boolean
  tls: boolean
  region: string
  prefix: string
  code: string
}

const emptyDraft = (): Draft => ({
  name: "",
  kind: "ftp",
  host: "",
  port: 21,
  username: "",
  password: "",
  path: "/backups",
  passive: true,
  tls: false,
  region: "eu-central-1",
  prefix: "cpbackup",
  code: "",
})

export function Destinations({ onNotify }: { onNotify: (message: string, error?: boolean) => void }) {
  const [rows, setRows] = useState<Destination[]>([])
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<Draft>(emptyDraft())
  const [busy, setBusy] = useState(false)
  const [removeId, setRemoveId] = useState<number | null>(null)

  const load = useCallback(() => {
    api<{ data: Destination[] }>("destinations")
      .then((result) => setRows(result.data))
      .catch((error: Error) => onNotify(error.message, true))
  }, [onNotify])

  useEffect(() => {
    load()
  }, [load])

  function edit(row?: Destination) {
    setDraft(
      row
        ? {
            id: row.id,
            name: row.name,
            kind: row.kind || "ftp",
            host: row.host,
            port: row.port,
            username: row.username,
            password: "",
            path: row.path,
            passive: row.passive,
            tls: row.tls,
            region: row.region || "",
            prefix: row.prefix || "",
            code: "",
          }
        : emptyDraft(),
    )
    setOpen(true)
  }

  async function save() {
    setBusy(true)
    try {
      await api("destination.save", draft)
      setOpen(false)
      onNotify("Hedef kaydedildi.")
      load()
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Kayıt başarısız", true)
    } finally {
      setBusy(false)
    }
  }

  async function test() {
    setBusy(true)
    try {
      const result = await api<{ message: string }>("destination.test", draft)
      onNotify(result.message)
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Bağlantı başarısız", true)
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!removeId) return
    setBusy(true)
    try {
      await api("destination.delete", { id: removeId })
      setRemoveId(null)
      onNotify("Hedef silindi.")
      load()
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Silinemedi", true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid gap-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">FTP bugünkü gibi durur. S3 ve bulut hedefleri, çalışan yedek turu bitince göreve bağlanır.</p>
        <Button onClick={() => edit()}>
          <Plus className="h-4 w-4" /> Hedef ekle
        </Button>
      </div>
      <Card>
        <CardContent className="px-0 py-0">
          {rows.length === 0 ? (
            <p className="p-6 text-sm text-muted-foreground">Henüz FTP hedefi yok.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ad</TableHead>
                  <TableHead>Sunucu</TableHead>
                  <TableHead>Dizin</TableHead>
                  <TableHead>Mod</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="font-medium">{row.name}</TableCell>
                    <TableCell>{row.username}@{row.host}:{row.port}</TableCell>
                    <TableCell>{row.path}</TableCell>
                    <TableCell className="space-x-1">
                      <Badge variant="secondary">{row.kind === "s3" ? "Amazon S3" : row.kind === "s3compat" ? "S3 uyumlu" : row.kind === "gdrive" ? "Drive" : row.kind === "dropbox" ? "Dropbox" : row.kind === "onedrive" ? "OneDrive" : row.tls ? "FTPS" : "FTP"}</Badge>
                      <Badge variant="outline">{row.passive ? "Pasif" : "Aktif"}</Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => edit(row)}>Düzenle</Button>
                      <Button variant="ghost" size="sm" onClick={() => setRemoveId(row.id)}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{draft.id ? "Hedefi düzenle" : "Yedek hedefi"}</DialogTitle>
            <DialogDescription>Aynı hesap paketi seçilen yere gider. Anahtar ve jeton geri gösterilmez.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <Field label="Ad"><Input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></Field>
            <Field label="Tür">
              <select className="h-9 w-full rounded-md border bg-card px-3 text-sm" value={draft.kind} onChange={(event) => setDraft({ ...draft, kind: event.target.value as Kind })}>
                <option value="ftp">FTP</option>
                <option value="s3">Amazon S3</option>
                <option value="s3compat">S3 uyumlu</option>
                <option value="gdrive">Google Drive</option>
                <option value="dropbox">Dropbox</option>
                <option value="onedrive">OneDrive</option>
              </select>
            </Field>
            {draft.kind === "ftp" ? (
              <div className="grid grid-cols-[1fr_120px] gap-3">
                <Field label="Sunucu"><Input value={draft.host} onChange={(event) => setDraft({ ...draft, host: event.target.value })} placeholder="ftp.ornek.com" /></Field>
                <Field label="Port"><Input type="number" value={draft.port} onChange={(event) => setDraft({ ...draft, port: Number(event.target.value) })} /></Field>
              </div>
            ) : null}
            {draft.kind === "s3compat" ? (
              <Field label="Uç nokta"><Input value={draft.host} onChange={(event) => setDraft({ ...draft, host: event.target.value })} placeholder="s3.eu-central-1.wasabisys.com" /></Field>
            ) : null}
            {draft.kind === "s3" || draft.kind === "s3compat" ? (
              <>
                <Field label="Bölge"><Input value={draft.region} onChange={(event) => setDraft({ ...draft, region: event.target.value })} /></Field>
                <Field label="Kova"><Input value={draft.path} onChange={(event) => setDraft({ ...draft, path: event.target.value })} /></Field>
                <Field label="Önek"><Input value={draft.prefix} onChange={(event) => setDraft({ ...draft, prefix: event.target.value })} /></Field>
                <Field label="Erişim anahtarı"><Input value={draft.username} onChange={(event) => setDraft({ ...draft, username: event.target.value })} /></Field>
                <Field label="Gizli anahtar" hint={draft.id ? "Boş bırakırsanız mevcut anahtar korunur." : undefined}>
                  <Input type="password" value={draft.password} onChange={(event) => setDraft({ ...draft, password: event.target.value })} autoComplete="new-password" />
                </Field>
              </>
            ) : null}
            {draft.kind === "gdrive" || draft.kind === "dropbox" || draft.kind === "onedrive" ? (
              <>
                <Field label="İstemci kimliği"><Input value={draft.username} onChange={(event) => setDraft({ ...draft, username: event.target.value })} /></Field>
                <Field label="İstemci sırrı" hint={draft.id ? "Boş bırakırsanız mevcut sır korunur." : undefined}>
                  <Input type="password" value={draft.password} onChange={(event) => setDraft({ ...draft, password: event.target.value })} autoComplete="new-password" />
                </Field>
                <Field label="Klasör"><Input value={draft.path} onChange={(event) => setDraft({ ...draft, path: event.target.value })} /></Field>
                <Field label="Yönlendirme adresi" hint="Bunu uygulamanın yönlendirme adresine bir kez yapıştır. Gmail ile bağlan deyince hesap açılır ve bu sunucuya döner.">
                  <Input readOnly value={`${window.location.origin}/cgi/cpbackup/api.cgi?action=destination.oauth`} />
                </Field>
              </>
            ) : null}
            {draft.kind === "ftp" ? (
              <>
            <Field label="Kullanıcı"><Input value={draft.username} onChange={(event) => setDraft({ ...draft, username: event.target.value })} /></Field>
            <Field label="Parola" hint={draft.id ? "Boş bırakırsanız mevcut parola korunur." : undefined}>
              <Input type="password" value={draft.password} onChange={(event) => setDraft({ ...draft, password: event.target.value })} autoComplete="new-password" />
            </Field>
            <Field label="Uzak dizin"><Input value={draft.path} onChange={(event) => setDraft({ ...draft, path: event.target.value })} /></Field>
            <div className="flex items-center justify-between gap-4 rounded-md border px-3 py-2">
              <div>
                <span className="text-sm">Pasif mod</span>
                <p className="text-xs text-muted-foreground">Bağlantı limiti olan FTP sunucularında açık kalır. Aktarım aynı oturumda sırayla gider.</p>
              </div>
              <Switch checked={draft.passive} onCheckedChange={(passive) => setDraft({ ...draft, passive })} />
            </div>
            <div className="flex items-center justify-between rounded-md border px-3 py-2">
              <span className="text-sm">FTPS (açık TLS)</span>
              <Switch checked={draft.tls} onCheckedChange={(tls) => setDraft({ ...draft, tls })} />
            </div>
              </>
            ) : null}
          </div>
          <DialogFooter>
            {draft.kind === "gdrive" || draft.kind === "dropbox" || draft.kind === "onedrive" ? (
              <>
                <Button variant="outline" disabled={busy || !draft.id} onClick={async () => {
                  try {
                    const result = await api<{ url: string }>("destination.auth_url", { id: draft.id })
                    if (window.top) window.top.location.href = result.url
                    else window.location.href = result.url
                  } catch (error) {
                    onNotify(error instanceof Error ? error.message : "Bağlantı adresi alınamadı", true)
                  }
                }}>{draft.kind === "gdrive" ? "Gmail ile bağlan" : "Bağlan"}</Button>
              </>
            ) : null}
            <Button variant="outline" onClick={test} disabled={busy}><RefreshCw className="h-4 w-4" /> Bağlantıyı sına</Button>
            <Button onClick={save} disabled={busy}>Kaydet</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={removeId !== null} onOpenChange={(next) => !next && setRemoveId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Hedef silinsin mi?</DialogTitle>
            <DialogDescription>Bağlı bir görev varsa silme reddedilir. Uzaktaki dosyalar durur.</DialogDescription>
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
