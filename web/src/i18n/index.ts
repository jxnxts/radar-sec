// Current language: chosen by the operator (saved in localStorage), else the browser's,
// else English. Changing it re-renders every component that reads `useI18n()`.

import { create } from 'zustand'
import { formatter, type Format } from '../lib/format'
import { CATALOGS, DEFAULT_LANG, normalizeLang, type Lang } from './catalog'
import type { Messages } from './en'

export * from './catalog'
export type { Messages } from './en'

export const STORAGE_KEY = 'radar.lang'

function readStored(): Lang | null {
  try {
    const value = globalThis.localStorage?.getItem(STORAGE_KEY)
    return value === 'en' || value === 'pt-BR' ? value : null
  } catch {
    return null // storage blocked (private mode, sandboxed iframe): fall through
  }
}

function writeStored(lang: Lang): void {
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, lang)
  } catch {
    // Not persisted, but the switch still works for this session.
  }
}

/** Saved choice, else the first supported browser language, else English. */
export function detectLang(): Lang {
  const stored = readStored()
  if (stored) return stored
  try {
    const nav = globalThis.navigator
    const tags = nav?.languages?.length ? nav.languages : nav?.language ? [nav.language] : []
    for (const tag of tags) {
      const lang = normalizeLang(tag)
      if (lang) return lang
    }
  } catch {
    // ignore
  }
  return DEFAULT_LANG
}

/** Keeps `<html lang>` and the tab title in step with the language. */
export function applyDocumentLang(lang: Lang): void {
  if (typeof document === 'undefined') return
  document.documentElement.lang = lang
  document.title = CATALOGS[lang].app.title
}

interface LangState {
  lang: Lang
  setLang: (lang: Lang) => void
}

export const useLang = create<LangState>((set) => ({
  lang: detectLang(),
  setLang: (lang) => {
    writeStored(lang)
    applyDocumentLang(lang)
    set({ lang })
  },
}))

export interface I18n {
  lang: Lang
  t: Messages
  f: Format
}

/** Catalog and formatters for the current language. */
export function useI18n(): I18n {
  const lang = useLang((s) => s.lang)
  return { lang, t: CATALOGS[lang], f: formatter(lang) }
}
