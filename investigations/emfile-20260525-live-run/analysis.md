# EMFILE live-run capture - 2026-05-25

## Preserved artifacts

- Raw sandbox trace bundle: `emfile-watch-20260525-133009.tar.gz`
  - Source inside Microsandbox before preservation: `/tmp/emfile-watch-20260525-133009`
  - SHA-256: `ab1e827d378499934654befa524306c26ac96c3e05760b0fe36ab1783a34a0c8`
- Host runtime FD census: `bullpen-emfile-host-census-20260525-133009.log`
  - Source on host before preservation: `/private/tmp/bullpen-emfile-host-census-20260525-133009.log`
  - SHA-256: `d283eaa15fc7eccb342240a4d1ac793870c8aa8510f9be03a7a583e67421c0d2`
- Bullpen server log snapshot: `bullpen-server.log`
  - Source on host before preservation: `/Users/bill/.bullpen/microsandbox-home/logs/bullpen.log`
  - SHA-256: `9eb2a383bd39b72ca5c713a870a5c129bdd9ade7cc11579b6661501e98c7f8db`
- Clean slot log before the failure window: `slot-1-2026-05-25T13-32-19Z.log`
  - Source on host before preservation: `/Users/bill/aistuff/art-2/.bullpen/logs/slot-1-2026-05-25T13-32-19Z.log`
  - SHA-256: `c60f27ec1289a2423b9e91b21a213b94936555a66e8867fd3b6875a0b978cd2c`
- Clean slot log before the failure window: `slot-5-2026-05-25T13-32-31Z.log`
  - Source on host before preservation: `/Users/bill/aistuff/art-2/.bullpen/logs/slot-5-2026-05-25T13-32-31Z.log`
  - SHA-256: `b7735780e08bbbb1c01e8bd305db4dc05d2a9eae5c6b30c372e170c7521a009b`

No Bullpen application code was patched during this preservation step.

## Run context

- Sandbox: Microsandbox sandbox named `bullpen`
- Bullpen server: running in sandbox, port 8080
- Project: `art-2`
- Ticket observed: `ticket-for-10-I1Te`
- Capture directory in guest: `/tmp/emfile-watch-20260525-133009`
- Guest trace files of particular interest:
  - `strace.5757` and related `strace.575x` files: earliest full-trace EMFILE events found after preservation
  - `strace.5219`: Claude process, early Claude/MCP log EMFILE burst
  - `strace.5218`: Bullpen worker/final write path
  - `guest-census.log`: guest FD and process census loop
- Host census file:
  - `bullpen-emfile-host-census-20260525-133009.log`

## Primary finding

The live capture does not support Bullpen leaking file descriptors.

During the failure window, the Bullpen Python process had only about 7 to 8 open file descriptors. Guest `/proc/sys/fs/file-nr` stayed low, roughly in the 96 to 192 allocated-file range in the relevant excerpts, far below the guest file-max value. The host Microsandbox runtime process was also not near an obvious host FD limit; the host `lsof` census was around 260 to 263 entries near the failure.

The failure instead appears to be a transient sandbox-wide filesystem/backend condition. It affected paths under `/workspace`, `/home/bullpen`, and `/app`, and even affected the monitoring shell when it attempted to read `/home/bullpen/logs/bullpen.log`.

## Strongest syscall evidence

The strongest evidence is not the first chronological EMFILE. It is that `close()` returned `EMFILE` on already-open files:

```text
close(5</workspace/art-2/.bullpen/tasks/ticket-for-10-I1Te.md>) = -1 EMFILE
close(5</home/bullpen/.claude/.credentials.json>) = -1 EMFILE
close(6</app/server/workers.py>) = -1 EMFILE
close(6</app/server/persistence.py>) = -1 EMFILE
```

That is not what ordinary per-process FD exhaustion looks like. It is consistent with Microsandbox passthrough filesystem code surfacing a backend failure during flush/close. In particular, the passthroughfs `do_flush()` path in:

```text
/Users/bill/github/microsandbox/crates/filesystem/lib/backends/passthroughfs/file_ops.rs
```

does a host-side `dup()` before closing the duplicated FD. If that backend `dup()` fails, the guest may observe the failure on close/flush.

## Backbearing: EMFILE chronology

The earliest observed EMFILE in the full preserved trace was not from `close()`, and it was not Bullpen writing the final slot log. The first full-trace EMFILE found after preservation was:

```text
strace.5757:1779715952.615854 openat(AT_FDCWD</workspace/art-2>, "/workspace/art-2/.bullpen/tasks", O_RDONLY|O_NONBLOCK|O_CLOEXEC|O_DIRECTORY) = -1 EMFILE
```

The same instant includes related `statx` and `getdents64` failures in `strace.575x` files while scanning Bullpen directories:

```text
strace.5758:1779715952.615971 statx(... "/workspace/art-2/.bullpen/profiles/.rgignore", ...) = -1 EMFILE
strace.5758:1779715952.616403 getdents64(3</workspace/art-2/.bullpen/profiles>, ...) = -1 EMFILE
```

Shortly afterward, the Claude process hit an early MCP log burst while trying to create/write log files under `/home/bullpen/.cache/claude-cli-nodejs/-workspace-art-2/...`.

From `strace.5219`:

```text
openat(... "/home/bullpen/.cache/claude-cli-nodejs/-workspace-art-2/mcp-logs-bullpen/2026-05-25T13-32-32-165Z.jsonl", O_WRONLY|O_CREAT|O_APPEND, 0666) = -1 EMFILE
mkdirat(... "/home/bullpen/.cache/claude-cli-nodejs/-workspace-art-2/mcp-logs-bullpen", 0777) = -1 EMFILE
```

The same burst then appeared for multiple MCP log directories, including Google Drive, Linear, Google Calendar, Gmail, and Netlify. This places the onset of the filesystem failure before Bullpen's final `_write_log` failure.

The first observed `close() = -1 EMFILE` came later:

```text
strace.5218:1779716006.079121 close(5</workspace/art-2/.bullpen/tasks/ticket-for-10-I1Te.md>) = -1 EMFILE
```

So the precise finding is:

- The first observed EMFILE in the preserved trace was an `openat` on `/workspace/art-2/.bullpen/tasks`.
- The first observed `close()` EMFILE was later.
- `close() = -1 EMFILE` remains the most diagnostic anomaly because ordinary guest FD exhaustion should not make closing an already-open file fail with EMFILE.

## Bullpen-visible failure

The Bullpen-visible failure occurred later during final log writing and exception handling.

From `strace.5218`:

```text
newfstatat(AT_FDCWD</app>, "/workspace/art-2/.bullpen", {st_mode=S_IFDIR|0755, ...}, 0) = 0
mkdirat(AT_FDCWD</app>, "/workspace/art-2/.bullpen/logs", 0777) = -1 EMFILE
newfstatat(AT_FDCWD</app>, "/workspace/art-2/.bullpen/logs", {st_mode=S_IFDIR|0755, ...}, 0) = 0
openat(AT_FDCWD</app>, "/workspace/art-2/.bullpen/logs", O_RDONLY|O_NONBLOCK|O_CLOEXEC|O_DIRECTORY) = 5</workspace/art-2/.bullpen/logs>
newfstatat(5</workspace/art-2/.bullpen/logs>, "", {st_mode=S_IFDIR|0755, ...}, AT_EMPTY_PATH) = 0
getdents64(5</workspace/art-2/.bullpen/logs>, 0xffff68023db0, 32768) = -1 EMFILE
close(5</workspace/art-2/.bullpen/logs>) = 0
openat(AT_FDCWD</app>, "/workspace/art-2/.bullpen/layout.json", O_RDONLY|O_CLOEXEC) = -1 EMFILE
```

This explains how execution got from a failed `mkdirat` to an attempted `layout.json` open:

- Python's `os.makedirs(..., exist_ok=True)` appears to have tolerated the failed `mkdirat` because the directory existed when it was immediately checked with `newfstatat`.
- The first uncaught Bullpen-visible failure in this run was `os.listdir(logs_dir)`, grounded as `getdents64(... logs ...) = -1 EMFILE`.
- During error handling, Bullpen attempted to reread `layout.json`, and that `openat` also failed with `EMFILE`.

## Working theory

This is likely not an application-level FD leak. It looks like a sandbox filesystem/backend failure window where the guest receives `EMFILE` from operations that should not be failing due to the guest process FD table.

The `close() = -1 EMFILE` evidence makes the passthroughfs close/flush path the highest-value diagnostic target. The next useful step is to instrument Microsandbox around passthroughfs file operations, especially:

- `do_flush()` and its host-side `dup()`
- mkdir paths
- open/create paths
- any shared backend resource accounting used by these paths

The instrumentation should log the failing host syscall, errno, target path or inode context where available, host PID/TID, and host FD count at the moment the guest would see `EMFILE`.
