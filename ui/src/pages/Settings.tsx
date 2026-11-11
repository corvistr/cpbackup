import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Field } from "@/components/field"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api, type PanelStatus } from "@/lib/api"

export function Settings({ onNotify }: { onNotify: (message: string, error?: boolean) => void }) {
  const [email, setEmail] = useState("")
  const [summaryMail, setSummaryMail] = useState(true)
  const [ownerFail, setOwnerFail] = useState(false)
  const [ownerOk, setOwnerOk] = useState(false)
  const [historyDays, setHistoryDays] = useState("90")
  const [maxLoad, setMaxLoad] = useState("4")
  const [gap, setGap] = useState("2")
  const [nice, setNice] = useState("10")
  const [ionice, setIonice] = useState("7")
  const [allowRestore, setAllowRestore] = useState(true)
  const [restoreTimes, setRestoreTimes] = useState("0")
  const [restoreHours, setRestoreHours] = useState("24")
  const [spool, setSpool] = useState("")
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api<PanelStatus>("status")
      .then((status) => {
        setEmail(status.notify_email || "")
        setSummaryMail(status.summary_mail)
        setOwnerFail(Boolean(status.owner_fail_mail))
        setOwnerOk(Boolean(status.owner_ok_mail))
        setHistoryDays(String(status.history_days))
        setMaxLoad(String(status.max_load))
        setGap(String(status.account_gap))
        setNice(String(status.nice_level))
        setIonice(String(status.ionice_level))
        setAllowRestore(status.allow_user_restore)
        setRestoreTimes(String(status.restore_times))
        setRestoreHours(String(status.restore_hours))
        setSpool(status.spool)
      })
      .catch((error: Error) => onNotify(error.message, true))
  }, [onNotify])

  async function save() {
    setBusy(true)
    try {
      await api("settings.save", {
        notify_email: email,
        summary_mail: summaryMail,
        owner_fail_mail: ownerFail,
        owner_ok_mail: ownerOk,
        history_days: Number(historyDays),
        max_load: Number(maxLoad),
        account_gap: Number(gap),
        nice_level: Number(nice),
        ionice_level: Number(ionice),
        allow_user_restore: allowRestore,
        restore_times: Number(restoreTimes),
        restore_hours: Number(restoreHours),
      })
      onNotify("Ayarlar kaydedildi.")
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Kayıt başarısız", true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid max-w-3xl gap-4">
      <Tabs defaultValue="general">
        <TabsList className="flex h-auto flex-wrap justify-start">
          <TabsTrigger value="general">Genel</TabsTrigger>
          <TabsTrigger value="performance">Performans</TabsTrigger>
          <TabsTrigger value="resource">Kaynak</TabsTrigger>
          <TabsTrigger value="restore">Geri yükleme</TabsTrigger>
        </TabsList>

        <TabsContent value="general" className="grid gap-4 rounded-lg border bg-card p-4">
          <Field label="Bildirim e-postası" hint="Boşsa posta gitmez. Hata ve geri yükleme sonucu bu adrese yazılır.">
            <Input value={email} onChange={(event) => setEmail(event.target.value)} placeholder="root@sunucu" />
          </Field>
          <div className="flex items-center justify-between gap-4 rounded-md border px-3 py-2">
            <div>
              <p className="text-sm">Tur bitince özet posta</p>
              <p className="text-xs text-muted-foreground">Hesap hesap değil, çalıştırma bitince tek mektup: başarılı, hata, atlanan.</p>
            </div>
            <Switch checked={summaryMail} onCheckedChange={setSummaryMail} />
          </div>
          <div className="flex items-center justify-between gap-4 rounded-md border px-3 py-2">
            <div>
              <p className="text-sm">Hesap sahibine hata postası</p>
              <p className="text-xs text-muted-foreground">Kapalı başlar. Adres, cPanel kullanıcı dosyasındaki iletişim adresidir. Posta gitmezse yedek yine tamam sayılır.</p>
            </div>
            <Switch checked={ownerFail} onCheckedChange={setOwnerFail} />
          </div>
          <div className="flex items-center justify-between gap-4 rounded-md border px-3 py-2">
            <div>
              <p className="text-sm">Hesap sahibine başarı postası</p>
              <p className="text-xs text-muted-foreground">Kapalı başlar. Açılırsa her başarılı hesap için bir mektup gider.</p>
            </div>
            <Switch checked={ownerOk} onCheckedChange={setOwnerOk} />
          </div>
          <Field label="Panel geçmişi" hint="Bitmiş kayıtlar bu günden eskiyse listeden silinir. 0 tutar. FTP’deki yedek dosyasına dokunmaz. Süregelen tur silinmez.">
            <div className="flex items-center gap-2">
              <Input className="max-w-[8rem]" type="number" min={0} max={3650} value={historyDays} onChange={(event) => setHistoryDays(event.target.value)} />
              <span className="text-xs text-muted-foreground">gün</span>
            </div>
          </Field>
          <p className="text-xs text-muted-foreground">Geçici paketler {spool || "spool"} altında durur ve FTP’ye gidince silinir. Bu dizin sabit.</p>
        </TabsContent>

        <TabsContent value="performance" className="grid gap-4 rounded-lg border bg-card p-4">
          <p className="text-xs text-muted-foreground">Aynı anda tek hesap paketlenir. İkinci bir yedek süreci diski ve FTP’yi zorlamasın diye bu sabit.</p>
          <Field label="Yük sınırı" hint="1 dakikalık yük bu değerin üstündeyken sıradaki hesap bekler. Eldeki paket yarıda kesilmez.">
            <Input className="max-w-[8rem]" type="number" min={1} step="0.5" value={maxLoad} onChange={(event) => setMaxLoad(event.target.value)} />
          </Field>
          <Field label="Hesap arası bekleme" hint="Bir hesap bitince FTP’nin toparlanması için beklenecek süre. 0 kapatır.">
            <div className="flex items-center gap-2">
              <Input className="max-w-[8rem]" type="number" min={0} max={120} value={gap} onChange={(event) => setGap(event.target.value)} />
              <span className="text-xs text-muted-foreground">saniye</span>
            </div>
          </Field>
        </TabsContent>

        <TabsContent value="resource" className="grid gap-4 rounded-lg border bg-card p-4">
          <Field label="CPU önceliği" hint="0 en önde, 19 en geride. 10, site trafiğine yer bırakır. pkgacct bu değerle başlar.">
            <div className="flex items-center gap-2">
              <Input className="max-w-[8rem]" type="number" min={0} max={19} value={nice} onChange={(event) => setNice(event.target.value)} />
              <span className="text-xs text-muted-foreground">nice</span>
            </div>
          </Field>
          <Field label="Disk önceliği" hint="0 diski daha çok kullanır, 7 yedeği yavaşlatıp okuma yazmayı sitelere bırakır. Sınıf: best-effort.">
            <div className="flex items-center gap-2">
              <Input className="max-w-[8rem]" type="number" min={0} max={7} value={ionice} onChange={(event) => setIonice(event.target.value)} />
              <span className="text-xs text-muted-foreground">ionice</span>
            </div>
          </Field>
          <p className="text-xs text-muted-foreground">Bellek için ayrı bir tavan yok. Paket, hesabın kendi boyutu kadar geçici alan ister; alan yetmezse o hesap hata yazar, sıradaki sürer.</p>
        </TabsContent>

        <TabsContent value="restore" className="grid gap-4 rounded-lg border bg-card p-4">
          <div className="flex items-center justify-between gap-4 rounded-md border px-3 py-2">
            <div>
              <p className="text-sm">Kullanıcı kendi yedeğini geri yükleyebilir</p>
              <p className="text-xs text-muted-foreground">Kapalıyken cPanel’deki düğme gizlenir. WHM’den geri yükleme durur.</p>
            </div>
            <Switch checked={allowRestore} onCheckedChange={setAllowRestore} />
          </div>
          <Field label="Hesap başına geri yükleme sınırı" hint="0, sınır koymaz. Süre dolmadan bu adet aşılırsa yeni geri yükleme reddedilir.">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Input className="max-w-[6rem]" type="number" min={0} max={50} value={restoreTimes} onChange={(event) => setRestoreTimes(event.target.value)} />
              <span className="text-xs text-muted-foreground">kez /</span>
              <Input className="max-w-[6rem]" type="number" min={1} max={168} value={restoreHours} onChange={(event) => setRestoreHours(event.target.value)} />
              <span className="text-xs text-muted-foreground">saat</span>
            </div>
          </Field>
          <p className="text-xs text-muted-foreground">Geri yükleme her seferinde hesap adının yazılmasını ister. Üzerine yazma, o işlemde ayrıca açılır. Ev dizini kilitlenmez.</p>
        </TabsContent>
      </Tabs>
      <Button onClick={save} disabled={busy} className="w-fit border-transparent bg-[#ff6c2c] text-white hover:bg-[#e4561c]">Kaydet</Button>
    </div>
  )
}
