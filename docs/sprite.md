# One-command Sprite deployment

## Context

The current deploy instructions are 7 manual steps including shelling into a
Sprite console, running git clone, pip install, set-password interactively, etc.
No non-technical user will do this. The goal is a single `curl | bash` that
prompts for the minimum (sprite name, admin password) and does everything else.

## Changes

### 1. Non-interactive credential bootstrap (`bullpen.py`)

Add a `--bootstrap-credentials` flag (or just detect the env vars) that reads:
- `BULLPEN_BOOTSTRAP_USER` (default: "admin")
- `BULLPEN_BOOTSTRAP_PASSWORD` (required)

If both are set, hash the password and write credentials via the existing
`auth.apply_credentials_mapping()` + `auth.write_env_file()` path, then exit.
Skip if credentials already exist (idempotent).

This is a new function `bootstrap_credentials()` in `bullpen.py`, called from
the deploy script via:
```
sprite exec --env BULLPEN_BOOTSTRAP_PASSWORD=xxx -- python bullpen.py --bootstrap-credentials
```

No shell history leakage concern here because `sprite exec --env` doesn't
persist to history on the Sprite, and the user typed the password into a
`read -s -p` prompt on their local machine (the deploy script handles this).

### 2. `deploy-sprite.sh` (new file, repo root)

Interactive local script. Flow:

```
1. Check `sprite` CLI exists, offer install URL if not
2. Prompt: sprite name (default: bullpen)
3. Prompt: admin password (read -s, no echo, confirm)
4. sprite create $NAME (skip if exists)
5. sprite exec: git clone, pip install
6. sprite exec --env: bootstrap credentials
7. sprite exec: echo exports >> ~/.bashrc (BULLPEN_PRODUCTION=1)
8. sprite exec: sprite-env services create
9. sprite url update --auth public
10. Print the live URL
```

User experience:
```
$ curl -sL https://raw.githubusercontent.com/billroy/bullpen/main/deploy-sprite.sh | bash
Sprite name [bullpen]: mybullpen
Admin password: ********
Confirm password: ********

Creating Sprite...         done (1.2s)
Installing Bullpen...      done (18s)
Setting up credentials...  done
Starting service...        done
Making it public...        done

Your Bullpen is live at: https://mybullpen.sprites.app
```

### Files to modify
- `bullpen.py` — add `--bootstrap-credentials` flag + `bootstrap_credentials()` function
- `deploy-sprite.sh` — new file, repo root

### Verification
1. `python3 -m pytest tests/ -x -q` — existing tests still pass
2. Test bootstrap locally:
   `BULLPEN_BOOTSTRAP_PASSWORD=test123 python bullpen.py --bootstrap-credentials`
   then verify `~/.bullpen/.env` contains hashed credentials
3. Test idempotency: run bootstrap again, verify no error and no duplicate
