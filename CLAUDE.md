# CLAUDE.md

@AGENTS.md

## Claude Code specifics

- Shared project settings: `.claude/settings.json`. Personal overrides go
  to `.claude/settings.local.json` (gitignored — never commit).
- No project subagents or hooks live here yet. They arrive with the
  first source file, together with the language's formatter hook.
