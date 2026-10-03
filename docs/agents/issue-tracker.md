---
type: instructions
status: current
created: 2026-10-03
updated: 2026-10-03
tags: [get-brolls, agents, github]
---

# Issue tracker: GitHub

Specs and tickets live in [kovr33k/get-brolls](https://github.com/kovr33k/get-brolls/issues). Use the GitHub CLI and pass `--repo kovr33k/get-brolls` explicitly for issue operations. This project also has an upstream remote; the selected tracker belongs to the origin repository.

## Operations

- Create: `gh issue create --repo kovr33k/get-brolls --title "TITLE" --body-file BODY_FILE`.
- Read: `gh issue view NUMBER --repo kovr33k/get-brolls --comments`.
- List: `gh issue list --repo kovr33k/get-brolls --state open --json number,title,body,labels`.
- Comment: `gh issue comment NUMBER --repo kovr33k/get-brolls --body-file BODY_FILE`.
- Label: `gh issue edit NUMBER --repo kovr33k/get-brolls --add-label LABEL` or `--remove-label LABEL`.
- Close: `gh issue close NUMBER --repo kovr33k/get-brolls`.

Use a UTF-8 temporary body file with actual newlines for multiline text. Follow the public-reporting rules in [AGENTS.md](../../AGENTS.md#dependências-e-arquivos-privados).

When a skill says to publish a spec or ticket, create a GitHub issue. When it says to fetch a ticket, read its issue and comments. Search for an existing matching issue before creating a duplicate.

`/to-spec` publishes an accepted specification with `ready-for-agent`; an unresolved draft remains a draft until its required confirmation is received. There is no configured `/triage` label mapping because that skill is not installed.

## Pull requests as a triage surface

**PRs as a request surface: no.**

GitHub issues and pull requests share a number space. Resolve an ambiguous reference as a pull request first, then as an issue. Pull requests are not feature-request intake under this configuration.
