import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach } from 'vitest'
import { useLang } from '../i18n'

// Every test starts in English with empty storage; tests that need pt-BR switch explicitly.
beforeEach(() => {
  try {
    localStorage.clear()
  } catch {
    // ignore
  }
  useLang.setState({ lang: 'en' })
})

afterEach(() => cleanup())
