# Перевірка тверджень з `2026-10-21-trends-dialogue.uk.md`

Перевірено 21.10.2026: цитовані сторінки відкрито напряму, метадані arXiv
звірено через API arXiv. Не знайдено чотири джерела: пост rajnandan.com,
глосарій unimon, слайди LY Corp на Speaker Deck і сторінку Endor Labs про
CI-сканери.

## Підсумок

Загальна картина у відповіді правильна, і головні цифри реальні: дослідження
11 harness, 57% і 32% LangChain, перехід з top-30 у top-5. Але приблизно
половина тверджень мала неточну атрибуцію, а одне не підтвердилось зовсім.
Висновки дизайну (`05-design.md`) спираються лише на тези, підтверджені
нижче, і на власні збої пілотного проєкту (його каталог збоїв).

## Твердження за твердженням

| № | Твердження | Вердикт | Що насправді | Джерело |
|---|---|---|---|---|
| 1 | Агент = модель + harness; harness як runtime з шести складників; дисципліна з початку 2026; еволюція prompt, context, harness | частково | Формула є в Osmani (19.04.2026). Визначення з шести складників і "початок 2026" - з анотації статті arXiv 2609.00006. Термін зазвичай приписують Mitchell Hashimoto (лютий 2026). Ланцюжок prompt, context, harness є лише у вторинних блогах | addyosmani.com/blog/agent-harness-engineering/ ; arxiv.org/abs/2609.00006 |
| 2 | Середня модель з добрим harness краща за сильну з поганим; top-30 у top-5 | частково | top-30 у top-5 - пост LangChain (Vivek Trivedy, 17.02.2026): deepagents-cli на Terminal Bench 2.0, бал з 52,8 до 66,5, модель та сама. Теза про середню і сильну модель - афоризм Osmani; емпірично близько до даних Faros: на 211 задачах відкриті моделі з оптимізованим harness дорівнювали фронтирним або випереджали їх | langchain.com/blog/improving-deep-agents-with-harness-engineering ; faros.ai/blog/harness-engineering |
| 3 | 11 harness; інструмент став платформою; SKILL.md 9/11, MCP 8/11, ACP у шести | підтверджено | Стаття "Harness Engineering: Anatomy, Architecture, and Evolution of Coding Agents" (Barbaste, Darrigol, Vu, Wiltberger), подана 15.07.2026, друге розширене видання. Усі числа є в анотації | arxiv.org/abs/2609.00006 |
| 4 | Плагін = запакований harness | частково | Першоджерела з таким формулюванням немає; гайди описують плагіни Claude Code як пакет skills, hooks, MCP і правил. Правдоподібний висновок автора, "PASS-критерії" нічим не підкріплені | capitalandcompute.net/blog/claude-code-harness-guide/ |
| 5 | Цикл observe, plan, act, reflect зі stop hooks, тестами, gates, retry | частково | noqta (13.04.2026) пише про feedback loops і автоматичні тести після кожного циклу, але не про цей цикл і не про stop hooks; навпаки, радить feedback loops замість gates. Слайдів LY Corp не знайдено. Механізм, схожий на stop hook, описує Osmani (Ralph Loop) | noqta.tn/blog/harness-engineering-ai-agents-production-ready-2026 |
| 6 | Збій агента як постійний сигнал; кожен рядок AGENTS.md повʼязаний зі збоєм | підтверджено | Обидві тези є в Osmani (розділ про "ratchet"). Цикл там з двох кроків: помилка, зміна harness; крок "класифікувати" додав автор відповіді | addyosmani.com/blog/agent-harness-engineering/ |
| 7 | Безпека через Hooks, Skills, MCP, CLI; CI-сканери shadow capabilities, credentials у контексті, eval/subprocess (Endor) | частково | Чотири точки інтеграції Endor називає (реклама їхнього продукту). Про CI-сканери такого роду Endor не пише; схоже роблять сканери skills інших вендорів (AgentGuard, Cisco Skill Scanner, JFrog); про секрети в контексті пише Pillar Security | endorlabs.com/learn/harness-engineering-how-to-make-ai-coding-agents-reliable-and-secure |
| 8 | Faros: зміни більші, складніші, ширший радіус ураження; рев'ю не встигає | підтверджено якісно | Пост посилається на "AI Engineering Report 2026"; цифр щодо розміру змін і відставання рев'ю в ньому немає | faros.ai/blog/harness-engineering |
| 9 | Endor: понад 80% AI-коду з вразливостями | підтверджено, з застереженням | Вендорний бенчмарк Endor: 200 задач, 77 класів вразливостей, функціонально коректний код. Інша сторінка Endor цитує Veracode 2025: 45% зразків не пройшли перевірки безпеки | endorlabs.com |
| 10 | LangChain: 57% мають агентів у продакшені, 32% - якість головний барʼєр | підтверджено | 57,3% і 32% (затримка 20%); 1340 респондентів, опитування 18.11-02.12.2025, тобто дані кінця 2025 | langchain.com/state-of-agent-engineering |
| 11 | Thoughtworks: context engineering, архітектурні обмеження, прибирання ентропії | частково | Три категорії - нотатка Birgitta Böckeler на martinfowler.com (17.02.2026), її групування тексту OpenAI про harness engineering, а не фреймворк Thoughtworks | martinfowler.com/articles/exploring-gen-ai/harness-engineering-memo.html |
| 12 | Застарілий контекст гірший за відсутній | не підтверджено | У жодному джерелі немає. Найближче: дослідження ETH Zurich, де згенеровані LLM файли AGENTS.md знижували успішність на 2-3% і здорожували інференс на 20% з гаком; ідеться про надлишковий, а не застарілий контекст | todatabeyond.substack.com/p/do-agentsmdclaudemd-files-help-coding |

**Невідповідність стеку.** Відповідь виходить зі стеку NestJS/TS + Postgres.
Пілотний проєкт - Python FastAPI + React/TS + Postgres з моделями на власних
серверах у контурі; поради, привʼязані до хмарних продуктів (Endor AURI), тут
не застосовні напряму.

## Що з цього взято в дизайн

- **Детерміновані перевірки замість порад агенту** (тези 6, практика 1):
  принцип 1 дизайну.
- **Кожне правило повʼязане зі збоєм** (теза 6, Osmani): принцип 2, перелік
  `03-incidents.md` як обґрунтування кожної перевірки.
- **Прибирання ентропії** (теза 11): шар 4, щомісячне прибирання.
- **Надлишковий контекст шкодить** (ETH Zurich, теза 12 у виправленому
  вигляді): SessionStart дає коротку довідку, а не весь CONTEXT.md.
- **Не взято:** 80% вразливостей як аргумент (вендорна цифра), CI-сканери
  Endor (не підтверджено), цикл observe-plan-act-reflect як готова схема.
