# Contributing

After the initial repository bootstrap, make changes on focused feature branches and open pull requests. Direct pushes to `main` are guarded by the versioned pre-push hook.

```bash
git config core.hooksPath .githooks
git switch -c feature/short-description
```

Before committing, run:

```bash
ruff check .
pytest
```

Do not commit Spotify client configuration, OAuth tokens, passwords, or content copied from a floppy disk.
