# План разработки: OpenAI-совместимый прокси-шлюз для n8n AI Agent

## Цель

Микросервис-прокси, который:
- Принимает запросы в формате **OpenAI API** (для подключения AI Agent в n8n).
- Проксирует запросы на бэкенд **https://bridge-back.admlr.lipetsk.ru**.
- Пробрасывает аутентификацию **X-API-Key** (из заголовка или из Bearer).
- Возвращает ответы в формате OpenAI для полной совместимости с n8n.

## Требования n8n к OpenAI-совместимому API

- **Base URL**: например `http://gateway:8000/v1` — n8n добавляет к нему пути.
- **Эндпоинты**:
  - `GET /v1/models` — список моделей.
  - `POST /v1/chat/completions` — чат (обычный и стриминг).
- **Аутентификация**: API Key (n8n передаёт как Bearer или в настройках credential).
- **Формат**: запрос/ответ как в [OpenAI Chat Completions](https://platform.openai.com/docs/api-reference/chat).

## Этапы разработки

### 1. Структура проекта и конфигурация

- [x] Создать структуру каталогов (приложение, конфиг, Docker).
- [ ] `requirements.txt` с зависимостями (FastAPI, uvicorn, aiohttp, pydantic, python-multipart).
- [ ] Конфигурация через переменные окружения: `BRIDGE_BASE_URL`, `DEFAULT_API_KEY` (опционально), `MODEL_NAME`.

### 2. Ядро прокси: аутентификация и заголовки

- [ ] Извлечение API-ключа:
  - из `Authorization: Bearer <key>`;
  - из заголовка `X-API-Key` (если n8n или клиент шлёт его напрямую).
- [ ] Проксирование на bridge: всегда отправлять **X-API-Key** на `bridge-back.admlr.lipetsk.ru`.
- [ ] Опционально: подстановка `DEFAULT_API_KEY`, если ключ не передан (для тестов/внутренних сценариев).

### 3. Эндпоинты в формате OpenAI

- [ ] **GET /v1/models**  
  Ответ в формате OpenAI: `{"object": "list", "data": [{"id": "...", "object": "model", ...}]}`.  
  Список моделей задаётся конфигом (одна модель или несколько).

- [ ] **POST /v1/chat/completions**  
  - Принимать тело запроса как в OpenAI (model, messages, temperature, max_tokens, stream, stop, top_p, n, presence_penalty, frequency_penalty, user).
  - Маппинг полей в формат bridge (если у bridge другие имена — преобразовать).
  - URL бэкенда: `{BRIDGE_BASE_URL}/api/v1/completions` (или один константный URL из конфига).

### 4. Нестриминговые ответы

- [ ] Запрос к bridge без `stream` (или stream=false).
- [ ] Получить JSON-ответ от bridge.
- [ ] Преобразовать ответ bridge в формат OpenAI:
  - `id`, `object`, `created`, `model`, `choices`, `usage` (prompt_tokens, completion_tokens, total_tokens).
- [ ] Обработка ошибок bridge (4xx/5xx) с пробросом статуса и тела в ответ клиенту.

### 5. Стриминг (SSE)

- [ ] При `stream=true` не вызывать `response.json()` — читать тело как поток.
- [ ] Запрос к bridge с `stream=true`.
- [ ] Читать SSE-поток от bridge (aiohttp stream).
- [ ] Преобразовать каждый chunk в формат OpenAI SSE (`data: {"id":..., "choices":[...]}\n\n`, завершение `data: [DONE]\n\n`).
- [ ] Отдавать клиенту через `StreamingResponse` с `media_type="text/event-stream"`.

### 6. Дополнительные эндпоинты (по необходимости)

- [ ] **POST /v1/chat/completions/with-file** — если n8n или клиенты будут загружать файлы (multipart → bridge).
- [ ] **GET /health** — для Docker/оркестрации и healthcheck.
- [ ] **GET /test** или убрать — по желанию для отладки.

### 7. CORS и безопасность

- [ ] CORS: разрешить нужные origin (или `*` для разработки).
- [ ] Не логировать API-ключи.
- [ ] Ограничение размера тела запроса при необходимости.

### 8. Docker-микросервис

- [ ] **Dockerfile**: Python 3.11-slim, копирование кода, установка зависимостей, пользователь без root, порт 8000, запуск через `uvicorn` (без `--reload` в проде).
- [ ] **docker-compose.yml**: сервис с переменными окружения (`BRIDGE_BASE_URL`, `DEFAULT_API_KEY`, `MODEL_NAME`), маппинг порта, healthcheck на `/health`.
- [ ] **.env.example**: шаблон переменных для запуска.

### 9. Документация и проверка

- [ ] README: назначение сервиса, как запустить (Docker, docker-compose), как настроить n8n (Base URL, API Key).
- [ ] Проверка: запросы с n8n AI Agent на Base URL `http://<gateway>:8000/v1` с API Key; проверка стриминга и нестриминга.

## Итоговая схема

```
n8n AI Agent  -->  [Gateway :8000]  -->  X-API-Key + body  -->  bridge-back.admlr.lipetsk.ru
                      /v1/models
                      /v1/chat/completions (JSON + SSE)
```

## Результат

- Один микросервис в Docker, готовый к деплою.
- Полный аналог формата OpenAI для подключения к AI Agent в n8n.
- Проксирование X-API-Key на https://bridge-back.admlr.lipetsk.ru.
