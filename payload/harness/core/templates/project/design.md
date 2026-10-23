# Harness of this project: decisions

Project-owned. The generic design is `harness/core/docs/design.md`; this file records
only what this project decided on top of it. Change it in the same change as
`harness/config/gates.json`.

## Level and gates

Adoption level (design.md, section 9): <L1>. Gate states live in
`harness/config/gates.json`; the reason for each inactive gate is here.

| Gate | State | Why | When it changes |
|---|---|---|---|
| QG3 deploy check | in progress | <deploy-hooks.sh not filled yet> | <after the first gated deploy> |

## Switched off on purpose (trade-offs)

| What | Why not now | What we pay | When to switch on |
|---|---|---|---|
| <QG4 candidate on a port> | <one service, one developer> | <a broken service is visible for minutes> | <before production> |

## Decisions

| Date | Question | Decision | Who |
|---|---|---|---|

## Risks

| Risk | Consequence | What we do |
|---|---|---|
| Hooks can be bypassed (a script file, another language) | a wrong command changes a server | the main gates run outside the agent; server-side permissions before production |
