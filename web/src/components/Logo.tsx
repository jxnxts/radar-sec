import { useEffect, useState } from 'react'
import { hueOf, initials } from '../lib/format'

interface LogoProps {
  src: string | null
  ticker: string
  company: string
  size?: 'sm' | 'md' | 'lg'
}

type Tone = 'light' | 'dark' | 'empty'

/**
 * Picks the backing plate by looking at the image: a light logo (white on transparent)
 * needs a dark plate; a nearly empty image is useless and becomes a monogram.
 */
export function logoTone(pixels: Uint8ClampedArray): Tone {
  let opaque = 0
  let luminance = 0
  for (let i = 0; i < pixels.length; i += 4) {
    const alpha = pixels[i + 3] ?? 0
    if (alpha < 40) continue
    opaque += 1
    luminance += (0.2126 * (pixels[i] ?? 0) + 0.7152 * (pixels[i + 1] ?? 0) + 0.0722 * (pixels[i + 2] ?? 0)) / 255
  }
  const total = pixels.length / 4
  if (total === 0 || opaque / total < 0.02) return 'empty'
  return luminance / opaque > 0.82 && opaque / total < 0.9 ? 'dark' : 'light'
}

function analyse(image: HTMLImageElement): Tone {
  try {
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 24
    const context = canvas.getContext('2d', { willReadFrequently: true })
    if (!context) return 'light'
    context.drawImage(image, 0, 0, 24, 24)
    return logoTone(context.getImageData(0, 0, 24, 24).data)
  } catch {
    return 'light'
  }
}

/**
 * Company logo on a plate (many logos have a transparent background). Without a
 * reliable logo, a monogram with the initials and a color derived from the ticker.
 */
export function Logo({ src, ticker, company, size = 'md' }: LogoProps) {
  const [failed, setFailed] = useState(false)
  const [tone, setTone] = useState<Tone>('light')
  useEffect(() => {
    setFailed(false)
    setTone('light')
  }, [src])

  if (!src || failed || tone === 'empty') {
    const hue = hueOf(ticker || company)
    return (
      <span
        className={`logo logo--${size} logo--mono`}
        style={{ '--hue': hue } as React.CSSProperties}
        aria-hidden="true"
      >
        {initials(ticker, company)}
      </span>
    )
  }
  return (
    <span className={`logo logo--${size}${tone === 'dark' ? ' logo--dark' : ''}`}>
      <img
        src={src}
        alt=""
        loading="lazy"
        decoding="async"
        onLoad={(event) => setTone(analyse(event.currentTarget))}
        onError={() => setFailed(true)}
      />
    </span>
  )
}
