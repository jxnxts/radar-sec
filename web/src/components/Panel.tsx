import type { ReactNode } from 'react'

interface PanelProps {
  index: string
  title: string
  aside?: ReactNode
  className?: string
  children: ReactNode
  labelledBy: string
}

/** Frame of a room panel: number, title and registration marks in the corners. */
export function Panel({ index, title, aside, className = '', children, labelledBy }: PanelProps) {
  return (
    <section className={`panel ${className}`} aria-labelledby={labelledBy}>
      <header className="panel__head">
        <h2 className="panel__title" id={labelledBy}>
          <span className="panel__index" aria-hidden="true">
            {index}
          </span>
          {title}
        </h2>
        {aside ? <div className="panel__aside">{aside}</div> : null}
      </header>
      <div className="panel__body">{children}</div>
    </section>
  )
}
