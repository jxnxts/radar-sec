import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RadarSocket, backoffDelay, socketUrl, type ConnectionInfo } from '../lib/socket'
import type { ServerMessage } from '../types'

class FakeSocket {
  static instances: FakeSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  closed = false

  constructor(public url: string) {
    FakeSocket.instances.push(this)
  }

  close() {
    if (this.closed) return
    this.closed = true
    this.onclose?.()
  }

  open() {
    this.onopen?.()
  }

  send(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) })
  }
}

function setup() {
  const states: ConnectionInfo[] = []
  const messages: ServerMessage[] = []
  const socket = new RadarSocket({
    url: 'ws://test/ws',
    onMessage: (message) => messages.push(message),
    onState: (info) => states.push(info),
    baseDelay: 1000,
    maxDelay: 8000,
    staleAfter: 20_000,
    random: () => 1, // no jitter: the delay is always the ceiling
    WebSocketImpl: FakeSocket as unknown as typeof WebSocket,
  })
  return { socket, states, messages, last: () => FakeSocket.instances[FakeSocket.instances.length - 1]! }
}

beforeEach(() => {
  vi.useFakeTimers()
  FakeSocket.instances = []
})
afterEach(() => vi.useRealTimers())

describe('backoffDelay', () => {
  it('doubles on each attempt up to the cap', () => {
    const full = (attempt: number) => backoffDelay(attempt, 500, 15_000, () => 1)
    expect([0, 1, 2, 3, 4, 5, 6, 9].map(full)).toEqual([500, 1000, 2000, 4000, 8000, 15_000, 15_000, 15_000])
  })

  it('jitters within the upper half of the delay', () => {
    expect(backoffDelay(2, 500, 15_000, () => 0)).toBe(1000)
    expect(backoffDelay(2, 500, 15_000, () => 0.5)).toBe(1500)
  })
})

describe('RadarSocket', () => {
  it('connects, delivers messages and reports its state', () => {
    const { socket, states, messages, last } = setup()
    socket.start()
    expect(states.at(-1)?.state).toBe('connecting')
    last().open()
    expect(states.at(-1)?.state).toBe('open')
    last().send({ type: 'system.status', seq: 1, ts: '', data: {} })
    expect(messages).toHaveLength(1)
    socket.stop()
  })

  it('reconnects with growing delays and resets the count once data flows again', () => {
    const { socket, states, last } = setup()
    socket.start()
    last().close()
    expect(states.at(-1)).toMatchObject({ state: 'waiting', attempt: 1 })
    vi.advanceTimersByTime(999)
    expect(FakeSocket.instances).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(FakeSocket.instances).toHaveLength(2)

    last().close() // second failure: waits 2 s
    vi.advanceTimersByTime(1999)
    expect(FakeSocket.instances).toHaveLength(2)
    vi.advanceTimersByTime(1)
    expect(FakeSocket.instances).toHaveLength(3)

    last().open()
    last().send({ type: 'system.status', seq: 1, ts: '', data: {} })
    last().close() // dropped again after recovering: back to 1 s
    vi.advanceTimersByTime(1000)
    expect(FakeSocket.instances).toHaveLength(4)
    socket.stop()
  })

  it('drops a silent connection and tries again', () => {
    const { socket, states, last } = setup()
    socket.start()
    last().open()
    last().send({ type: 'system.status', seq: 1, ts: '', data: {} })
    vi.advanceTimersByTime(19_999)
    expect(last().closed).toBe(false)
    vi.advanceTimersByTime(1)
    expect(last().closed).toBe(true)
    expect(states.at(-1)?.state).toBe('waiting')
    socket.stop()
  })

  it('does not reconnect after stopping', () => {
    const { socket, last } = setup()
    socket.start()
    last().open()
    socket.stop()
    vi.advanceTimersByTime(60_000)
    expect(FakeSocket.instances).toHaveLength(1)
  })

  it('an invalid message does not break the client', () => {
    const { socket, messages, last } = setup()
    const silence = vi.spyOn(console, 'error').mockImplementation(() => {})
    socket.start()
    last().open()
    last().onmessage?.({ data: '{broken' })
    last().send({ type: 'system.status', seq: 2, ts: '', data: {} })
    expect(messages).toHaveLength(1)
    silence.mockRestore()
    socket.stop()
  })
})

describe('socketUrl', () => {
  it('follows the page protocol', () => {
    expect(socketUrl({ protocol: 'http:', host: 'localhost:5173' })).toBe('ws://localhost:5173/ws')
    expect(socketUrl({ protocol: 'https:', host: 'radar.example' })).toBe('wss://radar.example/ws')
  })
})
