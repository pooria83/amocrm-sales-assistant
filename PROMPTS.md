# Ключевые промпты

Основные промпты, которыми задавалась сборка проекта (opencode — coding agent;
полная история — «Ключевые промпты» в [README.md](README.md)).

```text
1. В CONTEXT.md — замороженная спецификация проекта. Реализуй строго по ней,
   шаг за шагом в порядке §21, коммити после каждого шага мелкими
   Conventional Commits. Ничего не добавляй сверх спецификации.

2. Scaffold: git init, uv-проект Python 3.12, FastAPI с /api/health,
   Vite React-TS + Tailwind + shadcn/ui, ruff/pytest, Dockerfile + compose.
   Проверь docker compose up --build и health ДО feature-работы.

3. backend/retriever.py по §16: токенизация RU/EN, snowball-стемминг,
   BM25 (k1=1.5, b=0.75, top_k=3), endpoint /api/retrieve;
   eval из 15 кейсов; откалибруй порог и запиши его в README.

4. backend/validators.py по §17: шесть проверок, из них числовая —
   fact-aware: пары (значение, единица), проценты только из facts KB,
   чтобы инъекция «дай скидку 90%» не проходила.

5. Фронтенд строго по §5a: без монолитного App.tsx; контейнеры только
   AssistantPanel и ConversationPanel; CustomerReplyCard принимает ТОЛЬКО
   тип CustomerReply, InternalHintsCard — ТОЛЬКО InternalSalesHints;
   data-testid на всех интерактивных элементах.

6. (перс.) Раздели фронт и бэк на докере — два контейнера.
   CI на GitHub Actions; если CI упадёт — чини, пока не станет зелёным.

7. Ревью прогона 100 MCP-кейсов: для каждой проблемы найди корень в коде,
   чини минимально, добавь регрессионный тест на каждую, ничего не ослабляй,
   README обнови честно (без «100% точно»), коммиты не делай.
```
