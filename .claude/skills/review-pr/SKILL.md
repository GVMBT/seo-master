---
name: review-pr
description: Дождаться CodeRabbit ревью PR, исправить замечания и замержить
argument-hint: "<PR-number> (например: 72)"
---

## Задача
Обработай CodeRabbit ревью для PR #$ARGUMENTS и доведи до мержа.

## Алгоритм

### 1. Определить PR
- Если `$ARGUMENTS` пустой — найти PR текущей ветки: `gh pr view --json number,title,url`
- Если указан номер — использовать его

### 2. Дождаться CodeRabbit ревью
Поллинг с интервалом 30с, максимум 5 минут:
```bash
gh pr checks $PR_NUMBER --watch --fail-level all
```
Если checks не завершаются за 5 мин — сообщить пользователю и остановиться.

### 3. Прочитать замечания
```bash
gh pr view $PR_NUMBER --comments --json comments
gh api repos/GVMBT/seo-master/pulls/$PR_NUMBER/comments --jq '.[].body'
```
Также проверить review comments (inline):
```bash
gh api repos/GVMBT/seo-master/pulls/$PR_NUMBER/reviews --jq '.[] | select(.user.login=="coderabbitai") | .body'
```

### 4. Классифицировать замечания
- **BLOCK** — ошибки, баги, security issues → исправить обязательно
- **SUGGEST** — улучшения, стиль → исправить если разумно
- **SKIP** — false positives, спорные рекомендации → объяснить почему пропускаем

### 5. Исправить
Для каждого BLOCK/SUGGEST замечания:
1. Прочитать файл и контекст
2. Применить исправление (Edit)
3. Убедиться что тесты проходят: `uv run pytest tests/ -x -q`
4. Коммит: `fix: address CodeRabbit review — {краткое описание}`

### 6. Пуш и повторная проверка
```bash
git push
```
Подождать повторный ревью CodeRabbit (до 3 минут).
Если новых замечаний нет — переходить к мержу.
Если есть — повторить шаги 3-6 (максимум 3 итерации).

### 7. Мерж
```bash
gh pr merge $PR_NUMBER --merge --delete-branch
git checkout main && git pull origin main
```

## Правила
- Максимум 3 итерации правок. Если после 3 раундов ещё есть замечания — показать пользователю.
- НЕ делать `@coderabbitai resolve` — замечания должны быть реально исправлены или осознанно пропущены.
- Если замечание спорное — спросить пользователя, не решать самостоятельно.
- Каждый коммит правок — отдельный (не amend).
- После мержа — вернуться на main и pull.

## Формат отчёта
```
## PR #N: {title}

### CodeRabbit замечания: X найдено
| # | Файл:Строка | Замечание | Действие |
|---|-------------|----------|----------|
| 1 | path:42     | описание | FIXED / SKIPPED (причина) |

### Итог
- Исправлено: N
- Пропущено: M (с обоснованием)
- Итерации: K
- Статус: MERGED / NEEDS_USER_INPUT
```
