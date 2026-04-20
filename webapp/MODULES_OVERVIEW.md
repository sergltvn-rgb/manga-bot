# Reader WebApp: Module Overview

## Цель
Фронтенд читалки декомпозирован на функциональные модули, а `reader.js` оставлен как orchestration/glue слой с прокси-функциями для совместимости с текущими `onclick` в HTML.

## Ключевые модули
- `telemetry.js`: метрики boot/chapter/API.
- `api-client.js` + `reader-api.js`: сетевой слой и endpoint-обертки.
- `state-store.js`: localStorage и базовое состояние/прогресс.
- `reader-bootstrap.js`: загрузка данных читалки и стартовые параметры.
- `app-lifecycle.js`: lifecycle listeners (`beforeunload`, `visibilitychange`) и bootstrap приложения.
- `progress-bar.js`: создание и обновление reading progress bar.
- `reader-content-interactions.js`: scroll/tap поведение reader-content.
- `chapter-reader.js`: открытие главы, загрузка/рендер контента, навигация по главам.
- `screen-navigation.js`: переключение экранов, FAB/admin menu.
- `reader-shell-ui.js`: оболочка UI (канал, quick-switcher, immersive, cover helper).
- `rename-admin.js`: admin rename/reset flow.
- `reader-meta.js`: meta-utils (admin mode, роль пользователя, формат даты).
- `settings-ui.js`: настройки чтения и их применение.
- `progress-tracker.js`: прогресс чтения/last-read.
- `series-catalog.js`: карточки серий/томов/глав.
- `reader-ui.js`: lightbox/ToC/autoscroll/gestures.
- `social-interactions.js`: лайки и реакции.
- `comments-view.js` + `comments-controller.js`: комментарии (render + actions).
- `chapter-admin.js`: admin редактирование URL, bulk, drag-n-drop.
- `library-view.js`: вкладка библиотеки и статистика.
- `text-markup.js`: разметка текста комментариев.
- `feedback-ui.js`: haptic + toast.
- `typo-reporter.js`: репорт опечаток.

## Что осталось в `reader.js`
- Глобальное состояние текущей сессии.
- Инициализация менеджеров и связывание зависимостей между модулями.
- Совместимые глобальные прокси-функции, вызываемые из HTML.

## Принцип дальнейших изменений
- Новую логику добавлять в профильный модуль.
- В `reader.js` добавлять только DI-связку и прокси (если нужно для backward compatibility).
