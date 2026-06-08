# CMARA Demo

CMARA Demo is a server-side vehicle memory demo built around a simple loop:

```text
user input
-> retrieve history and structured preferences
-> decide ACT or ASK
-> learn from clarification
-> summarize a day's dialogue into reusable preferences
-> reuse those preferences next time
```

This repo is a demo system, not the paper evaluation pipeline. The focus here is a stable, explainable interaction loop that can be shown in a frontend.

## What works now

- Long-term memory storage and retrieval through LightMem
- Structured preference table for reusable preferences
- Policy layer that decides when to act and when to ask
- Clarification learning after a follow-up answer
- Offline preference extraction through `DirectPreferenceExtractor(Qwen)`
- Minimal HTTP API for frontend integration
- Server-side runbook and handoff docs

The current backend loop has already been validated on the server:

- `POST /turn`
- `POST /clarification`
- `POST /summarize`
- `GET /preferences`
- `POST /reset`

## Current boundaries

- `music_mode` can be extracted, stored, retrieved, and displayed, but it does not have a real execution tool yet.
- The API is intentionally single-session for demo stability: `session_id="default"`.
- The condition schema is intentionally narrow and demo-focused.
- This repo does not include the full benchmark-truth curation workflow.

## Repo structure

```text
src/
  action/         tool wrappers and LLM client
  interface/      session runtime, API service, HTTP server, CLI
  memory/         LightMem wrapper, preference table, learner, summarizer
  policy/         ACT vs ASK decision logic
scripts/          scenario runners, benchmarks, API startup
docs/             architecture, runbook, API contract, handoff docs
tests/            focused backend regression tests
```

## Key backend entrypoints

- Session state machine: `src/interface/session.py`
- Shared runtime builder: `src/interface/runtime.py`
- API service layer: `src/interface/api_service.py`
- HTTP server: `src/interface/http_api.py`
- API startup script: `scripts/run_api_server.py`

## Server environment

The current source-of-truth environment is the server:

- Host: `114.215.186.130`
- SSH port: `57003`
- Project root: `/root/vehicle_memory_demo`
- Python: `/data/miniconda3/envs/lightmem/bin/python`
- LightMem source: `/data/vmr_project/external/LightMem/src`
- LLM base URL: `http://127.0.0.1:7200/v1`
- Model: `Qwen2.5-14B-Instruct`

Login:

```bash
ssh -p 57003 root@114.215.186.130
```

Prepare environment:

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
```

## Run the demo backend

Start the HTTP API:

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
/data/miniconda3/envs/lightmem/bin/python scripts/run_api_server.py --host 0.0.0.0 --port 8010
```

Health check:

```bash
curl http://127.0.0.1:8010/health
```

Run the interactive CLI:

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
/data/miniconda3/envs/lightmem/bin/python src/interface/cli.py --debug
```

Run the main scenario:

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
/data/miniconda3/envs/lightmem/bin/python scripts/run_family_trip_scenario.py --reset
```

## HTTP API

Base URL:

```text
http://127.0.0.1:8010
```

Routes:

- `GET /health`
- `GET /preferences`
- `POST /turn`
- `POST /clarification`
- `POST /summarize`
- `POST /reset`

Minimal flow:

1. `POST /turn`
2. If response status is `needs_user_input`, keep `pending.pending_id`
3. Send the next user answer to `POST /clarification`
4. Use `GET /preferences` to display structured memory
5. Use `POST /summarize` to extract reusable preferences from the current session

See the full API contract in [docs/10_api_contract.md](docs/10_api_contract.md).

## Validation status

Validated locally:

- `pytest`
- Latest local result: `34 passed`

Validated on server:

- Runtime check against live Qwen service
- Real HTTP flow:
  - reset
  - turn
  - summarize
  - turn
  - clarification
  - preferences

Observed server behavior:

- A long family-trip dialogue can be summarized into structured preferences
- A later hot-weather request can trigger an ASK when conditions conflict
- Answering "好多了，今天基本恢复了" leads to:
  - `set_ac_temperature(value=25)`
  - a learned `health_state == recovering` preference
  - expiration of the older `health_state == sick` preference

## Handoff docs

Start here if you are taking over the project:

- [docs/06_backend_closure.md](docs/06_backend_closure.md)
- [docs/07_server_runbook.md](docs/07_server_runbook.md)
- [docs/08_frontend_handoff.md](docs/08_frontend_handoff.md)
- [docs/10_api_contract.md](docs/10_api_contract.md)
- [docs/11_next_goal.md](docs/11_next_goal.md)
