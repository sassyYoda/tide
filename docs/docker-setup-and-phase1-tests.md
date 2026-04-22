# Docker Setup & Phase 1 Test Run — ELI5 Guide

**Audience:** you, on macOS, with zero Docker experience.
**Goal:** install Docker, run the 5 Phase 1 verification tests, see them pass.
**Time:** ~20 minutes (10 of which is Docker installing itself in the background).

---

## Part 0 — What is Docker and why do we need it?

Docker is a way to run little "fake computers" (called **containers**) on your Mac. Phase 1 of Tide needs four of these fake computers running side-by-side:

1. **Postgres** with the TimescaleDB extension — the database
2. **Redis** — a fast cache we use for last-known-good data
3. **Qdrant** — a vector database (used later, started now for smoke tests)
4. **Python workers** — the code you wrote, running inside its own container

Without Docker you'd have to install Postgres, TimescaleDB, Redis, Qdrant, and all their Python bindings directly on your Mac. With Docker, `docker compose up` boots all of them in 60 seconds.

---

## Part 1 — Install Docker Desktop on macOS

### Step 1a: Download it

Go to https://www.docker.com/products/docker-desktop/ and click the big blue "Download for Mac" button. Pick the **Apple Silicon** version if you have an M1/M2/M3/M4 Mac, or **Intel** if it's older.

> **How do I know which chip I have?**
> Click the Apple menu → About This Mac. If it says "Apple M-something" you're on Apple Silicon. If it says "Intel Core i-something", pick Intel.

You'll get a file called `Docker.dmg`. Double-click it.

### Step 1b: Drag it to Applications

A window pops up with the Docker whale icon and an Applications folder. Drag the whale onto Applications. That's the whole install.

### Step 1c: Start Docker

Open Launchpad → click Docker. First launch asks for your Mac password (it needs one-time privileges to set up networking). Say yes.

You'll see a whale icon in your menu bar (top right of your screen). When it's solid and not animating, Docker is running.

> **First launch takes 1–2 minutes.** It's setting up a tiny Linux VM in the background. Don't close the window. Don't panic.

### Step 1d: Verify it works

Open Terminal (Cmd+Space → "Terminal") and paste:

```bash
docker run hello-world
```

You should see a big friendly message starting with:

```
Hello from Docker!
This message shows that your installation appears to be working correctly.
```

If you see that, **Docker is installed**. Close that window.

> **If you see `Cannot connect to the Docker daemon`:** Docker Desktop isn't running yet. Look for the whale in your menu bar. If no whale, open Docker from Launchpad.

---

## Part 2 — Run the 5 Phase 1 tests

All commands below should be run from the Tide repo root: `/Users/aryanahuja/projects/tide`.

```bash
cd ~/projects/tide
```

### Test 1: docker-compose boot smoke (SC-4)

This is the big one. It brings up all 6 containers (db, redis, qdrant, migrator, api, worker, beat) and confirms the NOAA poller starts writing data within 2 minutes.

```bash
bash scripts/smoke_compose.sh
```

**What to look for:**

- Containers booting: you'll see `tide-db`, `tide-redis`, `tide-qdrant`, `tide-migrator`, `tide-api`, `tide-worker`, `tide-beat` appearing in logs.
- The migrator container should print `alembic upgrade head` output, then exit cleanly.
- Within ~2 min, you should see log lines like `tide-worker | [INFO] NOAA poll succeeded for station 8531680`.

**Success =** the script exits with `✓ smoke test passed`. If it does, great — shut everything down with:

```bash
docker compose down -v
```

(The `-v` also deletes the volumes so next run starts fresh.)

> **If you want to poke around while it's running:** open a new Terminal tab and run:
> - `docker compose ps` — see all running containers
> - `docker compose logs -f api` — tail the API logs
> - `docker compose exec db psql -U tide -d tide -c 'SELECT count(*) FROM tidal_observations'` — see the row count grow

### Tests 2–5: Python test suites

These need Docker running (Docker Desktop open, whale in menu bar) but they don't need `docker compose up` — the tests spin up their *own* short-lived Postgres/Redis containers via a library called "testcontainers."

Run them one at a time and read the output. Each takes 30 sec to 3 min because testcontainers pulls the Postgres/Redis images on first run.

```bash
cd backend
```

**Test 2 — Freshness gate (6 tests):**
```bash
uv run pytest tests/unit/test_freshness_gate.py -q
```

Success = `6 passed`. This is the gate that makes `/conditions/:station_id` return a 503 when data is older than 35 minutes.

**Test 3 — Conditions endpoint integration (9 tests):**
```bash
uv run pytest tests/integration/test_conditions_endpoint.py -q
```

Success = `9 passed`. This is the *runtime proof* that the big CR-01 bug we fixed (the CAGG column names) is actually right. If this one fails after the static review said it was fine, come back and tell me.

**Test 4 — NOAA outage simulation (4 tests):**
```bash
uv run pytest tests/integration/test_noaa_outage_simulation.py -q
```

Success = `4 passed`. Simulates NOAA going down and confirms the circuit breaker trips after exactly 3 failures, last-known-good data is saved to Redis, and the worker doesn't crash.

**Test 5 — Seed idempotency + FK (4 tests):**
```bash
uv run pytest tests/integration/test_seed_idempotency.py -q
```

Success = `4 passed`. Proves that running `alembic upgrade head` twice doesn't duplicate the 9 stations and 30 fishing spots, and that every fishing spot's `nearest_station` points to a real station.

### One-shot way to run all four

If you're feeling fancy:

```bash
cd ~/projects/tide/backend
uv run pytest tests/unit/test_freshness_gate.py tests/integration/test_conditions_endpoint.py tests/integration/test_noaa_outage_simulation.py tests/integration/test_seed_idempotency.py -q
```

Expected: `23 passed`.

---

## Part 3 — Recording the results

When tests pass, open `.planning/phases/01-data-foundation/01-HUMAN-UAT.md` and change each `result: [pending]` to `result: passed` (or `failed: <what broke>`). Update the `Summary` block's counts. That's how the verification artifact gets "closed."

If anything fails, just tell me what you saw and I'll dig in.

---

## Troubleshooting cheat sheet

| Symptom | What's going on | Fix |
|---|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop isn't running | Open Docker from Launchpad, wait for the whale to stop animating |
| Tests hang for 5+ minutes on first run | testcontainers is pulling Postgres/Redis images | Be patient — only happens the first time |
| `docker compose up` says "port already in use" | You already have Postgres/Redis running locally | `brew services stop postgresql` and/or `brew services stop redis` |
| `uv: command not found` | uv isn't installed in the shell | `curl -LsSf https://astral.sh/uv/install.sh \| sh`, then open a new Terminal |
| Tests error with `docker.errors.DockerException` | Docker daemon isn't running | Start Docker Desktop; check the whale |
| Disk full warnings from Docker | Old images piling up | `docker system prune -a` (asks for confirmation before deleting) |
| "I see no whale and Docker Desktop is open" | macOS permissions/notch weirdness | Docker menu bar icon can hide behind the notch; try the Docker Desktop window directly |

---

## What NOT to worry about

- **Warnings about deprecated `@wait_container_is_ready` decorators** — known noise from the testcontainers library. Harmless.
- **Pytest collection warnings** — also harmless.
- **"Building X..." taking a long time** on first run — Docker is downloading base images. One-time cost.
- **First `docker compose up` pulling ~500MB** — Postgres + TimescaleDB + Redis + Qdrant images. One-time.

---

## When you're done

Come tell me what you saw. If everything passed: 🎉. If something failed: paste the error, and I'll figure out whether it's a real bug or just a setup quirk.
