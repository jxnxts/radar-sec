// WebSocket client with reconnection: growing, jittered backoff, plus detection of
// silent connections (the server sends `system.status` every few seconds).

import type { ServerMessage } from '../types'

export type ConnectionState = 'connecting' | 'open' | 'waiting'

export interface ConnectionInfo {
  state: ConnectionState
  attempt: number
  /** When the next attempt happens (ms since the epoch), in the "waiting" state. */
  retryAt: number | null
}

export interface SocketOptions {
  url: string
  onMessage: (message: ServerMessage) => void
  onState: (info: ConnectionInfo) => void
  baseDelay?: number
  maxDelay?: number
  staleAfter?: number
  random?: () => number
  WebSocketImpl?: typeof WebSocket
}

/** Delay before attempt `attempt` (0 = first): doubles on each failure, up to the cap. */
export function backoffDelay(
  attempt: number,
  base = 500,
  max = 15_000,
  random: () => number = Math.random,
): number {
  const ceiling = Math.min(max, base * 2 ** attempt)
  // Half fixed, half random: clients that dropped together don't all come back at once.
  return Math.round(ceiling / 2 + (random() * ceiling) / 2)
}

export class RadarSocket {
  private socket: WebSocket | null = null
  private attempt = 0
  private retryTimer: ReturnType<typeof setTimeout> | null = null
  private staleTimer: ReturnType<typeof setTimeout> | null = null
  private stopped = true
  private readonly options: Required<Omit<SocketOptions, 'WebSocketImpl'>> & {
    WebSocketImpl: typeof WebSocket
  }

  constructor(options: SocketOptions) {
    this.options = {
      baseDelay: 500,
      maxDelay: 15_000,
      staleAfter: 20_000,
      random: Math.random,
      WebSocketImpl: options.WebSocketImpl ?? WebSocket,
      ...options,
    } as typeof this.options
  }

  start(): void {
    if (!this.stopped) return
    this.stopped = false
    this.connect()
  }

  stop(): void {
    this.stopped = true
    this.clearTimers()
    this.socket?.close()
    this.socket = null
  }

  private clearTimers(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer)
    if (this.staleTimer) clearTimeout(this.staleTimer)
    this.retryTimer = this.staleTimer = null
  }

  private connect(): void {
    if (this.stopped) return
    this.options.onState({ state: 'connecting', attempt: this.attempt, retryAt: null })
    const socket = new this.options.WebSocketImpl(this.options.url)
    this.socket = socket

    socket.onopen = () => {
      if (socket !== this.socket) return
      this.options.onState({ state: 'open', attempt: this.attempt, retryAt: null })
      this.watchStale()
    }
    socket.onmessage = (event: MessageEvent) => {
      if (socket !== this.socket) return
      this.attempt = 0 // only counts as recovered once real data arrives
      this.watchStale()
      try {
        this.options.onMessage(JSON.parse(String(event.data)) as ServerMessage)
      } catch (error) {
        console.error('invalid message from server', error)
      }
    }
    socket.onclose = () => {
      if (socket !== this.socket) return
      this.socket = null
      this.scheduleRetry()
    }
    socket.onerror = () => socket.close()
  }

  private watchStale(): void {
    if (this.staleTimer) clearTimeout(this.staleTimer)
    this.staleTimer = setTimeout(() => {
      // Open but silent connection: drop it so onclose reconnects.
      this.socket?.close()
    }, this.options.staleAfter)
  }

  private scheduleRetry(): void {
    if (this.stopped) return
    this.clearTimers()
    const delay = backoffDelay(
      this.attempt,
      this.options.baseDelay,
      this.options.maxDelay,
      this.options.random,
    )
    this.attempt += 1
    this.options.onState({ state: 'waiting', attempt: this.attempt, retryAt: Date.now() + delay })
    this.retryTimer = setTimeout(() => this.connect(), delay)
  }
}

export function socketUrl(location: Pick<Location, 'protocol' | 'host'>): string {
  return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`
}
