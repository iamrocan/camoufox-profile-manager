'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  Ellipsis,
  Eraser,
  Globe,
  PackageOpen,
  Pause,
  Pencil,
  Play,
  Plus,
  House,
  Search,
  Shield,
  ShieldOff,
  Square,
  Trash2,
  Upload,
  Users,
} from 'lucide-react'

import { EmptyState } from '@/components/empty-state'
import { ConfirmDialog, Modal, PromptDialog } from '@/components/modal'
import { ProfileForm } from '@/components/profile-form'
import { useToast } from '@/components/toast'
import { useT, type MessageKey } from '@/lib/i18n'
import {
  browsersAPI,
  formatLastUsed,
  formatProxyString,
  groupsAPI,
  hasGeography,
  OS_LABELS,
  profilesAPI,
  readProxyCheck,
  type Group,
  type Profile,
  type ProxyCheckRecord,
} from '@/lib/api'

type SortKey = 'name' | 'id' | 'group' | 'os' | 'status' | 'last_used'

const COLUMNS: { key: SortKey; label: MessageKey; className?: string }[] = [
  { key: 'name', label: 'col.name' },
  { key: 'id', label: 'col.id' },
  { key: 'group', label: 'col.group' },
  { key: 'os', label: 'col.os' },
  { key: 'status', label: 'col.status' },
  { key: 'last_used', label: 'col.lastUsed' },
]

export default function ProfilesPage() {
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [groups, setGroups] = useState<Group[]>([])
  const [running, setRunning] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [sortKey, setSortKey] = useState<SortKey>('name')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [page, setPage] = useState(1)
  const perPage = 25

  const [checkingProxies, setCheckingProxies] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [menuFor, setMenuFor] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Profile | null>(null)
  const [confirm, setConfirm] = useState<null | {
    title: string
    body: string
    label: string
    // Says outright whether the action destroys something, rather than being
    // inferred by comparing the label against "Delete" — which stopped being
    // true the moment the label could be translated.
    destructive?: boolean
    run: () => Promise<void>
  }>(null)
  const [startupFor, setStartupFor] = useState<Profile | null>(null)
  const [savingStartup, setSavingStartup] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)

  const toast = useToast()
  const t = useT()
  const importRef = useRef<HTMLInputElement>(null)
  const archiveRef = useRef<HTMLInputElement>(null)

  const loadProfiles = useCallback(async () => {
    try {
      setError(null)
      // The API paginates; pull every page so sorting and search stay client-side
      // and instant. Guarded so a bad has_next can never spin forever.
      const collected: Profile[] = []
      for (let pageNumber = 1; pageNumber <= 200; pageNumber += 1) {
        const response = await profilesAPI.getProfiles({ page: pageNumber, per_page: 100 })
        collected.push(...response.profiles)
        if (!response.has_next) break
      }
      setProfiles(collected)
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err))
    } finally {
      setLoading(false)
    }
  }, [])

  const loadRunning = useCallback(async () => {
    try {
      const response = await browsersAPI.active()
      setRunning(new Set(response.active_browsers.map((browser) => browser.profile_id)))
    } catch {
      // The poll is best-effort; a transient failure must not surface as an error.
    }
  }, [])

  const loadGroups = useCallback(async () => {
    try {
      const response = await groupsAPI.list()
      setGroups(response.groups)
    } catch {
      // Groups are optional context for the table and the form.
    }
  }, [])

  useEffect(() => {
    // loadProfiles clears the previous error synchronously before awaiting,
    // which is the one render the rule objects to and is what makes a reload
    // stop showing a stale failure.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadProfiles()
    loadGroups()
    loadRunning()
    const timer = setInterval(loadRunning, 5000)
    return () => clearInterval(timer)
  }, [loadProfiles, loadGroups, loadRunning])

  useEffect(() => {
    // Close on any click that is not on a trigger or inside an open menu.
    // Relying on stopPropagation in the trigger's React handler is not enough:
    // React delegates to its root container, so the document listener could
    // still fire and shut the menu in the same click that opened it.
    const close = (event: MouseEvent) => {
      const target = event.target as Element | null
      if (target?.closest('[data-menu-trigger], [role="menu"]')) return
      setMenuFor(null)
    }
    document.addEventListener('click', close)
    return () => document.removeEventListener('click', close)
  }, [])

  // Go back to the first page when the filters change. Adjusted during render
  // rather than in an effect: an effect would paint the new results clamped to
  // whatever page number survived, then snap to the first one, and React
  // documents this as the way to derive state from a change in props or state.
  const [filterForPage, setFilterForPage] = useState(() => ({ search, statusFilter }))
  if (filterForPage.search !== search || filterForPage.statusFilter !== statusFilter) {
    setFilterForPage({ search, statusFilter })
    setPage(1)
  }

  const groupNames = useMemo(
    () => new Map(groups.map((group) => [group.id, group.name])),
    [groups],
  )

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const filtered = profiles.filter((profile) => {
      if (statusFilter !== 'all' && profile.status !== statusFilter) return false
      if (!needle) return true
      return (
        profile.name.toLowerCase().includes(needle) || profile.id.toLowerCase().includes(needle)
      )
    })

    const direction = sortDir === 'asc' ? 1 : -1
    return [...filtered].sort((a, b) => {
      switch (sortKey) {
        case 'id':
          return a.id.localeCompare(b.id) * direction
        case 'group':
          return (groupNames.get(a.group ?? '') ?? '').localeCompare(
            groupNames.get(b.group ?? '') ?? '',
          ) * direction
        case 'os':
          return (a.browser_settings?.os ?? '').localeCompare(b.browser_settings?.os ?? '') * direction
        case 'status':
          return a.status.localeCompare(b.status) * direction
        case 'last_used':
          return (
            (new Date(a.last_used ?? 0).getTime() - new Date(b.last_used ?? 0).getTime()) * direction
          )
        default:
          return a.name.localeCompare(b.name) * direction
      }
    })
  }, [profiles, search, statusFilter, sortKey, sortDir, groupNames])

  // Offering the bulk clear when nothing selected would change is just noise.
  const selectedWithGeography = useMemo(
    () => profiles.filter((profile) => selected.has(profile.id) && hasGeography(profile)).length,
    [profiles, selected],
  )

  // Same rule as the clear above: a profile with no proxy has nothing to check.
  const selectedWithProxy = useMemo(
    () => profiles.filter((profile) => selected.has(profile.id) && profile.proxy_config).length,
    [profiles, selected],
  )

  const totalPages = Math.max(1, Math.ceil(visible.length / perPage))
  // Deleting the last rows of a page must not strand the user on an empty one.
  const currentPage = Math.min(page, totalPages)
  const pageRows = visible.slice((currentPage - 1) * perPage, currentPage * perPage)
  const allOnPageSelected = pageRows.length > 0 && pageRows.every((row) => selected.has(row.id))

  /** Close the row menu and hand focus back to the button that opened it.
   *
   * Focus moves first: removing the menu while one of its items still has focus
   * drops focus to <body>, and a refocus queued after the close races that reset.
   */
  function closeMenu(profileId: string) {
    document.querySelector<HTMLButtonElement>(`[data-menu-trigger="${profileId}"]`)?.focus()
    setMenuFor(null)
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  async function withBusy(id: string, action: () => Promise<void>) {
    setBusy((current) => new Set(current).add(id))
    try {
      await action()
    } finally {
      setBusy((current) => {
        const next = new Set(current)
        next.delete(id)
        return next
      })
    }
  }

  async function launch(profile: Profile) {
    await withBusy(profile.id, async () => {
      try {
        await profilesAPI.startProfile(profile.id)
        await Promise.all([loadRunning(), loadProfiles()])
      } catch (err) {
        toast('error', t('toast.launchFailed'), String(err))
      }
    })
  }

  async function stop(profile: Profile) {
    await withBusy(profile.id, async () => {
      try {
        await profilesAPI.closeProfile(profile.id)
        await loadRunning()
      } catch (err) {
        toast('error', t('toast.closeFailed'), String(err))
      }
    })
  }

  function download(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  }

  async function exportArchive(profile: Profile) {
    toast('info', t('toast.packing'), t('toast.packingBody'))
    try {
      const blob = await profilesAPI.exportArchive(profile.id)
      const safe = profile.name.replace(/[^A-Za-z0-9_.-]+/g, '-').replace(/^-|-$/g, '')
      download(blob, `${safe || profile.id}.camoufox.zip`)
      toast('ok', t('toast.exported'), t('toast.exportedBody'))
    } catch (err) {
      toast('error', t('toast.exportFailed'), String(err))
    }
  }

  async function importArchive(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    try {
      const profile = await profilesAPI.importArchive(file)
      toast('ok', t('toast.imported'), profile.name)
      loadProfiles()
    } catch (err) {
      toast('error', t('toast.importFailed'), String(err))
    }
  }

  async function clone(profile: Profile) {
    try {
      await profilesAPI.cloneProfile(profile.id, `${profile.name} copy`)
      toast('ok', t('toast.cloned'), `${profile.name} copy`)
      loadProfiles()
    } catch (err) {
      toast('error', t('toast.cloneFailed'), String(err))
    }
  }

  /**
   * Check one proxy and leave the answer in its row.
   *
   * The row is the report, not a toast: a toast is gone in four seconds, and the
   * question this answers — is this proxy alive, and does it agree with the
   * profile — is one the list should keep showing. Only a failure to reach *our
   * own API* is worth interrupting for, because then no row can say anything.
   */
  async function checkProxy(profile: Profile): Promise<ProxyCheckRecord | null> {
    setCheckingProxies((current) => new Set(current).add(profile.id))
    try {
      const result = await profilesAPI.checkProxy(profile.id)
      const record: ProxyCheckRecord = {
        checked_at: result.checked_at ?? new Date().toISOString(),
        reachable: result.reachable,
        error: result.error,
        latency_ms: result.latency_ms,
        ip: result.location?.ip ?? null,
        country: result.location?.country ?? null,
        timezone: result.location?.timezone ?? null,
        findings: result.findings,
      }
      setProfiles((current) =>
        current.map((row) => (row.id === profile.id ? { ...row, proxy_check: record } : row)),
      )
      return record
    } catch (err) {
      toast('error', t('toast.checkFailed'), String(err))
      return null
    } finally {
      setCheckingProxies((current) => {
        const next = new Set(current)
        next.delete(profile.id)
        return next
      })
    }
  }

  /**
   * Check every selected profile that has a proxy.
   *
   * A few at a time: a hundred proxies opened at once is a hundred sockets and a
   * self-inflicted timeout, and rows landing one by one reads as progress where
   * a single wait reads as a hang.
   */
  async function checkSelectedProxies() {
    const queue = profiles.filter((profile) => selected.has(profile.id) && profile.proxy_config)
    if (!queue.length) return

    // Counted before the workers start draining the queue.
    const total = queue.length
    // Three outcomes, not two: a check that never reached our own API left its
    // row untouched, and reporting that as success is how a summary ends up
    // contradicting the table it summarises.
    let clean = 0
    let flagged = 0
    let unchecked = 0
    const workers = Array.from({ length: Math.min(5, total) }, async () => {
      for (let next = queue.shift(); next; next = queue.shift()) {
        const record = await checkProxy(next)
        if (!record) unchecked += 1
        else if (readProxyCheck(record, t).tone === 'ok') clean += 1
        else flagged += 1
      }
    })
    await Promise.all(workers)

    // Worded from the same rule the dots use, so a red row is never counted as
    // an answer just because the proxy replied.
    const parts = [
      flagged ? `${flagged} need attention` : null,
      unchecked ? `${unchecked} could not be checked` : null,
    ].filter(Boolean)

    if (parts.length)
      toast('error', parts.join(', '), `of ${total} selected. The rows carry the detail.`)
    else toast('ok', `${clean} ${clean === 1 ? 'proxy is' : 'proxies are'} healthy`)
  }

  function askDelete(profile: Profile) {
    setConfirm({
      title: t('delete.title'),
      body: t('delete.body', { name: profile.name }),
      label: t('action.delete'),
      destructive: true,
      run: async () => {
        await profilesAPI.deleteProfile(profile.id)
        toast('ok', t('delete.done'), profile.name)
        setSelected((current) => {
          const next = new Set(current)
          next.delete(profile.id)
          return next
        })
        loadProfiles()
      },
    })
  }

  async function toggleProxyPaused(profile: Profile) {
    try {
      const updated = await profilesAPI.toggleProxyPaused(profile.id)
      toast(
        'ok',
        t(updated.proxy_paused ? 'proxy.pausedTitle' : 'proxy.resumedTitle'),
        t(updated.proxy_paused ? 'proxy.pausedBody' : 'proxy.resumedBody', {
          name: profile.name,
        }),
      )
      loadProfiles()
    } catch (err) {
      toast('error', t('proxy.toggleFailed'), String(err))
    }
  }

  async function toggleUblock(profile: Profile) {
    try {
      const updated = await profilesAPI.toggleUblock(profile.id)
      toast(
        'ok',
        t(updated.ublock_disabled ? 'ublock.disabledTitle' : 'ublock.enabledTitle'),
        t(updated.ublock_disabled ? 'ublock.disabledBody' : 'ublock.enabledBody', {
          name: profile.name,
        }),
      )
      loadProfiles()
    } catch (err) {
      toast('error', t('ublock.toggleFailed'), String(err))
    }
  }

  async function saveStartupUrl(value: string) {
    if (!startupFor) return
    const profile = startupFor
    setSavingStartup(true)
    try {
      const updated = await profilesAPI.setStartupUrl(profile.id, value || null)
      toast(
        'ok',
        t(updated.startup_url ? 'startup.savedTitle' : 'startup.clearedTitle'),
        updated.startup_url
          ? t('startup.savedBody', { url: updated.startup_url })
          : t('startup.clearedBody', { name: profile.name }),
      )
      setStartupFor(null)
      loadProfiles()
    } catch (err) {
      // The dialog stays open: the URL was refused, and closing it would throw
      // away what the user typed along with the chance to correct it.
      toast('error', t('startup.failed'), String(err))
    } finally {
      setSavingStartup(false)
    }
  }

  function askClearData(profile: Profile) {
    setConfirm({
      title: t('clear.title'),
      body: t('clear.body', { name: profile.name }),
      label: t('clear.confirm'),
      run: async () => {
        try {
          const result = await profilesAPI.clearData(profile.id)
          const mb = (result.bytes_removed / 1_048_576).toFixed(1)
          toast(
            'ok',
            t('clear.doneTitle', { name: profile.name }),
            t('clear.doneBody', { files: result.files_removed, mb }),
          )
          loadProfiles()
        } catch (err) {
          toast('error', t('clear.failed'), String(err))
        }
      },
    })
  }

  function askBulkDelete() {
    const count = selected.size
    setConfirm({
      title: t('bulk.deleteTitle', { count }),
      body: t('bulk.deleteBody'),
      label: t('action.delete'),
      destructive: true,
      run: async () => {
        for (const id of selected) await profilesAPI.deleteProfile(id)
        toast('ok', t('bulk.deleteDone', { count }))
        setSelected(new Set())
        loadProfiles()
      },
    })
  }

  /**
   * The profiles this exists for were all created the same way — with the
   * timezone and coordinates of a randomly chosen region — so the useful unit is
   * a selection, not one profile at a time. Only those that actually state a
   * location are named, so the confirmation says what will really change.
   */
  function askClearGeography() {
    const ids = profiles.filter((p) => selected.has(p.id) && hasGeography(p)).map((p) => p.id)
    setConfirm({
      title: t('bulk.geoTitle', { count: ids.length }),
      body: t('bulk.geoBody'),
      label: t('bulk.geoConfirm'),
      run: async () => {
        const result = await profilesAPI.clearGeography(ids)
        toast('ok', t('bulk.geoDone', { count: result.cleared.length }))
        setSelected(new Set())
        loadProfiles()
      },
    })
  }

  function askCloseAll() {
    setConfirm({
      title: t('bulk.closeAllTitle'),
      body: t('bulk.closeAllBody', { count: running.size }),
      label: t('bulk.closeAllConfirm'),
      run: async () => {
        const result = await browsersAPI.closeAll()
        toast('ok', result.message)
        loadRunning()
      },
    })
  }

  async function runConfirmed() {
    if (!confirm) return
    const action = confirm
    setConfirm(null)
    try {
      await action.run()
    } catch (err) {
      toast('error', 'Action failed', String(err))
    }
  }

  async function exportExcel() {
    setExportOpen(false)
    try {
      const blob = await profilesAPI.exportExcel()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'camoufox-profiles.xlsx'
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      toast('ok', t('excel.exported'), t('excel.exportedBody'))
    } catch (err) {
      toast('error', t('excel.exportFailed'), String(err))
    }
  }

  async function importExcel(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    try {
      const result = await profilesAPI.importExcel(file)
      if (result.success) {
        toast('ok', t('excel.imported', { count: result.data?.created_count ?? 0 }))
        loadProfiles()
      } else {
        toast(
          'error',
          t('excel.importErrors'),
          (result.data?.errors ?? []).slice(0, 3).join('\n') || result.message,
        )
      }
    } catch (err) {
      toast('error', t('excel.importFailed'), String(err))
    }
  }

  return (
    <>
      <header className="sticky top-0 z-20 flex h-[52px] items-center gap-3 border-b border-line bg-canvas/85 px-5 backdrop-blur">
        <h1 className="text-[14px] font-semibold">{t('profiles.title')}</h1>
        <span className="font-mono text-ink-faint">{visible.length}</span>

        <div className="relative ml-3 w-[240px]">
          <Search
            size={13}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint"
          />
          <input
            className="field h-[30px] pl-7"
            placeholder={t('profiles.search')}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            aria-label={t('profiles.searchLabel')}
          />
        </div>

        <select
          // Wide enough for the longest translated label ("Todos los estados"),
          // not just the English one. Fixed rather than min-width: this sits in
          // a flex row, where a min-width with no width grows to fill and pushes
          // the toolbar buttons off the edge.
          className="field h-[30px] w-[168px] shrink-0"
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
          aria-label={t('profiles.filterByStatus')}
        >
          <option value="all">{t('profiles.allStatuses')}</option>
          <option value="active">{t('statusOpt.active')}</option>
          <option value="inactive">{t('statusOpt.inactive')}</option>
          <option value="blocked">{t('statusOpt.blocked')}</option>
          <option value="maintenance">{t('statusOpt.maintenance')}</option>
        </select>

        <div className="ml-auto flex items-center gap-2">
          {running.size > 0 && (
            <button className="btn btn-default" onClick={askCloseAll}>
              <Square size={12} fill="currentColor" />
              Close {running.size} running
            </button>
          )}
          <button className="btn btn-ghost" onClick={() => setExportOpen(true)} title={t('profiles.exportExcel')}>
            <Download size={14} />
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => importRef.current?.click()}
            title={t('profiles.importExcel')}
          >
            <Upload size={14} />
          </button>
          <input
            ref={importRef}
            type="file"
            accept=".xlsx,.xls"
            onChange={importExcel}
            className="hidden"
          />
          <button
            className="btn btn-ghost"
            onClick={() => archiveRef.current?.click()}
            title={t('profiles.importArchive')}
          >
            <PackageOpen size={14} />
          </button>
          <input
            ref={archiveRef}
            type="file"
            accept=".zip"
            onChange={importArchive}
            className="hidden"
          />
          <button
            className="btn btn-primary"
            onClick={() => {
              setEditing(null)
              setFormOpen(true)
            }}
          >
            <Plus size={14} strokeWidth={2.5} />
            {t('profiles.new')}
          </button>
        </div>
      </header>

      {selected.size > 0 && (
        <div className="flex items-center gap-3 border-b border-line bg-raised px-5 py-2">
          <span>{t('bulk.selected', { count: selected.size })}</span>
          {selectedWithProxy > 0 && (
            <button
              className="btn btn-default h-7"
              disabled={checkingProxies.size > 0}
              onClick={checkSelectedProxies}
            >
              <Globe size={13} />
              {checkingProxies.size > 0
                ? t('bulk.checking', { count: checkingProxies.size })
                : t('bulk.checkProxies', { count: selectedWithProxy })}
            </button>
          )}
          {selectedWithGeography > 0 && (
            <button className="btn btn-default h-7" onClick={askClearGeography}>
              <Globe size={13} />
              {t('bulk.clearGeography', { count: selectedWithGeography })}
            </button>
          )}
          <button className="btn btn-danger h-7" onClick={askBulkDelete}>
            <Trash2 size={13} />
            {t('action.delete')}
          </button>
          <button className="btn btn-ghost h-7" onClick={() => setSelected(new Set())}>
            {t('bulk.clearSelection')}
          </button>
        </div>
      )}

      {error ? (
        <EmptyState
          icon={<Users size={18} />}
          title={t('empty.apiTitle')}
          body={error}
          action={
            <button className="btn btn-default" onClick={loadProfiles}>
              {t('empty.retry')}
            </button>
          }
        />
      ) : loading ? (
        <p className="px-5 py-8 text-ink-faint">{t('profiles.loading')}</p>
      ) : profiles.length === 0 ? (
        <EmptyState
          icon={<Users size={18} />}
          title={t('empty.noneTitle')}
          body={t('empty.noneBody')}
          action={
            <button
              className="btn btn-primary"
              onClick={() => {
                setEditing(null)
                setFormOpen(true)
              }}
            >
              <Plus size={14} strokeWidth={2.5} />
              {t('empty.createFirst')}
            </button>
          }
        />
      ) : visible.length === 0 ? (
        <EmptyState
          icon={<Search size={18} />}
          title={t('empty.noMatchTitle')}
          body={t('empty.noMatchBody')}
          action={
            <button
              className="btn btn-default"
              onClick={() => {
                setSearch('')
                setStatusFilter('all')
              }}
            >
              {t('empty.clearFilters')}
            </button>
          }
        />
      ) : (
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-line text-left text-[11px] uppercase tracking-[0.05em] text-ink-faint">
              <th className="w-9 py-2 pl-5">
                <input
                  type="checkbox"
                  className="accent-signal"
                  checked={allOnPageSelected}
                  aria-label={t('profiles.selectAll')}
                  onChange={() =>
                    setSelected((current) => {
                      const next = new Set(current)
                      pageRows.forEach((row) =>
                        allOnPageSelected ? next.delete(row.id) : next.add(row.id),
                      )
                      return next
                    })
                  }
                />
              </th>
              {COLUMNS.map((column) => (
                <th key={column.key} className="py-2 pr-4 font-medium">
                  <button
                    className="inline-flex items-center gap-1 hover:text-ink"
                    onClick={() => toggleSort(column.key)}
                  >
                    {t(column.label)}
                    {sortKey === column.key &&
                      (sortDir === 'asc' ? <ArrowUp size={11} /> : <ArrowDown size={11} />)}
                  </button>
                </th>
              ))}
              <th className="py-2 pr-4 font-medium">{t('col.proxy')}</th>
              <th className="w-[104px] py-2 pr-5" />
            </tr>
          </thead>
          <tbody>
            {pageRows.map((profile, index) => {
              const isRunning = running.has(profile.id)
              const isBusy = busy.has(profile.id)
              return (
                <tr
                  key={profile.id}
                  className="row-in group border-b border-line/60 hover:bg-surface"
                  style={{ animationDelay: `${Math.min(index, 12) * 12}ms` }}
                >
                  <td className="relative py-2.5 pl-5">
                    {/* Hairline marker: a running profile is visible at a glance. */}
                    {isRunning && (
                      <span className="absolute left-0 top-0 h-full w-[2px] bg-signal" aria-hidden />
                    )}
                    <input
                      type="checkbox"
                      className="accent-signal"
                      checked={selected.has(profile.id)}
                      aria-label={`Select ${profile.name}`}
                      onChange={() =>
                        setSelected((current) => {
                          const next = new Set(current)
                          if (next.has(profile.id)) next.delete(profile.id)
                          else next.add(profile.id)
                          return next
                        })
                      }
                    />
                  </td>

                  <td className="py-2.5 pr-4 font-medium">{profile.name}</td>
                  <td className="py-2.5 pr-4 font-mono text-ink-faint">{profile.id}</td>
                  <td className="py-2.5 pr-4 text-ink-dim">
                    {profile.group ? (groupNames.get(profile.group) ?? profile.group) : '—'}
                  </td>
                  <td className="py-2.5 pr-4 text-ink-dim">
                    {OS_LABELS[profile.browser_settings?.os ?? ''] ?? profile.browser_settings?.os}
                  </td>
                  <td className="py-2.5 pr-4">
                    <StatusCell status={profile.status} running={isRunning} />
                  </td>
                  <td className="py-2.5 pr-4 text-ink-dim">{formatLastUsed(profile.last_used, t)}</td>
                  <td className="py-2.5 pr-4">
                    <ProxyCell
                      profile={profile}
                      checking={checkingProxies.has(profile.id)}
                    />
                  </td>

                  <td className="py-2.5 pr-5">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        className="btn btn-default h-7"
                        disabled={isBusy}
                        onClick={() => (isRunning ? stop(profile) : launch(profile))}
                      >
                        {isRunning ? (
                          <>
                            <Square size={11} fill="currentColor" />
                            {t('action.stop')}
                          </>
                        ) : (
                          <>
                            <Play size={11} fill="currentColor" />
                            {t('action.run')}
                          </>
                        )}
                      </button>

                      <div className="relative">
                        <button
                          className="btn btn-ghost h-7 w-7 p-0"
                          aria-label={t('profiles.actionsFor', { name: profile.name })}
                          aria-haspopup="menu"
                          aria-expanded={menuFor === profile.id}
                          data-menu-trigger={profile.id}
                          onClick={(event) => {
                            event.stopPropagation()
                            setMenuFor(menuFor === profile.id ? null : profile.id)
                          }}
                        >
                          <Ellipsis size={15} />
                        </button>

                        {menuFor === profile.id && (
                          <div
                            role="menu"
                            className="dialog-in absolute right-0 top-8 z-30 w-[164px] overflow-hidden rounded-md border border-line bg-raised py-1 shadow-xl shadow-black/50"
                            onClick={(event) => event.stopPropagation()}
                            onKeyDown={(event) => {
                              const items = Array.from(
                                event.currentTarget.querySelectorAll<HTMLButtonElement>(
                                  '[role="menuitem"]',
                                ),
                              )
                              const index = items.indexOf(document.activeElement as HTMLButtonElement)
                              if (event.key === 'Escape') {
                                event.stopPropagation()
                                closeMenu(profile.id)
                              } else if (event.key === 'ArrowDown') {
                                event.preventDefault()
                                items[(index + 1) % items.length]?.focus()
                              } else if (event.key === 'ArrowUp') {
                                event.preventDefault()
                                items[(index - 1 + items.length) % items.length]?.focus()
                              }
                            }}
                          >
                            <MenuItem
                              icon={<Pencil size={13} />}
                              label={t('action.edit')}
                              autoFocus
                              onClick={() => {
                                setEditing(profile)
                                setFormOpen(true)
                                closeMenu(profile.id)
                              }}
                            />
                            <MenuItem
                              icon={<Copy size={13} />}
                              label={t('action.duplicate')}
                              onClick={() => {
                                clone(profile)
                                closeMenu(profile.id)
                              }}
                            />
                            <MenuItem
                              icon={<Globe size={13} />}
                              label={t('action.checkProxy')}
                              onClick={() => {
                                // The set holds ids, not a count, so a second
                                // check of the same row would clear the first
                                // one's "Checking…" when it finished.
                                if (!checkingProxies.has(profile.id)) checkProxy(profile)
                                closeMenu(profile.id)
                              }}
                            />
                            {profile.proxy_config ? (
                              <MenuItem
                                icon={profile.proxy_paused ? <Play size={13} /> : <Pause size={13} />}
                                label={t(
                                  profile.proxy_paused
                                    ? 'action.resumeProxy'
                                    : 'action.pauseProxy',
                                )}
                                onClick={() => {
                                  toggleProxyPaused(profile)
                                  closeMenu(profile.id)
                                }}
                              />
                            ) : null}
                            <MenuItem
                              icon={
                                profile.ublock_disabled ? (
                                  <Shield size={13} />
                                ) : (
                                  <ShieldOff size={13} />
                                )
                              }
                              label={t(
                                profile.ublock_disabled
                                  ? 'action.enableUblock'
                                  : 'action.disableUblock',
                              )}
                              onClick={() => {
                                toggleUblock(profile)
                                closeMenu(profile.id)
                              }}
                            />
                            <MenuItem
                              icon={<House size={13} />}
                              label={t(
                                profile.startup_url
                                  ? 'action.changeStartupUrl'
                                  : 'action.setStartupUrl',
                              )}
                              onClick={() => {
                                setStartupFor(profile)
                                closeMenu(profile.id)
                              }}
                            />
                            <MenuItem
                              icon={<PackageOpen size={13} />}
                              label={t('action.export')}
                              onClick={() => {
                                exportArchive(profile)
                                closeMenu(profile.id)
                              }}
                            />
                            <MenuItem
                              icon={<Eraser size={13} />}
                              label={t('action.clearData')}
                              onClick={() => {
                                askClearData(profile)
                                closeMenu(profile.id)
                              }}
                            />
                            <MenuItem
                              icon={<Trash2 size={13} />}
                              label={t('action.delete')}
                              danger
                              onClick={() => {
                                askDelete(profile)
                                closeMenu(profile.id)
                              }}
                            />
                          </div>
                        )}
                      </div>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-between px-5 py-3 text-ink-dim">
          <span>
            {t('page.range', {
              from: (currentPage - 1) * perPage + 1,
              to: Math.min(currentPage * perPage, visible.length),
              total: visible.length,
            })}
          </span>
          <div className="flex items-center gap-1">
            <button
              className="btn btn-ghost h-7 w-7 p-0"
              disabled={currentPage === 1}
              onClick={() => setPage(currentPage - 1)}
              aria-label={t('page.previous')}
            >
              <ChevronLeft size={15} />
            </button>
            <span className="px-2 font-mono">
              {currentPage} / {totalPages}
            </span>
            <button
              className="btn btn-ghost h-7 w-7 p-0"
              disabled={currentPage === totalPages}
              onClick={() => setPage(currentPage + 1)}
              aria-label={t('page.next')}
            >
              <ChevronRight size={15} />
            </button>
          </div>
        </div>
      )}

      <ProfileForm
        open={formOpen}
        profile={editing}
        groups={groups}
        onClose={() => setFormOpen(false)}
        onSaved={loadProfiles}
      />

      <PromptDialog
        open={startupFor !== null}
        title={t('startup.title')}
        body={t('startup.hint')}
        label={t('startup.label')}
        placeholder="https://open.spotify.com"
        initialValue={startupFor?.startup_url ?? ''}
        confirmLabel={t('startup.save')}
        busy={savingStartup}
        onSubmit={saveStartupUrl}
        onCancel={() => setStartupFor(null)}
      />

      <ConfirmDialog
        open={confirm !== null}
        title={confirm?.title ?? ''}
        body={confirm?.body ?? ''}
        confirmLabel={confirm?.label}
        destructive={confirm?.destructive ?? false}
        onConfirm={runConfirmed}
        onCancel={() => setConfirm(null)}
      />

      <Modal
        open={exportOpen}
        title={t('excel.title')}
        onClose={() => setExportOpen(false)}
        width={440}
        footer={
          <>
            <button className="btn btn-default" onClick={() => setExportOpen(false)}>
              {t('action.cancel')}
            </button>
            <button className="btn btn-primary" onClick={exportExcel}>
              {t('excel.confirm')}
            </button>
          </>
        }
      >
        <p className="text-ink-dim">
          {t('excel.warningBefore')}
          <span className="text-ink">{t('excel.warningEmphasis')}</span>
          {t('excel.warningAfter')}
        </p>
      </Modal>
    </>
  )
}

/** The configured proxy, and under it the last answer it gave.
 *
 * Two lines rather than a column of its own: the table is already wide, and the
 * second line only exists once there is something to say, so a list nobody has
 * checked looks exactly as it did before.
 */
function ProxyCell({ profile, checking }: { profile: Profile; checking: boolean }) {
  const t = useT()
  const configured = formatProxyString(profile.proxy_config) || '—'
  const check = profile.proxy_check
  const paused = Boolean(profile.proxy_config && profile.proxy_paused)

  return (
    // Bounded, because a table cell grows to fit its content: an unreachable
    // proxy reports a whole sentence, and without a cap one dead proxy pushed
    // the row actions off the screen and gave the table a scrollbar.
    <div className="max-w-[280px] leading-tight">
      <div className="flex items-center gap-1.5">
        <span className={`truncate font-mono ${paused ? 'text-ink-faint/50 line-through' : 'text-ink-faint'}`}>
          {configured}
        </span>
        {paused ? (
          <span
            className="shrink-0 rounded-full border border-warn/40 bg-warn/10 px-1.5 py-[1px] text-[10px] font-medium uppercase tracking-wide text-warn"
            title={t('proxy.pausedHint')}
          >
            {t('status.paused')}
          </span>
        ) : null}
      </div>
      {checking ? (
        <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-ink-faint">
          <span className="signal-pulse h-1.5 w-1.5 rounded-full bg-signal" />
          {t('status.checking')}
        </div>
      ) : check ? (
        <ProxyResult check={check} />
      ) : null}
    </div>
  )
}

function ProxyResult({ check }: { check: ProxyCheckRecord }) {
  const t = useT()
  const { tone, label, detail } = readProxyCheck(check, t)
  const dot = tone === 'ok' ? 'bg-ok' : tone === 'warn' ? 'bg-warn' : 'bg-danger'
  // Latency and country only mean something when the proxy answered; when it did
  // not, the reason is the only thing worth the space.
  const parts = check.reachable
    ? [check.ip, check.country, check.latency_ms !== null ? `${check.latency_ms} ms` : null]
    : [check.error]

  return (
    <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-ink-faint" title={detail}>
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
      <span className="sr-only">{label}.</span>
      {/* min-w-0 so this is the part that gives way: a flex item will not shrink
          below its content without it, and the truncation never happens. */}
      <span className="min-w-0 truncate font-mono">{parts.filter(Boolean).join(' · ')}</span>
      <span className="shrink-0 text-ink-dim/70">· {formatLastUsed(check.checked_at, t)}</span>
    </div>
  )
}

const STATUS_KEYS: Record<string, MessageKey> = {
  active: 'statusOpt.active',
  inactive: 'statusOpt.inactive',
  blocked: 'statusOpt.blocked',
  maintenance: 'statusOpt.maintenance',
}

function StatusCell({ status, running }: { status: string; running: boolean }) {
  const t = useT()
  if (running) {
    return (
      <span className="inline-flex items-center gap-1.5 text-signal">
        <span className="signal-pulse h-1.5 w-1.5 rounded-full bg-signal" />
        {t('status.running')}
      </span>
    )
  }
  const tone =
    status === 'blocked' ? 'bg-danger' : status === 'maintenance' ? 'bg-ink-dim' : 'bg-ink-faint'
  const key = STATUS_KEYS[status]
  return (
    // No capitalize: the translations are already written with the casing
    // they should have, and the class would also fight languages that do not
    // capitalise the way English does.
    <span className="inline-flex items-center gap-1.5 text-ink-dim">
      <span className={`h-1.5 w-1.5 rounded-full ${tone}`} />
      {key ? t(key) : status}
    </span>
  )
}

function MenuItem({
  icon,
  label,
  onClick,
  danger,
  autoFocus,
}: {
  icon: React.ReactNode
  label: string
  onClick: () => void
  danger?: boolean
  autoFocus?: boolean
}) {
  return (
    <button
      role="menuitem"
      autoFocus={autoFocus}
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 px-3 py-1.5 text-left transition-colors hover:bg-line focus:bg-line ${
        danger ? 'text-danger' : 'text-ink'
      }`}
    >
      {icon}
      {label}
    </button>
  )
}
