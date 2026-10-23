# Тренди harness engineering: діалог з Claude (вихідний текст)

Збережено дослівно, як отримано, 21.10.2026. Це джерело, а не висновок:
твердження й цифри перевірено окремо у `02-fact-check.md`. Стиль тексту не
правився (тире, стрілки лишились як в оригіналі).

**Питання:** які тренди побудови харнесс процесів при розробці софта? ризики,
виклики, важливі аспекти

**Відповідь:**

Під «harness» зараз зазвичай мають на увазі **harness engineering** — побудову середовища навколо AI-агентів для кодингу. Якщо ти мав на увазі платформу Harness.io (CI/CD), скажи, і я відповім окремо.

## Що це і чому це тренд

Базова формула: агент = модель + harness. Harness — це runtime, що зв'язує LLM зі світом через цикл, інструменти, керування контекстом, засоби безпеки, оркестрацію та точки розширення; як окрему дисципліну її назвали на початку 2026. Еволюцію описують так: prompt engineering (мова) → context engineering (інформація) → harness engineering (середовище). Ключова теза: середня модель із хорошим harness перемагає сильну модель з поганим. Емпіричне підтвердження: команда Viv Trivedy підняла агента з топ-30 у топ-5, змінюючи лише harness.

## Основні тренди

**1. Від інструменту до платформи.** Дослідження 11 production-харнесів (Claude Code, Codex CLI, Gemini CLI, OpenHands, Aider тощо) робить висновок, що у першій половині 2026 coding harness перетворився з інструменту на платформу. SKILL.md-скіли за поширеністю випереджають MCP (9/11 проти 8/11), а ACP є в шести системах і отримав нову роль — хостинг harness. Тобто один harness може запускати інший як бекенд.

**2. Пакування harness.** Плагін фактично є упакованим harness: правила задачі, критерії PASS, контекст, інструменти, workflow, guardrails. Його можна ставити і перевикористовувати між командами.

**3. Цикли замість one-shot.** Підхід, у якому агентом керують повторювані цикли «observe → plan → act → reflect» з stop hooks, тест-ранерами, validation gates і retry-логікою. Звідси й нічні асинхронні прогони.

**4. Помилка агента як сигнал для harness.** Найважливіша звичка — сприймати помилки агента як постійні сигнали: кожен рядок у хорошому AGENTS.md має бути пов'язаний з конкретним збоєм. Робочий цикл: прогнати агента на реальних задачах, побачити збій, класифікувати його, оновити harness і повторити.

**5. Безпека через hooks і політики.** Це означає інтеграцію в coding-agent harness через Hooks, Skills, MCP і CLI. З'являються CI-сканери, що шукають ризики можливостей агентів: shadow capabilities, потрапляння credentials у контекст LLM, eval/subprocess.

## Ризики та виклики

- **Blast radius змін.** За даними Faros, AI дає зміни коду більші, складніші і з ширшим радіусом ураження, ніж раніше. Рев'ю не встигає за обсягом.
- **Безпека коду.** Endor Labs заявляє, що понад 80% AI-згенерованого коду містить вразливості. Це вендорський бенчмарк, тож цифру варто сприймати з поправкою, але напрям проблеми реальний.
- **Довгі задачі й цикли.** Що довша задача, то ймовірніше агент втратить контекст або повторюватиме ті самі фікси. Потрібні явні умови виходу та бюджети.
- **Context rot і застарілий контекст.** Застарілий контекст гірший за відсутній, бо агент впевнено йому слідує. AGENTS.md і скіли потребують підтримки, як код.
- **Prompt injection і автономія.** Чим автономніше працює агент, тим вищі ризики галюцинацій і prompt injection, особливо коли агент читає зовнішні дані через MCP або браузер.
- **Організаційний ризик.** Відповідальність за harness часто розподілена неформально між командами, а ризики некерованого впровадження AI часто невидимі, доки не стануть інцидентами.
- **Якість залишається блокером.** В опитуванні LangChain 57% вже мають агентів у production, а 32% називають якість головним блокером для релізу.

## На що звертати увагу на практиці

1. **Верифікація важливіша за автоматизацію.** Головне в harness engineering — довести, що робота коректна. Тести, типи, лінтери й контракти мають бути детермінованим gate, а не порадою агенту.
2. **Специфікація задачі як контракт:** цілі, non-goals, джерела контексту, критерії приймання, межі дозволів, ризики та обробка збоїв.
3. **Мінімальний контекст.** Давати найменший контекст із високою щільністю сигналу, а не заливати контекстне вікно. Сабагенти з ізольованим контекстом допомагають саме в цьому.
4. **Зворотний зв'язок у правила.** AI code review без шляху назад у правила, тести й контекст — це не harness.
5. **Межі дій.** Це робота з визначення межі між тим, що агент може і чого не може робити: sandbox, scoped permissions, approvals для незворотних дій, audit trail.
6. **Боротьба з ентропією.** Thoughtworks ділить цю роботу на context engineering, архітектурні обмеження і «garbage collection» проти ентропії, тобто регулярне прибирання правил, скілів і мертвого контексту.

Для твого стеку (NestJS/TS, Postgres) найбільший виграш зазвичай дає не складна оркестрація, а жорсткі детерміновані gates: strict-типи, архітектурні лінт-правила на межі модулів, тести міграцій і контрактні тести API. Агент швидко вчиться в такому середовищі, бо отримує чіткий зворотний сигнал.

Sources:
- [Harness Engineering: Anatomy… of Coding Agents (arXiv)](https://arxiv.org/pdf/2609.00006)
- [Faros — Harness engineering](https://www.faros.ai/blog/harness-engineering)
- [Endor Labs — reliable and secure agents](https://www.endorlabs.com/learn/harness-engineering-how-to-make-ai-coding-agents-reliable-and-secure)
- [Addy Osmani — Agent Harness Engineering](https://addyosmani.com/blog/agent-harness-engineering/)
- [LY Corp — 2026 is the Year of the Harness](https://speakerdeck.com/lycorptech_jp/2026-is-the-year-of-the-harness-harness-engineering-strategies-to-save-ai-coding-agents-from-infinite-loops)
- [Harness Engineering Guide](https://www.bestblogs.dev/en/explore/topics/harness-engineering-guide)
- [deepset — Harness engineering](https://www.deepset.ai/blog/harness-engineering)
- [awesome-harness-engineering](https://github.com/walkinglabs/awesome-harness-engineering/wiki)
- [Plandek — agentic software delivery](https://plandek.com/blog/the-transition-to-agentic-software-delivery)
- [Harness vs Context vs Prompt Engineering](https://rajnandan.com/posts/agent-harness-context-prompt-engineering/)
- [Noqta — AI coding loops](https://noqta.tn/en/blog/ai-coding-loops-harness-engineering-iterative-agents-2026)
- [Unimon glossary — Harness Engineering](https://unimon.co.th/en/glossary/harness-engineering)
