// fetch shim：把 /api/* 请求路由到本地 Pyodide worker 或 localStorage mock。
// 必须在 dist 主 JS 之前加载。
(function () {
  'use strict'

  const NICKNAME_KEY = 'duel.nickname'
  const HISTORY_KEY = 'duel.history'
  const USER_ID = 'local-solo'

  function getNickname() {
    try {
      let name = window.localStorage.getItem(NICKNAME_KEY)
      if (!name) {
        name = window.prompt('欢迎来到小传说·对决！\n请输入你的昵称（20 字以内）：', '旅行者')
        if (name) {
          name = name.trim().slice(0, 20) || '旅行者'
        } else {
          name = '旅行者'
        }
        window.localStorage.setItem(NICKNAME_KEY, name)
      }
      return name
    } catch { return '旅行者' }
  }

  function readHistory() {
    try { return JSON.parse(window.localStorage.getItem(HISTORY_KEY) || '[]') }
    catch { return [] }
  }
  function writeHistory(list) {
    try { window.localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(-200))) }
    catch { /* 忽略配额错误 */ }
  }
  window.__duelRecordResult = function (game) {
    // 由 shim 内部在结算时调用
    const entry = {
      ts: Date.now(),
      winner: game?.winner ?? null,
      result: game?.winner === 'player' ? 'win' : game?.winner === 'ai' ? 'loss' : 'draw',
      coins: game?.coins || null,
      turn: game?.turn_number ?? null,
    }
    const list = readHistory()
    list.push(entry)
    writeHistory(list)
  }

  // ---- worker rpc ----
  const worker = new Worker('pyodide-worker.js')
  const pending = new Map()
  let nextId = 1
  worker.onmessage = evt => {
    const { id, ok, result, error } = evt.data
    const entry = pending.get(id)
    if (!entry) return
    pending.delete(id)
    if (ok) entry.resolve(result)
    else entry.reject(error)
  }
  function call(method, payload) {
    return new Promise((resolve, reject) => {
      const id = nextId++
      pending.set(id, { resolve, reject })
      worker.postMessage({ id, method, payload })
    })
  }

  // ---- 响应助手 ----
  function jsonResponse(body, init = {}) {
    const status = init.status ?? 200
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  function errorResponse(status, code, message) {
    return jsonResponse({ error: code, message, details: {} }, { status })
  }

  // ---- 路由 ----
  async function handle(url, method, request) {
    const path = url.pathname
    if (path === '/api/me' && method === 'GET') {
      const displayName = getNickname()
      return jsonResponse({ userId: USER_ID, displayName, isAdmin: false })
    }
    if (path === '/api/visits' && method === 'POST') {
      // 本地无访问记录
      return jsonResponse({ counted: false, visitedAt: new Date().toISOString() })
    }
    if (path === '/api/cards' && method === 'GET') {
      const cards = await call('cards')
      return jsonResponse({ cards })
    }
    if (path === '/api/game/new' && method === 'POST') {
      const packet = await call('newGame')
      return jsonResponse(packet, { status: 201 })
    }
    if (path === '/api/game/action' && method === 'POST') {
      const body = await request.json()
      try {
        const packet = await call('action', { gameId: body.gameId, action: body.action })
        if (packet?.game?.status === 'finished' && !packet.__recorded) {
          packet.__recorded = true
          window.__duelRecordResult(packet.game)
        }
        return jsonResponse(packet)
      } catch (err) {
        return errorResponse(err.code === 'not_found' ? 404 : 400, err.code || 'engine_error', err.message || '操作失败')
      }
    }
    const clearMatch = path.match(/^\/api\/game\/([^/]+)$/)
    if (clearMatch && method === 'DELETE') {
      await call('clear', { gameId: decodeURIComponent(clearMatch[1]) })
      return new Response(null, { status: 204 })
    }
    // 排行榜和管理后台在本地版已经从入口和路由层屏蔽，接口一律 404
    return errorResponse(404, 'not_found', '未知接口')
  }

  const originalFetch = window.fetch.bind(window)
  window.fetch = function (input, init) {
    try {
      const request = input instanceof Request ? input : new Request(input, init)
      const url = new URL(request.url, window.location.href)
      if (url.origin === window.location.origin && url.pathname.startsWith('/api/')) {
        return handle(url, request.method.toUpperCase(), request).catch(err => {
          return errorResponse(500, 'shim_error', err?.message || String(err))
        })
      }
    } catch { /* 落回原生 fetch */ }
    return originalFetch(input, init)
  }
})()
