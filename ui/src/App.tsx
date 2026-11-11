import { useCallback, useEffect, useRef, useState } from "react"
import { ArrowLeft, CalendarClock, DatabaseBackup, History, LayoutDashboard, PanelLeftClose, PanelLeftOpen, RotateCcw, Settings as SettingsIcon, Users } from "lucide-react"
import { cn } from "@/lib/utils"
import { panelHome } from "@/lib/api"
import { Logo } from "@/components/logo"
import { Button } from "@/components/ui/button"
import { Accounts } from "@/pages/Accounts"
import { Dashboard } from "@/pages/Dashboard"
import { Destinations } from "@/pages/Destinations"
import { History as HistoryPage } from "@/pages/History"
import { Jobs } from "@/pages/Jobs"
import { Restore } from "@/pages/Restore"
import { Settings } from "@/pages/Settings"

type Page = "dashboard" | "accounts" | "restore" | "destinations" | "jobs" | "history" | "settings"

const nav: { id: Page; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "dashboard", label: "Özet", icon: LayoutDashboard },
  { id: "accounts", label: "Hesaplar", icon: Users },
  { id: "restore", label: "Geri yükle", icon: RotateCcw },
  { id: "destinations", label: "FTP hedefleri", icon: DatabaseBackup },
  { id: "jobs", label: "Görevler", icon: CalendarClock },
  { id: "history", label: "Geçmiş", icon: History },
  { id: "settings", label: "Ayarlar", icon: SettingsIcon },
]

function readCollapsed() {
  try {
    return localStorage.getItem("cpbackup-nav") === "icons"
  } catch {
    return false
  }
}

export default function App() {
  const [page, setPage] = useState<Page>("dashboard")
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [toast, setToast] = useState<{ text: string; error: boolean } | null>(null)
  const timer = useRef<number | null>(null)

  useEffect(() => {
    try {
      localStorage.setItem("cpbackup-nav", collapsed ? "icons" : "full")
    } catch {
      /* tarayıcı saklamayı kapattıysa menü yine çalışır */
    }
  }, [collapsed])

  const notify = useCallback((text: string, error = false) => {
    setToast({ text, error })
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setToast(null), 5000)
  }, [])

  return (
    <div className={cn("min-h-screen transition-[padding] duration-200", collapsed ? "md:pl-[4.5rem]" : "md:pl-60")}>
      <aside className={cn(
        "flex flex-col bg-slate-950 text-slate-100 transition-[width] duration-200 md:fixed md:inset-y-0 md:left-0 md:z-30",
        collapsed ? "md:w-[4.5rem]" : "md:w-60",
      )}>
        <div className={cn("flex items-center px-3 pt-3", collapsed ? "md:justify-center" : "justify-end")}>
          <button
            type="button"
            title={collapsed ? "Menüyü genişlet" : "Menüyü daralt"}
            onClick={() => setCollapsed((value) => !value)}
            className="hidden h-8 w-8 items-center justify-center rounded-md text-slate-300 hover:bg-white/10 hover:text-white md:flex"
          >
            {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </button>
        </div>
        <div className={cn("flex items-center gap-3 px-4 py-3", collapsed && "md:justify-center md:px-2")}>
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white">
            <Logo className="h-8 w-8" />
          </div>
          <div className={cn("min-w-0", collapsed && "md:hidden")}>
            <p className="text-sm font-semibold">cPBackup</p>
            <p className="text-xs text-slate-400">FTP hesap yedekleri</p>
          </div>
        </div>
        <nav className="flex min-h-0 flex-1 gap-1 overflow-auto px-3 pb-4 md:flex-col">
          {nav.map((item) => {
            const Icon = item.icon
            const active = page === item.id
            return (
              <button
                key={item.id}
                type="button"
                title={item.label}
                onClick={() => setPage(item.id)}
                className={cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-left text-sm",
                  collapsed && "md:justify-center md:px-2",
                  active ? "bg-white/10 text-white" : "text-slate-300 hover:bg-white/5",
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className={cn(collapsed && "md:sr-only")}>{item.label}</span>
              </button>
            )
          })}
        </nav>
        <div className={cn("px-3 py-4", collapsed && "md:px-2")}>
          <a
            href={panelHome()}
            title="WHM'e dön"
            className={cn(
              "flex h-8 items-center justify-center gap-2 rounded-md bg-[#ff6c2c] text-xs font-medium text-white hover:bg-[#e4561c]",
              collapsed ? "md:w-10" : "w-full",
            )}
          >
            <ArrowLeft className={cn("h-4 w-4", collapsed ? "hidden md:block" : "hidden")} />
            <span className={cn(collapsed && "md:sr-only")}>WHM'e dön</span>
          </a>
        </div>
      </aside>
      <main className="min-w-0 flex-1">
        <header className="flex items-center justify-between border-b bg-card px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold">{nav.find((item) => item.id === page)?.label}</h1>
            <p className="text-xs text-muted-foreground">WHM eklentisi · yalnızca root</p>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" className="border-transparent bg-[#ff6c2c] text-white hover:bg-[#e4561c] hover:text-white" asChild>
              <a href={panelHome()}>WHM'e dön</a>
            </Button>
            <Button variant="outline" size="sm" onClick={() => setPage("jobs")}>Yedek görevi</Button>
          </div>
        </header>
        <section className="p-6">
          {page === "dashboard" ? <Dashboard onError={(message) => notify(message, true)} /> : null}
          {page === "accounts" ? <Accounts onNotify={notify} /> : null}
          {page === "restore" ? <Restore onNotify={notify} /> : null}
          {page === "destinations" ? <Destinations onNotify={notify} /> : null}
          {page === "jobs" ? <Jobs onNotify={notify} /> : null}
          {page === "history" ? <HistoryPage onNotify={notify} /> : null}
          {page === "settings" ? <Settings onNotify={notify} /> : null}
        </section>
      </main>
      {toast ? (
        <div className={cn(
          "fixed bottom-4 right-4 z-50 max-w-sm rounded-lg border px-4 py-3 text-sm shadow-lg",
          toast.error ? "border-red-200 bg-red-50 text-red-800" : "border-emerald-200 bg-emerald-50 text-emerald-900",
        )}>
          {toast.text}
        </div>
      ) : null}
    </div>
  )
}
