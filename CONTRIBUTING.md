# Contributing

## Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Always deployable. Never commit directly. |
| `develop` | Integration branch. All features merge here first. |
| `feature/<name>` | New functionality |
| `fix/<name>` | Bug fixes |
| `docs/<name>` | Documentation only |
| `chore/<name>` | Tooling, dependencies, config |

## Workflow

1. Pick or create a GitHub Issue for the work
2. Branch off `develop`: `git checkout -b feature/my-feature develop`
3. Write code + tests
4. Run `ruff check . && ruff format . && pytest` — all must pass
5. Open a PR into `develop` referencing the Issue
6. Squash merge after review

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add Nequi parser
fix: handle multi-page PDFs in base parser
docs: update setup guide
chore: bump pdfplumber to 0.11
test: add fixtures for Bancolombia parser
```

## Adding a New Bank Parser

See [docs/adding-a-parser.md](docs/adding-a-parser.md).

## Code Style

- Formatter + linter: `ruff`
- Type checker: `mypy`
- Run both before pushing: `ruff check . && ruff format . && mypy src/`
