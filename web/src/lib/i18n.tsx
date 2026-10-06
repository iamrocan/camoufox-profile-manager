'use client'

/**
 * Translations, as a plain typed dictionary.
 *
 * Not next-intl or react-i18next: the UI is built with `output: "export"`,
 * so there is no server to run locale middleware on, and the routing-based
 * approaches those libraries are built around do not apply. Two languages
 * and a few hundred strings do not need an async message loader either.
 *
 * `en` is the source of truth. Every other locale is typed against it, so a
 * missing or misspelt key is a compile error rather than a blank label, and
 * adding a string to `en` forces the translators' hand immediately.
 *
 * Interpolation is `{name}` and is substituted by `t('key', { name })`.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

export const LOCALES = {
  en: 'English',
  es: 'Español',
} as const

export type Locale = keyof typeof LOCALES

const STORAGE_KEY = 'camoufox.locale'

// --- English: the source of truth ------------------------------------------

const en = {
  // Navigation and shell
  'nav.profiles': 'Profiles',
  'nav.groups': 'Groups',
  'nav.schedules': 'Schedules',
  'nav.settings': 'Settings',
  'nav.logout': 'Log out',
  'nav.language': 'Language',

  // Profiles list
  'profiles.title': 'Profiles',
  'profiles.search': 'Search name or ID',
  'profiles.allStatuses': 'All statuses',
  'profiles.new': 'New profile',
  'profiles.exportExcel': 'Export to Excel',
  'profiles.importExcel': 'Import from Excel',
  'profiles.importArchive': 'Import a profile archive',
  'profiles.loading': 'Loading…',
  'profiles.filterByStatus': 'Filter by status',
  'profiles.searchLabel': 'Search profiles',
  'profiles.selectAll': 'Select all on this page',
  'profiles.selectOne': 'Select {name}',
  'profiles.actionsFor': 'Actions for {name}',

  // Status filter options
  'statusOpt.active': 'Active',
  'statusOpt.inactive': 'Inactive',
  'statusOpt.blocked': 'Blocked',
  'statusOpt.maintenance': 'Maintenance',

  // Table headers
  'col.name': 'NAME',
  'col.id': 'ID',
  'col.group': 'GROUP',
  'col.os': 'OS',
  'col.status': 'STATUS',
  'col.lastUsed': 'LAST USED',
  'col.proxy': 'PROXY',

  // Row actions
  'action.run': 'Run',
  'action.stop': 'Stop',
  'action.edit': 'Edit',
  'action.duplicate': 'Duplicate',
  'action.checkProxy': 'Check proxy',
  'action.pauseProxy': 'Pause proxy',
  'action.resumeProxy': 'Resume proxy',
  'action.export': 'Export…',
  'action.clearData': 'Clear data',
  'action.delete': 'Delete',
  'action.cancel': 'Cancel',

  // Status
  'status.running': 'Running',
  'status.active': 'Active',
  'status.paused': 'paused',
  'status.checking': 'Checking…',
  'status.never': 'never',

  // Proxy pause
  'proxy.pausedTitle': 'Proxy paused',
  'proxy.pausedBody': '{name} will launch without its proxy until you resume it.',
  'proxy.resumedTitle': 'Proxy resumed',
  'proxy.resumedBody': '{name} will launch with its proxy again.',
  'proxy.toggleFailed': 'Could not toggle proxy',
  'proxy.pausedHint':
    'Proxy paused: the next launch will not use it. Toggle from the row menu.',

  // Clear data
  'clear.title': 'Clear browser data',
  'clear.body':
    'Cookies, cache, history, local/session storage and downloads for "{name}" will be wiped. The fingerprint, proxy and settings are kept — the profile keeps its identity but opens like a fresh install. This cannot be undone.',
  'clear.confirm': 'Clear data',
  'clear.doneTitle': 'Cleared {name}',
  'clear.doneBody': '{files} files removed ({mb} MB). The fingerprint was kept.',
  'clear.failed': 'Could not clear data',

  // Delete
  'delete.title': 'Delete profile',
  'delete.body':
    '"{name}" and its browser data will be removed. This cannot be undone.',
  'delete.done': 'Profile deleted',

  // Generic
  'generic.of': 'of',
  'generic.selected': 'selected',
} as const

export type MessageKey = keyof typeof en

// --- Spanish ----------------------------------------------------------------
//
// Neutral Latin American Spanish, impersonal where a label would otherwise
// have to pick a person ("Pausar proxy", not "Pausa el proxy"). Technical
// terms that the field uses in English — proxy, fingerprint, cookies, cache —
// are left alone, because translating them makes the UI harder to follow for
// anyone who reads about this subject anywhere else.

const es: Record<MessageKey, string> = {
  'nav.profiles': 'Perfiles',
  'nav.groups': 'Grupos',
  'nav.schedules': 'Programaciones',
  'nav.settings': 'Ajustes',
  'nav.logout': 'Cerrar sesión',
  'nav.language': 'Idioma',

  'profiles.title': 'Perfiles',
  'profiles.search': 'Buscar nombre o ID',
  'profiles.allStatuses': 'Todos los estados',
  'profiles.new': 'Nuevo perfil',
  'profiles.exportExcel': 'Exportar a Excel',
  'profiles.importExcel': 'Importar desde Excel',
  'profiles.importArchive': 'Importar un archivo de perfil',
  'profiles.loading': 'Cargando…',
  'profiles.filterByStatus': 'Filtrar por estado',
  'profiles.searchLabel': 'Buscar perfiles',
  'profiles.selectAll': 'Seleccionar todo en esta página',
  'profiles.selectOne': 'Seleccionar {name}',
  'profiles.actionsFor': 'Acciones para {name}',

  'statusOpt.active': 'Activo',
  'statusOpt.inactive': 'Inactivo',
  'statusOpt.blocked': 'Bloqueado',
  'statusOpt.maintenance': 'Mantenimiento',

  'col.name': 'NOMBRE',
  'col.id': 'ID',
  'col.group': 'GRUPO',
  'col.os': 'SO',
  'col.status': 'ESTADO',
  'col.lastUsed': 'ÚLTIMO USO',
  'col.proxy': 'PROXY',

  'action.run': 'Iniciar',
  'action.stop': 'Detener',
  'action.edit': 'Editar',
  'action.duplicate': 'Duplicar',
  'action.checkProxy': 'Probar proxy',
  'action.pauseProxy': 'Pausar proxy',
  'action.resumeProxy': 'Reanudar proxy',
  'action.export': 'Exportar…',
  'action.clearData': 'Limpiar datos',
  'action.delete': 'Eliminar',
  'action.cancel': 'Cancelar',

  'status.running': 'En ejecución',
  'status.active': 'Activo',
  'status.paused': 'pausado',
  'status.checking': 'Probando…',
  'status.never': 'nunca',

  'proxy.pausedTitle': 'Proxy pausado',
  'proxy.pausedBody': '{name} se abrirá sin su proxy hasta que lo reanudes.',
  'proxy.resumedTitle': 'Proxy reanudado',
  'proxy.resumedBody': '{name} volverá a abrirse con su proxy.',
  'proxy.toggleFailed': 'No se pudo cambiar el proxy',
  'proxy.pausedHint':
    'Proxy pausado: el próximo inicio no lo usará. Cámbialo desde el menú de la fila.',

  'clear.title': 'Limpiar datos del navegador',
  'clear.body':
    'Se borrarán cookies, caché, historial, almacenamiento local y de sesión, y descargas de "{name}". El fingerprint, el proxy y los ajustes se conservan — el perfil mantiene su identidad pero se abre como una instalación nueva. Esto no se puede deshacer.',
  'clear.confirm': 'Limpiar datos',
  'clear.doneTitle': '{name} limpiado',
  'clear.doneBody': '{files} archivos eliminados ({mb} MB). El fingerprint se conservó.',
  'clear.failed': 'No se pudieron limpiar los datos',

  'delete.title': 'Eliminar perfil',
  'delete.body':
    'Se eliminará "{name}" junto con sus datos de navegación. Esto no se puede deshacer.',
  'delete.done': 'Perfil eliminado',

  'generic.of': 'de',
  'generic.selected': 'seleccionados',
}

const MESSAGES: Record<Locale, Record<MessageKey, string>> = { en, es }

// --- Context ----------------------------------------------------------------

type Vars = Record<string, string | number>

interface I18nValue {
  locale: Locale
  setLocale: (next: Locale) => void
  t: (key: MessageKey, vars?: Vars) => string
}

const I18nContext = createContext<I18nValue | null>(null)

function interpolate(template: string, vars?: Vars): string {
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole,
  )
}

export function I18nProvider({ children }: { children: ReactNode }) {
  // Always start on `en` so the server-rendered markup and the first client
  // render agree; the stored choice is applied in an effect straight after.
  // Reading localStorage during render would hydrate-mismatch every page.
  const [locale, setLocaleState] = useState<Locale>('en')

  useEffect(() => {
    let stored: string | null = null
    try {
      stored = window.localStorage.getItem(STORAGE_KEY)
    } catch {
      // Private mode, or storage disabled. English it is.
    }
    if (stored && stored in MESSAGES) {
      setLocaleState(stored as Locale)
    }
  }, [])

  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next)
    try {
      window.localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // The choice still applies to this session.
    }
  }, [])

  const t = useCallback(
    (key: MessageKey, vars?: Vars) =>
      interpolate(MESSAGES[locale][key] ?? MESSAGES.en[key] ?? key, vars),
    [locale],
  )

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useI18n must be used inside I18nProvider')
  return ctx
}

/** Shorthand for the common case of only needing the translate function. */
export function useT(): I18nValue['t'] {
  return useI18n().t
}
