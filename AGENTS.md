# AGENTS.md

## Project overview

Single-script Python tool that extracts Youdao Cloud Notes Mac client local SQLite data into Obsidian-compatible Markdown files. The same repo doubles as a Claude Code skill (`claude-code-skill/youdao-export/`).

## Commands

```bash
# Run the migration (default: auto-detect account, output to ~/Desktop/obsidian)
python3 claude-code-skill/youdao-export/scripts/youdao_migrate.py

# With options
python3 claude-code-skill/youdao-export/scripts/youdao_migrate.py --account user@email.com --output ~/Documents/Vault

# With OSS image upload
python3 claude-code-skill/youdao-export/scripts/youdao_migrate.py --oss --output ~/Documents/Vault
```

## Dependencies

```bash
pip3 install -r requirements.txt
# or: pip3 install beautifulsoup4 oss2
```

## Architecture

- **Entry point**: `claude-code-skill/youdao-export/scripts/youdao_migrate.py` (~800 lines, no modules)
- Reads 3 SQLite databases from the client data directory (Linux: `~/.config/ynote-desktop/`, macOS: `~/Library/Containers/ynote-desktop/...`):
  - `<account>.db` — folder tree (`note_book`) + note metadata (`note`) + resource cache (`resource`)
  - `<account>-content.db` — old-editor body (`contenttable`)
  - `<account>-search.db` — fallback body source
- Body extraction priority: local file (new editor JSON blocks) → contenttable (old editor) → search.db
- New editor JSON block types (field `"6"`): `p`, `h`, `co`, `t`, `im`, `l`, `q`, `hr`; inline styles in field `"9"`: `b`, `i`, `s`, `u`, `li`, `il`
- Output: `.md` files with YAML frontmatter, preserving original folder hierarchy

## Constraints

- **Cross-platform** — auto-detects default data path on macOS and Linux. Use `--base-dir` to override.
- **No tests** — verify manually by running the script and checking output
- **No linting/build** — plain Python script, no toolchain
- The script opens multiple SQLite connections; no concurrency concerns
- OSS upload requires env vars: `OSS_BUCKET`, `OSS_ACCESS_KEY_ID`, `OSS_ACCESS_KEY_SECRET` (or `~/.ossutilconfig`). Config validation happens in `main()`, not inside `load_oss_config()` — the function returns `None` on failure.
- `oss2` is imported lazily inside `load_oss_config()` — script runs fine without it unless `--oss` is used.
- `--oss` is mandatory when resources exist. Without it, the script exits with an error before any export.
