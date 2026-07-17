# AGENTS.md

## Cursor Cloud specific instructions

Lutris is a single GTK3 Python desktop application (a Linux game launcher). There is no
backend server in this repo. Standard commands live in the `Makefile`, `pyproject.toml`,
`INSTALL.rst`, and `CONTRIBUTING.md`; refer to those. Notes below are the non-obvious
gotchas for running/testing in the Cloud VM.

### Running the app (important gotcha)

`bin/lutris` deliberately strips every `sys.path` entry under `/home` (see the
`LUTRIS_ALLOW_LOCAL_PYTHON_PACKAGES` check at the top of the file). Python dependencies
here are installed with user-level pip into `~/.local/lib/...`, so the app will fail with
`No module named 'PIL'` (or similar) unless you set that variable. Always run with:

```bash
DISPLAY=:1 LUTRIS_ALLOW_LOCAL_PYTHON_PACKAGES=1 ./bin/lutris -d
```

- A GUI display is available at `DISPLAY=:1` (use it for manual/GUI testing).
- `~/.local/bin` is added to `PATH` in `~/.bashrc` so `ruff`, `mypy`, and `nose2` resolve.
- Runtime data (SQLite `pga.db`, downloaded runners) lives under
  `~/.local/share/lutris` and `~/.cache/lutris`; delete these to reset app state.

### Expected non-fatal errors in this headless VM

These are logged on startup but do NOT indicate a broken environment: `No GPU available`,
`Vulkan is not available`, `i386 lib... missing` (32-bit GL/Vulkan/gnutls), and the
`org.freedesktop.portal.Settings` D-Bus `UnknownMethod` (no desktop portal). They only
affect actually launching games, not the client itself.

### Lint / test / run quick reference

- Lint/static checks: `make sc` (runs ruff format check, `ruff check`, mypy, compileall,
  annotation check, and `.po` validation). mypy is filtered through `mypy-baseline`.
- Tests: `make test` (or `nose2 --exclude-ci`, which is what CI runs). `make test` first
  removes `tests/fixtures/pga.db`.
- Run: see the command above.
