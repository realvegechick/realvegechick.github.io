# 小传说·对决（本地版）

完全前端、静态托管的《小传说·对决》。规则引擎跑在浏览器里（Pyodide + backend/game），
无后端、无登录、无排行榜。

## 目录

- `index.html` — 入口，注入 `api-shim.js` 后加载主应用
- `api-shim.js` — 劫持 `fetch('/api/*')` 到本地引擎或 localStorage
- `pyodide-worker.js` — Web Worker，加载 Pyodide 与 `game/*.py`
- `game/` — 从后端拷来的规则引擎（`__init__.py` / `cards.py` / `engine.py`）
- `assets/` — 主 JS/CSS、图片、音频

## 本地运行

任意静态服务器都行（不能 `file://`，Web Worker 需要同源协议）：

```bash
cd dist
python3 serve.py --port 8765
# 打开 http://127.0.0.1:8765
```

`serve.py` 是一个带 SPA fallback 的静态服务器（未知路径回退到 `index.html`）。
如果只用 `python3 -m http.server`，主流程也能跑，只是手动访问 `/ranking`、`/admin`
这类下线路径会看到 404，而不是被静默重定向。

首次访问会：

1. 弹一次原生 prompt 让你输入昵称（存 `localStorage.duel.nickname`）
2. 从 CDN 加载 Pyodide（约 6MB gzip），之后浏览器缓存
3. 之后每次进入秒开

## 部署到静态托管

`dist/` 整个目录上传即可（GitHub Pages / Netlify / Cloudflare Pages / 任意对象存储）。
所有资源引用都是相对路径，可以部署在子路径下。

## 战绩

每局结束后写入 `localStorage.duel.history`，格式：

```js
{ ts, winner, result, coins, turn }
```

当前版本没有 UI 展示（原排行榜/管理后台入口已隐藏）。数据保留以便将来加界面。

## 已知取舍

- 首屏加载依赖 Pyodide CDN（`cdn.jsdelivr.net/pyodide/v0.26.4/full/`），断网无法首次启动；缓存后可离线。
- 原后端提供的排行榜、管理后台、访问记录在纯前端下已完全下线：入口按钮被移除、`/ranking` 和 `/admin` 路由拦截回首页、对应 API 一律 404。bundle 里的组件代码是死代码，无法从入口触达。
- 规则引擎用的是 `backend/game/` 的最新版本，如果后端 py 文件更新，需要把最新的 3 个文件复制到 `dist/game/`。
