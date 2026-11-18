// Supported languages, their catalogs and helpers that turn server codes into text.
// Kept free of React and of the store so that pure modules (lib/format) can use it.

import type { Localized } from '../types'
import { en, type Messages } from './en'
import { ptBR } from './pt-BR'

export type Lang = 'en' | 'pt-BR'

export const LANGS: readonly Lang[] = ['en', 'pt-BR']
export const DEFAULT_LANG: Lang = 'en'

export const CATALOGS: Record<Lang, Messages> = { en, 'pt-BR': ptBR }

/** BCP 47 tag handed to `Intl` (and to the chart library) for each language. */
export function intlLocale(lang: Lang): string {
  return lang === 'en' ? 'en-US' : 'pt-BR'
}

/** Maps any language tag to a supported one: `pt*` → pt-BR, `en*` → en, else null. */
export function normalizeLang(tag: string | null | undefined): Lang | null {
  if (!tag) return null
  const lower = tag.toLowerCase()
  if (lower.startsWith('pt')) return 'pt-BR'
  if (lower.startsWith('en')) return 'en'
  return null
}

/**
 * Picks the text for `lang` from a server-provided `{ en, "pt-BR" }` map, falling back
 * to English. A plain string (older servers) is returned as is.
 */
export function localized<T extends string>(
  value: Localized<T> | T | null | undefined,
  lang: Lang,
): T | '' {
  if (value == null) return ''
  if (typeof value === 'string') return value
  return value[lang] ?? value.en ?? (Object.values(value)[0] as T | undefined) ?? ''
}

/** Looks a server code up in a catalog map; unknown codes are shown untranslated. */
export function labelOf(map: Record<string, string>, code: string | null | undefined): string {
  if (!code) return ''
  return map[code] ?? code
}

/**
 * Insider role: one of the server's role labels, a free-text SEC officer title
 * (shown as is) or a composite "CEO · Chief Executive Officer".
 */
export function roleLabel(t: Messages, role: string | null | undefined): string {
  if (!role) return ''
  const [head, ...rest] = role.split(' · ')
  return [labelOf(t.roles, head), ...rest].join(' · ')
}
