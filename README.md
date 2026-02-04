# Bridge OpenAI Gateway

Микросервис-прокси, предоставляющий **OpenAI-совместимый API** для подключения **AI Agent в n8n** к бэкенду [bridge-back.admlr.lipetsk.ru](https://bridge-back.admlr.lipetsk.ru).

- Принимает запросы в формате OpenAI (`/v1/models`, `/v1/chat/completions`).
- Проксирует аутентификацию **X-API-Key** (из заголовка `Authorization: Bearer <key>` или `X-API-Key`) на бэкенд.
- Поддерживает обычные ответы и **стриминг (SSE)**.

## Запуск в Docker

```bash
# Сборка и запуск
docker compose up -d

# Логи
docker compose logs -f bridge-gateway
```

Сервис будет доступен на `http://localhost:8000`.

## Настройка n8n

1. В n8n создайте учётные данные типа **OpenAI**.
2. **Base URL** (как у OpenAI, поддерживаются оба варианта):
   - `http://<host>:<порт>/api/v1` — рекомендуемый (как у OpenAI)
   - `http://<host>:<порт>/v1` — тоже работает
   - Примеры: `http://localhost:8000/api/v1`, `http://your-domain.com:8008/api/v1`, `http://bridge-gateway:8000/api/v1`
3. **API Key**: ваш ключ для bridge (передаётся на бэкенд как `X-API-Key`).
4. В узле AI Agent / Chat OpenAI выберите учётную запись и модель. Для эмбеддингов: `bge-m3-multi`, `multilingual-e5-large`.

## Переменные окружения

| Переменная | Описание | По умолчанию |
|------------|----------|---------------|
| `BRIDGE_BASE_URL` | Базовый URL бэкенда | `https://bridge-back.admlr.lipetsk.ru` |
| `BRIDGE_COMPLETIONS_URL` | URL эндпоинта completions | `{BRIDGE_BASE_URL}/api/v1/completions` |
| `MODEL_NAME` | Имя модели для n8n | `deepseek-v3` |
| `BRIDGE_MODEL` | Имя модели в запросах к bridge | `deepseek-ai/DeepSeek-V3-0324` |
| `DEFAULT_API_KEY` | Ключ по умолчанию (опционально) | — |
| `PORT` | Порт на хосте (маппинг в docker-compose) | `8000` |

Скопируйте `.env.example` в `.env` и при необходимости задайте переменные.

## Эндпоинты

- `GET /v1/models` и `GET /api/v1/models` — список моделей (OpenAI-формат): чат-модели и `bge-m3-multi` для эмбеддингов.
- `POST /v1/chat/completions` и `POST /api/v1/chat/completions` — чат (JSON и streaming).
- `POST /v1/embeddings` и `POST /api/v1/embeddings` — эмбеддинги (модели `bge-m3-multi`, `multilingual-e5-large`).
- `GET /health` — проверка состояния для Docker/оркестрации.

## Локальная разработка

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Документация API: http://localhost:8000/docs
