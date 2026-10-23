# Project rules for the agent

Project-owned: created once from the harness-dev template, never touched by an upgrade.
Imported by `CLAUDE.md` right after `harness/core/rules.md`; where the two differ, this
file wins. Keep it short; every rule here should point to the failure or the decision it
came from.

## Working language

- Replies to the user: <English>, whatever language the prompt is in, unless the user
  asks for another one. Subagent prompts and reports in the same language.
- Code comments and commit messages: <English>.
- Documents for people: <language of the docs>.

## Data and perimeter

- What counts as personal or confidential data here: <names, contacts, customer IDs...>.
- Where secrets live: <secrets folder, never read by the agent>.
- Scratch folder outside git for temporary files and exports: <sandbox/>.
- The only channels allowed to send data outside: <none / a named script with a scanner>.

## Approvals specific to this project

- <actions that need a "yes" on top of the generic list, e.g. closing a ticket, running
  a data migration, publishing to the wiki>

## Servers and environments

- <how to reach machines, which wrappers to use, what never to run there>

## Exempt from the generic rules

- Text style does not apply to: <folders with their own typography, vendored docs>.
