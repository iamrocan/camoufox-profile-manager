'use client'

import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'

import { useT } from '@/lib/i18n'

interface ModalProps {
  open: boolean
  title: string
  subtitle?: string
  onClose: () => void
  children: React.ReactNode
  footer?: React.ReactNode
  width?: number
}

/**
 * Dialog shell. Closes on Escape and on backdrop click, moves focus inside on
 * open, and locks background scroll — the old modal did none of these.
 */
export function Modal({ open, title, subtitle, onClose, children, footer, width = 620 }: ModalProps) {
  const t = useT()
  const panelRef = useRef<HTMLDivElement>(null)
  const onCloseRef = useRef(onClose)

  // Callers commonly pass an inline callback. Keep the current callback in a
  // ref so parent rerenders do not tear down and recreate the focus trap.
  // Re-running that effect restores its initially focused element, which made
  // polling pages repeatedly steal focus back to an auto-focused input.
  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!open) return

    const panel = panelRef.current
    const previouslyFocused = document.activeElement as HTMLElement | null

    const focusable = () =>
      Array.from(
        panel?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((element) => element.offsetParent !== null)

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onCloseRef.current()
        return
      }
      // aria-modal alone does not stop Tab walking into the page behind the
      // overlay, so the cycle is kept inside the dialog by hand.
      if (event.key !== 'Tab') return
      const items = focusable()
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (event.shiftKey && (active === first || active === panel)) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && active === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    // Let autoFocus inside the dialog win; only fall back to the panel itself.
    if (!panel?.contains(document.activeElement)) panel?.focus()

    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
      previouslyFocused?.focus?.()
    }
  }, [open])

  if (!open) return null

  return (
    <div
      className="overlay-in fixed inset-0 z-40 flex items-center justify-center bg-black/70 p-6 backdrop-blur-[2px]"
      onMouseDown={(event) => {
        // Only a click that starts on the backdrop closes; a drag out of a text
        // field must not dismiss the dialog.
        if (event.target === event.currentTarget) onClose()
      }}
    >
      {/* Header and footer stay pinned; only the body scrolls, so a tall form
          can never push its own title or its Save button out of reach. */}
      <div
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        style={{ width }}
        className="dialog-in flex max-h-full max-w-full flex-col rounded-lg border border-line bg-surface shadow-2xl shadow-black/60 outline-none"
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-line px-5 py-3.5">
          <div>
            <h2 className="text-[14px] font-semibold">{title}</h2>
            {subtitle && <p className="mt-0.5 text-ink-dim">{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            aria-label={t('modal.close')}
            className="btn btn-ghost -mr-2 h-7 w-7 p-0"
          >
            <X size={15} strokeWidth={2} />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>

        {footer && (
          <footer className="flex shrink-0 justify-end gap-2 border-t border-line px-5 py-3">
            {footer}
          </footer>
        )}
      </div>
    </div>
  )
}

interface PromptProps {
  open: boolean
  title: string
  body?: string
  label: string
  placeholder?: string
  /** What the field starts with; re-applied each time the dialog opens. */
  initialValue?: string
  confirmLabel?: string
  busy?: boolean
  onSubmit: (value: string) => void
  onCancel: () => void
}

/**
 * Asks for one line of text. Replaces window.prompt, which cannot be styled,
 * cannot be translated and blocks the whole page.
 *
 * Submitting an empty field is allowed on purpose: for a value that can be
 * unset, clearing the box is the obvious way to say so, and a dialog that
 * refuses to close until you type something has no way to express it.
 */
export function PromptDialog({
  open,
  title,
  body,
  label,
  placeholder,
  initialValue = '',
  confirmLabel,
  busy = false,
  onSubmit,
  onCancel,
}: PromptProps) {
  const t = useT()
  const [value, setValue] = useState(initialValue)

  useEffect(() => {
    // The dialog stays mounted between openings, so the field has to be refilled
    // here; otherwise it would still hold whatever the last profile had in it.
    // A key would avoid the effect but would also discard what the user typed
    // whenever the parent rerendered, which polling pages do constantly.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (open) setValue(initialValue)
  }, [open, initialValue])

  return (
    <Modal
      open={open}
      title={title}
      onClose={onCancel}
      width={460}
      footer={
        <>
          <button type="button" className="btn btn-default" onClick={onCancel}>
            {t('action.cancel')}
          </button>
          <button type="submit" form="prompt-form" className="btn btn-primary" disabled={busy}>
            {confirmLabel ?? t('modal.confirm')}
          </button>
        </>
      }
    >
      <form
        id="prompt-form"
        onSubmit={(event) => {
          event.preventDefault()
          onSubmit(value.trim())
        }}
        className="flex flex-col gap-3"
      >
        {body && <p className="text-ink-dim">{body}</p>}
        <div>
          <label className="field-label" htmlFor="prompt-input">
            {label}
          </label>
          <input
            id="prompt-input"
            className="field font-mono"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={placeholder}
            autoFocus
            autoComplete="off"
            spellCheck={false}
          />
        </div>
      </form>
    </Modal>
  )
}

interface ConfirmProps {
  open: boolean
  title: string
  body: string
  confirmLabel?: string
  destructive?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** Replaces window.confirm so destructive actions match the rest of the UI. */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  destructive = false,
  onConfirm,
  onCancel,
}: ConfirmProps) {
  const t = useT()
  return (
    <Modal
      open={open}
      title={title}
      onClose={onCancel}
      width={420}
      footer={
        <>
          <button className="btn btn-default" onClick={onCancel}>
            {t('action.cancel')}
          </button>
          <button
            className={destructive ? 'btn btn-danger' : 'btn btn-primary'}
            onClick={onConfirm}
            autoFocus
          >
            {confirmLabel ?? t('modal.confirm')}
          </button>
        </>
      }
    >
      <p className="text-ink-dim">{body}</p>
    </Modal>
  )
}
