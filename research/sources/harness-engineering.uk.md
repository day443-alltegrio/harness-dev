# Harness engineering: виклики, ризики, тренди та практика

*Станом на 22.10.2026*

Harness engineering — це проєктування середовища навколо AI-агента: контексту, обмежень, сенсорів, циклів верифікації та меж дій. Головний висновок: найбільший виграш дають детерміновані перевірки й примусова верифікація, а найслабше місце — перевірка функціональної поведінки.

## Джерела та оцінка вихідної добірки

Огляд спирається на першоджерела: [OpenAI](https://openai.com/index/harness-engineering/) (Ryan Lopopolo), [Anthropic](https://anthropic.com/engineering/harness-design-long-running-apps) (Prithvi Rajasekaran, команда [Managed Agents](https://anthropic.com/engineering/managed-agents)), [Thoughtworks](https://martinfowler.com/articles/harness-engineering.html) (Birgitta Böckeler), [LangChain](https://blog.langchain.com/improving-deep-agents-with-harness-engineering) (Vivek Trivedy) і [Simon Willison](https://simonwillison.net/2025/Oct/22/living-dangerously-with-claude/) щодо безпеки.

Значна частина вихідної добірки вторинна: глосарії, агрегатори, вендорські блоги. Головні тези передані правильно, з одним уточненням: кейс «з топ-30 у топ-5» належить LangChain — deepagents-cli піднявся з 52.8% до 66.5% на Terminal Bench 2.0 лише за рахунок harness, модель (gpt-5.2-codex) не змінювали. Цифри від Endor Labs та інших вендорів — орієнтир, а не факт.

## 1. Основні виклики

- **Довгі задачі та «амнезія».** За Anthropic, кожне нове контекстне вікно — це амнезія. Робочі рішення: декомпозиція на керовані частини і передача контексту між сесіями через структуровані артефакти.
- **Агент погано оцінює власну роботу.** Агенти завищують результати, особливо в суб'єктивних задачах на кшталт дизайну. У trace-ах LangChain найчастіший збій: агент перечитав свій код, вирішив, що все гаразд, і зупинився.
- **Behaviour harness досі не розв'язаний.** Böckeler називає перевірку функціональної поведінки «слоном у кімнаті». Зелені AI-тести плюс покриття вимагають забагато довіри до AI-згенерованих тестів. Неправильний діагноз, оверінжиніринг і хибно зрозумілу задачу не ловить надійно жоден сенсор.
- **Harness старіє разом зі зміною моделі.** Кожен компонент кодує припущення про те, чого модель не вміє сама. З Opus 4.6 Anthropic відмовився від context resets і залишив лише compaction.
- **Ентропія.** Агент відтворює наявні патерни, включно з поганими. Команда OpenAI спершу витрачала щоп'ятниці 20% тижня на ручне прибирання «AI slop», і це не масштабувалося.
- **Як виміряти якість самого harness.** Якщо сенсори ніколи не спрацьовують, це висока якість чи сліпі детектори? Потрібен аналог code coverage для harness.
- **Legacy-код.** Harness найбільше потрібен там, де його найважче побудувати — у системах з великим техборгом.
- **Людська увага — вузьке місце.** У OpenAI з ростом пропускної здатності вузьким місцем став людський QA.

## 2. Основні ризики

- **Lethal trifecta.** Willison описує поєднання трьох умов: доступ до приватних даних, контакт із недовіреним контентом і здатність до зовнішньої комунікації. Coding-агенти корисні саме тому, що мають усі три. Його висновок: єдине переконливе рішення — sandbox, а контроль мережі відрізає канал ексфільтрації.
- **Масштаб проблеми.** За оцінкою CSA Labs, лише 11% зі 100 комерційних агентів пройшли базову планку безпеки. Джерело вторинне, цифра індикативна.
- **Оверфітинг harness.** Зміни, підігнані під конкретну задачу, шкодять узагальненню і дають регресії на інших задачах.
- **Doom loops.** Агент може понад 10 разів пробувати дрібні варіації того самого зламаного підходу.
- **Невідомість на довгій дистанції.** Навіть OpenAI не знає, як еволюціонує архітектурна цілісність агентно-згенерованої системи протягом років.
- **Сліпе копіювання чужих практик.** Мінімальні merge gates OpenAI самі автори називають безвідповідальними при низькій пропускній здатності. Автономний end-to-end цикл залежить від інструментів конкретного репозиторію і без схожих інвестицій не переноситься.
- **Дрейф шаблонів.** Harness templates матимуть проблеми версіонування service templates, можливо гірші, бо недетерміновані guides і sensors важче тестувати.
- **Обсяг змін.** AI дає більші й складніші зміни з ширшим радіусом ураження, і рев'ю не встигає за обсягом.

## 3. Основні тренди

- **Зміна ролі інженера.** Формула OpenAI: люди керують, агенти виконують. Команда проєктує середовище, задає намір і будує цикли зворотного зв'язку. Результат: близько мільйона рядків коду, ~1500 PR, 3.5 PR на інженера на день.
- **Мультиагентні схеми з окремим evaluator.** У Anthropic три агенти (planner, generator, evaluator) будували full-stack застосунки в багатогодинних сесіях. Скептичного evaluator налаштувати значно простіше, ніж змусити generator чесно оцінювати себе.
- **Harness як платформа.** Anthropic запустив Managed Agents, де сесія — контекстний об'єкт поза вікном моделі, а інтерфейси мають пережити конкретні реалізації. OpenAI у серпні 2026 представив Codex як платформу з відкритим agent harness.
- **Агенти покращують harness.** LangChain автоматизував аналіз збоїв: паралельні агенти розбирають trace-и, головний агент синтезує висновки й пропонує зміни.
- **Повернення детермінованих сенсорів.** Мутаційне та структурне тестування переживають відродження, а LSP інтегрують в агентів.
- **Harness templates.** Böckeler прогнозує, що команди обиратимуть стек частково за тим, які harness для нього вже існують.
- **Agent legibility.** «Нудні» технології агентам легше моделювати. Дрібні залежності OpenAI іноді переписував під себе.
- **Sandbox як стандарт.** Додається проксі авторизації, який підставляє credentials поза sandbox, тож секретів усередині немає.

## 4. Практичні аспекти та досвід

### Контекст і знання

- **AGENTS.md — карта, а не енциклопедія.** Великий файл в OpenAI провалився: витісняв задачу, швидко гнив, не перевірявся. Робочий варіант: AGENTS.md ~100 рядків із посиланнями, тека docs/ як система запису, свіжість якої перевіряють лінтери і «doc-gardening» агент.
- **Чого агент не бачить, того не існує.** Знання в Google Docs, чатах чи головах людей агенту недоступні. Архітектурні рішення з обговорень треба переносити в репозиторій.
- **Описуйте середовище одразу.** LangChain на старті мапить директорії й доступні інструменти, бо самостійний пошук контексту схильний до помилок.

### Обмеження та сенсори

- **Інваріанти, а не мікроменеджмент.** У OpenAI кожен домен поділено на фіксовані шари із суворо перевіреними напрямками залежностей. Повідомлення кастомних лінтерів містять інструкції з виправлення для агента.
- **Guides і sensors разом.** Лише зворотний зв'язок дає агента, що повторює помилки; лише правила — агента, який не дізнається, чи вони спрацювали.
- **Перевірки ліворуч.** Дешеві детерміновані перевірки — на кожну зміну; дорогі inferential (AI-рев'ю, мутаційні тести) — пізніше в pipeline.
- **Steering loop.** Коли проблема повторюється, покращуйте guides і sensors, щоб вона стала менш імовірною.

### Виконання

- **Примусовий цикл build → verify.** LangChain використовує hook, що перехоплює агента перед виходом і змушує пройти верифікацію проти специфікації. Також: детектор циклів за кількістю правок файлу і попередження про бюджет часу.
- **Reasoning sandwich.** Максимальний reasoning на плануванні та верифікації, нижчий на реалізації. Робота повністю на xhigh дала лише 53.9% через таймаути.
- **Довгі задачі — почати з малого.** Progress-файл, список задач із булевими прапорцями, ритуал старту з читанням обох, одна одиниця роботи на сесію. Тест: якщо свіжий контекст не відновлює проєкт з диска, це не harness, а довгий промпт.
- **Planner формулює «що» і «навіщо», а не «як».** Деталі реалізації від planner каскадно поширювали помилки. Перед реалізацією evaluator узгоджує з generator «sprint contract» з тестованими критеріями.
- **Застосунок прозорий для агента.** OpenAI запускає застосунок окремо для кожного git worktree з тимчасовим стеком логів, метрик і трейсів. Це робить перевірюваними вимоги на кшталт часу старту сервісу.

### Підтримка і люди

- **Переглядайте harness при зміні моделі.** Той самий harness на Claude Opus 4.6 дав 59.6%, бо цикл покращення під Claude не проганяли.
- **Постійний garbage collection.** Фонові задачі шукають відхилення від «золотих принципів» і відкривають дрібні рефакторинг-PR, більшість з яких рев'юється менш ніж за хвилину.
- **Людина там, де вона найважливіша.** Мета harness — не прибрати людину, а направити її внесок у найцінніші точки.

## Висновок

1. Harness engineering — це відродження класичних інженерних дисциплін (типи, архітектурні fitness functions, CI, observability), але тепер їх споживає агент, і вони потрібні з першого дня.
2. Найбільший виграш дають детерміновані сенсори та примусова верифікація. Найбільша нерозв'язана проблема — перевірка поведінки та правильне розуміння задачі; тут людина лишається ключовим сенсором.
3. Harness — це живий код: він гниє, оверфітиться і застаріває з новими моделями. Йому потрібні власник, версіонування і регулярне прибирання.
4. Безпека будується архітектурно — sandbox, мережеві allowlist, секрети поза агентом — а не через промпти.

### Для NestJS/TS/Postgres

- strict TS і dependency-cruiser або ESLint boundaries для меж модулів, з повідомленнями-інструкціями для агента;
- окрема тимчасова БД на кожен worktree;
- тести міграцій і контрактні тести API як gate;
- структуровані логи, доступні агенту;
- короткий AGENTS.md-карта плюс docs/ із планами і техборгом.

## Джерела

- [OpenAI — Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/)
- [Birgitta Böckeler — Harness engineering for coding agent users (martinfowler.com)](https://martinfowler.com/articles/harness-engineering.html)
- [Anthropic — Harness design for long-running application development](https://anthropic.com/engineering/harness-design-long-running-apps)
- [Anthropic — Scaling Managed Agents](https://anthropic.com/engineering/managed-agents)
- [InfoQ — Anthropic three-agent harness](https://infoq.com/news/2026/04/anthropic-three-agent-harness-ai/)
- [LangChain — Improving Deep Agents with harness engineering](https://blog.langchain.com/improving-deep-agents-with-harness-engineering)
- [LangChain — How to choose the right sandbox for your agent](https://www.langchain.com/blog/how-to-choose-the-right-sandbox-for-your-agent)
- [Simon Willison — Living dangerously with Claude](https://simonwillison.net/2025/Oct/22/living-dangerously-with-claude/)
- [Software Mansion — Security for coding agents](https://agentic-engineering.swmansion.com/becoming-productive/security/)
- [Zentera — Lethal trifecta for AI agents](https://www.zentera.net/blog/lethal-trifecta-ai-agents)
- [Mejba Ahmed — Anthropic's long-running agent harness](https://www.mejba.me/blog/anthropic-long-running-agent-harness)
- [Understanding Data — Generator-Evaluator harness design](https://understandingdata.com/posts/generator-evaluator-harness-design/)
- [First AI Movers — Harness design is becoming the real moat](https://radar.firstaimovers.com/harness-design-long-running-ai-agents)
- [Ken Huang — From Software Engineering to Harness Engineering](https://kenhuangus.substack.com/p/from-software-engineering-to-harness)
- [ZenML — Harness engineering for agentic coding systems](https://www.zenml.io/llmops-database/harness-engineering-for-agentic-coding-systems)
