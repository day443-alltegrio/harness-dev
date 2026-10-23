# Harness engineering: challenges, risks, trends, and practice

*As of 22.10.2026*

Harness engineering is the design of the environment around an AI agent: context, constraints, sensors, verification loops, and action boundaries. The main takeaway: the largest gains come from deterministic checks and enforced verification; the weakest link remains checking functional behaviour.

## Sources and assessment of the source set

This overview draws on primary sources: [OpenAI](https://openai.com/index/harness-engineering/) (Ryan Lopopolo), [Anthropic](https://anthropic.com/engineering/harness-design-long-running-apps) (Prithvi Rajasekaran, [Managed Agents](https://anthropic.com/engineering/managed-agents) team), [Thoughtworks](https://martinfowler.com/articles/harness-engineering.html) (Birgitta Böckeler), [LangChain](https://blog.langchain.com/improving-deep-agents-with-harness-engineering) (Vivek Trivedy), and [Simon Willison](https://simonwillison.net/2025/Oct/22/living-dangerously-with-claude/) on security.

Much of the wider source set is secondary: glossaries, aggregators, vendor blogs. The core claims are transmitted correctly, with one clarification: the "from top 30 into top 5" case belongs to LangChain - deepagents-cli rose from 52.8% to 66.5% on Terminal Bench 2.0 through harness changes alone; the model (gpt-5.2-codex) was unchanged. Figures from Endor Labs and other vendors are directional, not established fact.

## 1. Core challenges

- **Long-running tasks and "amnesia".** Per Anthropic, every new context window is amnesia. Working remedies: decompose into manageable units and pass context between sessions through structured artifacts.
- **Agents misjudge their own work.** Agents overstate results, especially on subjective tasks such as design. In LangChain traces the most common failure: the agent reread its own code, decided it was fine, and stopped.
- **Behaviour harness remains unsolved.** Böckeler calls checking functional behaviour the "elephant in the room". Green AI-authored tests plus coverage demand too much trust in AI-generated tests. A wrong diagnosis, over-engineering, and a misunderstood task are not caught reliably by any sensor.
- **The harness ages as the model changes.** Every component encodes assumptions about what the model cannot do alone. With Opus 4.6, Anthropic dropped context resets and kept only compaction.
- **Entropy.** The agent reproduces existing patterns, including bad ones. The OpenAI team first spent 20% of every Friday on manual cleanup of "AI slop"; that did not scale.
- **How to measure harness quality itself.** If sensors never fire, is that high quality or blind detectors? The field needs a code-coverage analogue for the harness.
- **Legacy code.** The harness is most needed where it is hardest to build - in systems with heavy tech debt.
- **Human attention is the bottleneck.** At OpenAI, as throughput grew, human QA became the constraint.

## 2. Core risks

- **Lethal trifecta.** Willison describes the conjunction of three conditions: access to private data, exposure to untrusted content, and the ability to communicate externally. Coding agents are useful precisely because they have all three. His conclusion: the only convincing mitigation is a sandbox; network control cuts the exfiltration channel.
- **Scale of the problem.** Per CSA Labs, only 11% of 100 commercial agents cleared a basic security bar. The source is secondary; the figure is indicative.
- **Harness overfitting.** Changes tuned to one task hurt generalization and cause regressions on other tasks.
- **Doom loops.** An agent may retry more than ten minor variations of the same broken approach.
- **Unknowns over the long haul.** Even OpenAI does not know how the architectural integrity of an agent-generated system evolves over years.
- **Blind copying of other teams' practices.** OpenAI's own authors call their minimal merge gates irresponsible at low throughput. An autonomous end-to-end loop depends on a specific repository's tooling and does not transfer without similar investment.
- **Template drift.** Harness templates will face the versioning problems of service templates, possibly worse, because non-deterministic guides and sensors are harder to test.
- **Change volume.** AI produces larger, more complex changes with a wider blast radius, and review cannot keep up with the volume.

## 3. Core trends

- **Shift in the engineer's role.** OpenAI's formula: humans steer, agents execute. The team designs the environment, states intent, and builds feedback loops. Outcome: about a million lines of code, ~1500 PRs, 3.5 PRs per engineer per day.
- **Multi-agent setups with a dedicated evaluator.** At Anthropic, three agents (planner, generator, evaluator) built full-stack applications in multi-hour sessions. Configuring a skeptical evaluator is far easier than forcing the generator to assess itself honestly.
- **Harness as a platform.** Anthropic launched Managed Agents, where the session is a context object outside the model window, and interfaces must outlive concrete implementations. In August 2026 OpenAI presented Codex as a platform with an open agent harness.
- **Agents improve the harness.** LangChain automated failure analysis: parallel agents dissect traces; a lead agent synthesizes findings and proposes changes.
- **Return of deterministic sensors.** Mutation and structural testing are seeing a revival, and LSPs are being wired into agents.
- **Harness templates.** Böckeler predicts teams will choose stacks partly by which harnesses already exist for them.
- **Agent legibility.** "Boring" technologies are easier for agents to model. OpenAI sometimes rewrote small dependencies in-house for that reason.
- **Sandbox as the default.** An authorization proxy is added that injects credentials outside the sandbox, so secrets never live inside.

## 4. Practical aspects and experience

### Context and knowledge

- **AGENTS.md is a map, not an encyclopedia.** A large file at OpenAI failed: it crowded out the task, rotted quickly, and was not checked. The working pattern: an AGENTS.md of ~100 lines with links, a docs/ tree as the system of record, freshness enforced by linters and a "doc-gardening" agent.
- **What the agent cannot see does not exist.** Knowledge in Google Docs, chats, or people's heads is unavailable to the agent. Architectural decisions from discussions must land in the repository.
- **Describe the environment up front.** LangChain maps directories and available tools at start-up, because unaided context discovery is error-prone.

### Constraints and sensors

- **Invariants, not micromanagement.** At OpenAI each domain is split into fixed layers with strictly enforced dependency directions. Custom linter messages include fix instructions for the agent.
- **Guides and sensors together.** Feedback alone yields an agent that repeats mistakes; rules alone yield an agent that never learns whether they fired.
- **Shift checks left.** Cheap deterministic checks on every change; expensive inferential ones (AI review, mutation tests) later in the pipeline.
- **Steering loop.** When a problem recurs, improve guides and sensors so it becomes less likely.

### Execution

- **Enforced build -> verify loop.** LangChain uses a hook that intercepts the agent before exit and forces verification against the specification. Also: a loop detector by file-edit count, and time-budget warnings.
- **Reasoning sandwich.** Maximum reasoning on planning and verification, lower on implementation. Running entirely at xhigh yielded only 53.9% because of timeouts.
- **Long tasks: start small.** A progress file, a task list with boolean flags, a start ritual that reads both, one unit of work per session. Test: if a fresh context cannot reconstruct the project from disk, it is not a harness - it is a long prompt.
- **The planner states "what" and "why", not "how".** Implementation detail from the planner cascaded errors. Before implementation, the evaluator agrees with the generator on a "sprint contract" with testable criteria.
- **The application is transparent to the agent.** OpenAI runs the application separately for each git worktree with a temporary stack of logs, metrics, and traces. That makes requirements such as service start time verifiable.

### Maintenance and people

- **Revisit the harness when the model changes.** The same harness on Claude Opus 4.6 scored 59.6% because the Claude-side improvement loop had not been run.
- **Continuous garbage collection.** Background jobs hunt deviations from "golden principles" and open small refactoring PRs, most of which are reviewed in under a minute.
- **Put humans where they matter most.** The goal of a harness is not to remove people, but to concentrate their contribution on the highest-value points.

## Conclusion

1. Harness engineering is a revival of classic engineering disciplines (types, architectural fitness functions, CI, observability), but now the consumer is an agent, and they are needed from day one.
2. The largest gains come from deterministic sensors and enforced verification. The largest unsolved problem is behaviour checking and correct task understanding; here the human remains the key sensor.
3. A harness is living code: it rots, overfits, and goes stale with new models. It needs an owner, versioning, and regular cleanup.
4. Security is architectural - sandbox, network allowlists, secrets outside the agent - not prompt-based.

### For NestJS / TS / Postgres

- strict TS and dependency-cruiser or ESLint boundaries for module edges, with instruction-style messages for the agent;
- a separate temporary database per worktree;
- migration tests and API contract tests as gates;
- structured logs accessible to the agent;
- a short AGENTS.md map plus docs/ with plans and tech debt.

## Sources

- [OpenAI - Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/)
- [Birgitta Böckeler - Harness engineering for coding agent users (martinfowler.com)](https://martinfowler.com/articles/harness-engineering.html)
- [Anthropic - Harness design for long-running application development](https://anthropic.com/engineering/harness-design-long-running-apps)
- [Anthropic - Scaling Managed Agents](https://anthropic.com/engineering/managed-agents)
- [InfoQ - Anthropic three-agent harness](https://infoq.com/news/2026/04/anthropic-three-agent-harness-ai/)
- [LangChain - Improving Deep Agents with harness engineering](https://blog.langchain.com/improving-deep-agents-with-harness-engineering)
- [LangChain - How to choose the right sandbox for your agent](https://www.langchain.com/blog/how-to-choose-the-right-sandbox-for-your-agent)
- [Simon Willison - Living dangerously with Claude](https://simonwillison.net/2025/Oct/22/living-dangerously-with-claude/)
- [Software Mansion - Security for coding agents](https://agentic-engineering.swmansion.com/becoming-productive/security/)
- [Zentera - Lethal trifecta for AI agents](https://www.zentera.net/blog/lethal-trifecta-ai-agents)
- [Mejba Ahmed - Anthropic's long-running agent harness](https://www.mejba.me/blog/anthropic-long-running-agent-harness)
- [Understanding Data - Generator-Evaluator harness design](https://understandingdata.com/posts/generator-evaluator-harness-design/)
- [First AI Movers - Harness design is becoming the real moat](https://radar.firstaimovers.com/harness-design-long-running-ai-agents)
- [Ken Huang - From Software Engineering to Harness Engineering](https://kenhuangus.substack.com/p/from-software-engineering-to-harness)
- [ZenML - Harness engineering for agentic coding systems](https://www.zenml.io/llmops-database/harness-engineering-for-agentic-coding-systems)
