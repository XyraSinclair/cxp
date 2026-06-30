# cxp — codexpool

Make several ChatGPT Pro accounts behave as **one** Codex login.

`cxp` is a localhost token-injecting proxy. Codex is pointed at it (via
`chatgpt_base_url`). For each request the proxy picks an account by **live usage**,
injects that account's bearer token, and streams the response straight back. It is
the **sole refresher** per account — single-use rotating refresh tokens are never
copied or raced (the bug that otherwise forces constant re-logins). It rotates
accounts only *between turns*: on a real quota wall, or when live usage drops under
the spillover threshold. That rotation is the hot-swap.

This is the canonical, proven system. (It supersedes the older `codex-hot-swap`
PTY-wrapper approach, which is retired.)

## Why
Run a swarm of Codex agents overnight without hitting a single account's 5h/weekly
caps. When one account walls, traffic transparently moves to the next account with
headroom — no chat is killed, no token is double-spent.

## Install
```bash
./install.sh            # places cxp + cxp-bridge, sets up the codex shim
cxp import              # seed the pool from ~/.codex/accounts/*.auth.json
cxp login               # add accounts via OAuth (browser); repeat per account
cxp install-agent       # launchd: keep the proxy alive across reboots/crashes
cxp status              # verify
```
Requires Python 3.9+ and `aiohttp` (`pip install -r requirements.txt`).
`cxp-bridge` is stdlib-only.

## Commands
```
cxp [codex args...]   launch codex through the pool (default)
cxp status            per-account live usage + routing + proxy health
cxp import            (re)seed the pool from ~/.codex/accounts/*.auth.json
cxp login [hint]      sign one account into the pool (browser OAuth)
cxp auth-log          recent auth/login events
cxp quarantine        move pooled ~/.codex credentials aside so cxp owns refresh
cxp unquarantine      restore files moved by `cxp quarantine`
cxp proxy             run the proxy in the foreground (normally auto-spawned)
cxp stop | restart    control the shared proxy
cxp install-agent     install the launchd keepalive agent
cxp uninstall-agent   remove it
```

## Architecture
```
codex / omp (openai-codex provider)
        │
        ▼
  cxp-bridge  ── forwards stranded/old ports to the live proxy (never kills a chat)
        │
        ▼
  cxp proxy   ── picks account by live usage, injects bearer, rotates on a wall
        │
        ▼
  OpenAI backend-api/codex
```
- **cxp** — the proxy + control CLI (one self-installing file; the launchd agent is a copy of it).
- **cxp-bridge** — strictly-additive reachability guarantee: re-listens on free/old ports a running chat baked in at launch and pipes them to the current proxy. Only ever binds free ports; never kills or restarts anything.

## Failover detection
A turn fails over to a fresh account only when the proxy *recognizes* the wall.
There are three detection paths, because ChatGPT signals a spent quota three
different ways:
1. **HTTP 429** with a quota code/message — caught before the body streams.
2. **Early SSE error** — a quota event in the first 64 KB / 1.5 s of the stream,
   before any output. The turn is rerouted in place.
3. **Mid-stream SSE error** — ChatGPT delivers the 5h-window wall as an error
   event *inside a 200 stream, after token output has already started*. The
   in-flight turn can no longer be rerouted (bytes are already going to the
   client), but the relay scans the whole stream (`scan_sse_for_quota`) and, on
   a hit, flags the account walled so sticky affinity breaks and the **next**
   turn moves to a healthy account.

Path 3 matters: without it a single account pinned by affinity absorbs every
retry against an exhausted 5h window — observed in the wild as tens of thousands
of `[200]`s, zero detected walls, and no failover, while sibling accounts sat at
full headroom. `cxp status` (which reads the usage endpoint directly) shows the
account `WALLED`; the proxy must agree, mid-conversation, for the swap to fire.

## Tests
```bash
python3 tests/test_wall_detection.py      # or: pytest tests/
```
`tests/test_wall_detection.py` locks in all three detection paths — including a
test that *proves* the prefix scanner misses a mid-stream wall (the regression
path 3 closes).

## Safety / hygiene
- Never commit credentials. `.gitignore` excludes `accounts/`, `*.auth.json`, logs,
  ports, and `codex-home/`. The source contains **no** secrets.
- cxp must be the **only** token refresher for the pooled accounts. Do not run a
  second refresher (e.g. the old `codex-hot-swap` daemon) against the same accounts
  — that races the single-use refresh tokens and burns the accounts.

## License
MIT — see [LICENSE](LICENSE).
