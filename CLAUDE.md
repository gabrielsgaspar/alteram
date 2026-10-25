# CLAUDE.md

@AGENTS.md

## Claude Code specifics

- Use the skills in `.claude/skills/`: `new-case` when adding or checking a case, `prompt-change` whenever anything in `prompts/` changes.
- Use plan mode for any change touching more than one file.
- `.claude/settings.json` blocks reading `.env`. Do not try to work around it.
