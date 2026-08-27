// Pyodide worker：把 backend/game 里的规则引擎跑在浏览器里。
// 主线程通过 postMessage({id, method, payload}) 请求；worker 回 {id, ok, result|error}。

const PYODIDE_VERSION = 'v0.26.4'
const PYODIDE_BASE = `https://cdn.jsdelivr.net/pyodide/${PYODIDE_VERSION}/full/`

self.importScripts(PYODIDE_BASE + 'pyodide.js')
/* global loadPyodide */

const state = { games: new Map(), pyodide: null, ready: null, nextGameId: 1, bootstrapError: null }

const BRIDGE_PY = `
import copy, json
from game import (
    new_game as _new_game,
    apply_action as _apply_action,
    public_state as _public_state,
    take_action_events as _take_action_events,
    card_catalog as _card_catalog,
    GameError,
)

_games = {}
_next_id = [1]

def _pack(state_obj):
    events = _take_action_events(state_obj)
    return {"game": _public_state(state_obj), "events": events}

def create_game():
    gid = f"local-{_next_id[0]}"
    _next_id[0] += 1
    state = _new_game()
    packet = _pack(state)
    _games[gid] = state
    packet["gameId"] = gid
    return packet

def apply(gid, action):
    state = _games.get(gid)
    if state is None:
        raise GameError("对局不存在或无权访问", code="not_found")
    action_py = action.to_py() if hasattr(action, 'to_py') else action
    try:
        next_state = _apply_action(state, action_py)
    except GameError as err:
        raise
    _games[gid] = next_state
    packet = _pack(next_state)
    packet["gameId"] = gid
    return packet

def clear(gid):
    _games.pop(gid, None)
    return None

def catalog():
    return _card_catalog()

def dispatch(method, payload_json):
    payload = json.loads(payload_json) if payload_json else {}
    try:
        if method == "cards":
            result = catalog()
        elif method == "newGame":
            result = create_game()
        elif method == "action":
            result = apply(payload["gameId"], payload["action"])
        elif method == "clear":
            result = clear(payload["gameId"])
        else:
            return json.dumps({"ok": False, "error": {"code": "unknown_method", "message": method, "details": {}}})
        return json.dumps({"ok": True, "result": result}, default=str)
    except GameError as err:
        return json.dumps({"ok": False, "error": {"code": err.code, "message": str(err), "details": err.details}})
    except Exception as err:
        return json.dumps({"ok": False, "error": {"code": "engine_error", "message": f"{type(err).__name__}: {err}", "details": {}}})
`

async function bootstrap() {
  const pyodide = await loadPyodide({ indexURL: PYODIDE_BASE })
  const files = ['__init__.py', 'cards.py', 'engine.py']
  const sources = await Promise.all(files.map(f =>
    fetch(new URL(`game/${f}`, self.location.href)).then(r => {
      if (!r.ok) throw new Error(`加载 game/${f} 失败: ${r.status}`)
      return r.text()
    })
  ))
  pyodide.FS.mkdir('/game')
  files.forEach((f, i) => pyodide.FS.writeFile(`/game/${f}`, sources[i]))
  pyodide.runPython(`import sys; sys.path.insert(0, '/')`)
  pyodide.runPython(BRIDGE_PY)
  state.pyodide = pyodide
}

state.ready = bootstrap().catch(err => { state.bootstrapError = err })

self.onmessage = async event => {
  const { id, method, payload } = event.data
  try {
    await state.ready
    if (state.bootstrapError) throw state.bootstrapError
    const dispatch = state.pyodide.globals.get('dispatch')
    try {
      const raw = dispatch(method, JSON.stringify(payload ?? {}))
      const parsed = JSON.parse(raw)
      if (parsed.ok) {
        self.postMessage({ id, ok: true, result: parsed.result })
      } else {
        self.postMessage({ id, ok: false, error: parsed.error })
      }
    } finally {
      dispatch.destroy()
    }
  } catch (err) {
    self.postMessage({
      id, ok: false,
      error: { code: 'engine_error', message: err?.message || String(err), details: {} },
    })
  }
}
