import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LanguageSwitch } from '../components/TopBar'
import { CATALOGS, STORAGE_KEY, detectLang, localized, normalizeLang, roleLabel, useLang } from '../i18n'
import { en } from '../i18n/en'

afterEach(() => vi.restoreAllMocks())

/** Every key path of a catalog, so pt-BR can be checked against en at runtime too. */
function keys(value: unknown, prefix = ''): string[] {
  if (value === null || typeof value !== 'object') return [prefix]
  return Object.entries(value).flatMap(([key, child]) => keys(child, prefix ? `${prefix}.${key}` : key))
}

describe('catalogs', () => {
  it('pt-BR has exactly the keys of en', () => {
    expect(keys(CATALOGS['pt-BR']).sort()).toEqual(keys(en).sort())
  })
})

describe('language switch', () => {
  it('switches the language, persists it and updates <html lang>', () => {
    render(<LanguageSwitch />)
    const group = screen.getByRole('group', { name: 'Language' })
    const english = screen.getByRole('button', { name: 'English' })
    const portuguese = screen.getByRole('button', { name: 'Português (Brasil)' })
    expect(group).toBeTruthy()
    expect(english.getAttribute('aria-pressed')).toBe('true')
    expect(portuguese.getAttribute('aria-pressed')).toBe('false')

    fireEvent.click(portuguese)
    expect(useLang.getState().lang).toBe('pt-BR')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('pt-BR')
    expect(document.documentElement.lang).toBe('pt-BR')
    expect(document.title).toBe('Radar SEC · sala de operações')
    // The group label follows the language; each option keeps its own name.
    expect(screen.getByRole('group', { name: 'Idioma' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Português (Brasil)' }).getAttribute('aria-pressed')).toBe('true')

    fireEvent.click(screen.getByRole('button', { name: 'English' }))
    expect(localStorage.getItem(STORAGE_KEY)).toBe('en')
    expect(document.documentElement.lang).toBe('en')
  })

  it('options are real buttons, reachable by keyboard', () => {
    render(<LanguageSwitch />)
    const portuguese = screen.getByRole('button', { name: 'Português (Brasil)' })
    portuguese.focus()
    expect(document.activeElement).toBe(portuguese)
    expect(portuguese.getAttribute('type')).toBe('button')
    expect(portuguese.getAttribute('lang')).toBe('pt-BR')
  })

  it('keeps working when storage throws', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    render(<LanguageSwitch />)
    expect(() => fireEvent.click(screen.getByRole('button', { name: 'Português (Brasil)' }))).not.toThrow()
    expect(useLang.getState().lang).toBe('pt-BR')
    expect(() => detectLang()).not.toThrow()
  })
})

describe('initial language', () => {
  it('prefers the saved choice', () => {
    localStorage.setItem(STORAGE_KEY, 'pt-BR')
    expect(detectLang()).toBe('pt-BR')
  })

  it('ignores garbage in storage and falls back to the browser language', () => {
    localStorage.setItem(STORAGE_KEY, 'klingon')
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['fr-FR', 'pt-PT', 'en-US'])
    expect(detectLang()).toBe('pt-BR')
  })

  it('defaults to English', () => {
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['de-DE'])
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('de-DE')
    expect(detectLang()).toBe('en')
  })

  it('normalizes language tags', () => {
    expect(normalizeLang('pt')).toBe('pt-BR')
    expect(normalizeLang('PT-br')).toBe('pt-BR')
    expect(normalizeLang('en-GB')).toBe('en')
    expect(normalizeLang('es')).toBeNull()
  })
})

describe('server text', () => {
  const map = { en: 'Two insiders bought.', 'pt-BR': 'Dois insiders compraram.' }

  it('picks the current language from a localized map', () => {
    expect(localized(map, 'en')).toBe('Two insiders bought.')
    expect(localized(map, 'pt-BR')).toBe('Dois insiders compraram.')
  })

  it('falls back to English, and accepts a plain string from older servers', () => {
    expect(localized({ en: 'Only English.' }, 'pt-BR')).toBe('Only English.')
    expect(localized('Texto antigo.', 'en')).toBe('Texto antigo.')
    expect(localized(null, 'en')).toBe('')
  })

  it('translates role codes and keeps free-text titles', () => {
    expect(roleLabel(CATALOGS['pt-BR'], 'Director')).toBe('diretor (conselho)')
    expect(roleLabel(CATALOGS['pt-BR'], 'CEO · Chief Executive Officer')).toBe('CEO · Chief Executive Officer')
    expect(roleLabel(CATALOGS['pt-BR'], 'Officer · EVP Sales')).toBe('executivo · EVP Sales')
    expect(roleLabel(CATALOGS.en, 'Chief Wizard')).toBe('Chief Wizard')
  })

  it('the whole switch is live: a subscriber sees the new language', () => {
    const seen: string[] = []
    const stop = useLang.subscribe((state) => seen.push(state.lang))
    act(() => useLang.getState().setLang('pt-BR'))
    stop()
    expect(seen).toEqual(['pt-BR'])
  })
})
