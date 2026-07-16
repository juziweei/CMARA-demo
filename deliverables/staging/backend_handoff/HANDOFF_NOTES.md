# Handoff Notes

## Frontend-first prompt

你是这个项目的前端接手工程师。优先修改 `frontend/index.html`、`frontend/styles.css`、`frontend/app.js`，保持当前 API 契约不变。页面默认通过 `/health`、`/scenarios`、`/turn`、`/clarification`、`/summarize`、`/reset` 和 `/demo/*` 接口联调。目标是保持演示页可用、布局稳定、状态显示清楚，不要先重写后端逻辑。

## Backend-support prompt

如果前端改动需要新增字段或新状态，先同步更新 `src/interface/http_api.py`、`src/interface/api_service.py` 和 `docs/10_api_contract.md`，再动页面。不要删除现有健康检查和场景接口；`data/preferences.json` 是运行数据，不是源码。

## Reminders

- 不要打包 `.git/`、`__pycache__/`、`.pytest_cache/`
- 不要打包 `data/qdrant/`、`data/history.db`
- 不要依赖 `.env`，只给 `.env.example`
- 前端单独改时，先确认 API Base 指向可用后端
- 如果只看静态页面，记得说明它仍然依赖后端数据源
