# EMFILE transition repro capture - 2026-05-25

## Preserved artifacts

- Raw sandbox trace bundle: `emfile-watch-20260525-135032.tar.gz`
  - Source inside Microsandbox before preservation: `/tmp/emfile-watch-20260525-135032`
  - SHA-256: `5af17118003e82abbc10aee2989f38214fed9e28e9687d31aa9c6e1e443e1172`
- Host runtime FD census: `bullpen-emfile-host-census-20260525-135032.log`
  - Source on host before preservation: `/private/tmp/bullpen-emfile-host-census-20260525-135032.log`
  - SHA-256: `7923f84c79281e658712193f824b84e26f2e38be046f2d77ef446a612c1a48c2`
- Bullpen server log snapshot: `bullpen-server.log`
  - Source on host before preservation: `/Users/bill/.bullpen/microsandbox-home/logs/bullpen.log`
  - SHA-256: `86b8777ae744a4910aaa905cd7baa5a9ddcb21fc77b64ae410f546eed1371eb4`
- Clean slot log before failure: `slot-1-2026-05-25T13-52-42Z.log`
  - Source on host before preservation: `/Users/bill/aistuff/art-2/.bullpen/logs/slot-1-2026-05-25T13-52-42Z.log`
  - SHA-256: `e56be675dc9a681609c8dbd0313096e261d2eccf7510b2c903a2367e38b35e30`
- Clean slot log before failure: `slot-3-2026-05-25T13-52-53Z.log`
  - Source on host before preservation: `/Users/bill/aistuff/art-2/.bullpen/logs/slot-3-2026-05-25T13-52-53Z.log`
  - SHA-256: `ab839401f9ba68e6e414d0375238c2f6debdbf0f8127aaebd32aef9ebe2d1262`

No Bullpen application code was patched during this capture.

## Run context

- Sandbox: Microsandbox sandbox named `bullpen`
- Bullpen server: PID 301 inside the sandbox
- Project: `art-2`
- Ticket observed: `testing-again-Fm1h`
- Capture directory in guest: `/tmp/emfile-watch-20260525-135032`
- Monitors armed before the ticket was dropped:
  - `strace -ttt -yy -s 256 -f -ff` attached to Bullpen PID 301 and existing threads
  - canary loop probing `/workspace/art-2/.bullpen/tasks`, `/workspace/art-2/.bullpen/logs`, `/app/server/workers.py`, and `/home/bullpen/logs/bullpen.log`
  - guest process/FD census
  - host runtime FD census

## Primary finding

This capture cleanly shows a transition from working filesystem operations to an EMFILE-clogged state.

The canary was green immediately before the transition:

```text
1779717174.154337 list_tasks ok count=20
1779717174.154337 list_logs ok count=133
1779717174.154337 read_app ok bytes=1
1779717174.154337 read_home ok bytes=1
1779717174.368931 list_tasks ok count=20
1779717174.368931 list_logs ok count=133
1779717174.368931 read_app ok bytes=1
1779717174.368931 read_home ok bytes=1
```

Then all four independent probes failed together:

```text
1779717174.583412 list_tasks errno=24 Too many open files path=/workspace/art-2/.bullpen/tasks
1779717174.583412 list_logs errno=24 Too many open files path=/workspace/art-2/.bullpen/logs
1779717174.583412 read_app errno=24 Too many open files path=/app/server/workers.py
1779717174.583412 read_home errno=24 Too many open files path=/home/bullpen/logs/bullpen.log
```

The canary continued seeing EMFILE until `1779717228.008483`, then recovered at `1779717228.213240`. The clogged window observed by the canary was therefore about 53.6 seconds.

## First actual EMFILE syscall

Filtering the strace bundle for actual syscall failures containing ` = -1 EMFILE`, the first observed EMFILE was a `close()` failure:

```text
strace.14298:1779717174.565451 close(3</app/server/__init__.py>) = -1 EMFILE (Too many open files)
strace.14298:1779717174.566547 close(4</app/server/mcp_tools.py>) = -1 EMFILE (Too many open files)
strace.14298:1779717174.566798 close(3</app/server/mcp_tools.py>) = -1 EMFILE (Too many open files)
```

That is about 18 ms before the canary recorded the first all-mount EMFILE failure at `1779717174.583412`.

This is a stronger finding than the previous capture: in this run, after excluding trace lines that merely contain the string `EMFILE` inside Python source text, the first actual EMFILE-returning syscall is `close()`.

## FD counts during transition

The guest census around the transition does not support Bullpen or the guest global file table being exhausted:

```text
1779717174.186936 file_nr=96 0 395743 bullpen_fd=7
1779717174.688904 file_nr=128 0 395743 bullpen_fd=7
1779717175.189885 file_nr=128 0 395743 bullpen_fd=7
```

The Claude process had roughly 29 to 30 FDs, the proxy had 24, and the strace process had about 32. These are small counts relative to the configured limits.

The host runtime FD census in this preserved file starts after the canary transition and therefore should not be used as transition-time proof. It still shows the Microsandbox runtime process at ordinary counts later in the run, roughly 221 to 260 `lsof` rows, not a runaway host-FD condition.

## Bullpen-visible failure

The app-visible failure in this run was the original `os.makedirs` shape:

```text
Exception in thread Thread-375 (_run_agent):
Traceback (most recent call last):
  File "/app/server/workers.py", line 2359, in _run_agent
  File "/app/server/workers.py", line 3082, in _write_log
  File "<frozen os>", line 215, in makedirs
  File "<frozen os>", line 225, in makedirs
OSError: [Errno 24] Too many open files: '/workspace/art-2/.bullpen'
```

Then Bullpen attempted error handling and hit the familiar layout read failure:

```text
File "/app/server/workers.py", line 331, in _load_layout
File "/app/server/persistence.py", line 28, in read_json
OSError: [Errno 24] Too many open files: '/workspace/art-2/.bullpen/layout.json'
```

The corresponding final strace window includes:

```text
strace.14282:1779717209.324263 newfstatat(AT_FDCWD</app>, "/workspace/art-2/.bullpen", ...) = -1 EMFILE
strace.14282:1779717209.324707 mkdirat(AT_FDCWD</app>, "/workspace/art-2/.bullpen", 0777) = -1 EMFILE
strace.14282:1779717209.324969 newfstatat(AT_FDCWD</app>, "/workspace/art-2/.bullpen", ...) = -1 EMFILE
strace.14282:1779717209.325194 openat(AT_FDCWD</app>, "/workspace/art-2/.bullpen/layout.json", O_RDONLY|O_CLOEXEC) = -1 EMFILE
```

## Additional observation

During the clogged state, a fresh `msb exec` also failed before reaching the requested command:

```text
error: failed to exec "docker-entrypoint.sh"
  -> resource limit: spawn "docker-entrypoint.sh": No file descriptors available (os error 24) (EMFILE)
```

Running the diagnostic exec with a raised `--rlimit nofile=1048576` succeeded, which allowed the capture to be read and preserved.

## Working theory

This run strengthens the passthroughfs close/flush theory:

- the transition was captured from clean canary success to global canary EMFILE,
- the first actual EMFILE syscall in the strace was `close()`,
- the affected paths spanned `/workspace`, `/app`, and `/home/bullpen`,
- Bullpen itself had only about 7 FDs,
- guest `file_nr` was tiny compared with `file-max`.

The highest-value next diagnostic remains instrumentation inside Microsandbox passthroughfs around the close/flush path, especially the host-side `dup()` in `do_flush()`, plus nearby mkdir/open/stat paths. The key question is what host-side operation or backend resource state makes the guest see EMFILE on `close()`.

