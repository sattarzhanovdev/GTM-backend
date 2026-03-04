# GTM backend (Django)

## Run

```sh
cd backend
python3 -V  # рекомендуется Python 3.12 или 3.13
python3 manage.py migrate
python3 manage.py runserver 0.0.0.0:8000
```

## CORS (для браузера)

CORS нужен только если фронт запускается в браузере (например Expo Web). Для iOS/Android CORS не применяется.

В проект добавлен простой CORS middleware для путей `/api/*` (разрешает `Origin`, `Authorization`, `Content-Type`).

## Python version

Проект рассчитан на Python **3.12/3.13**. Если запускать на Python **3.14**, Django может падать странными ошибками (например `'super' object has no attribute 'dicts'`).

## Auth

- Логин (`username`): `квартира-подъезд` (пример: `12-1`)
- Пароль (`password`): `квартира` (пример: `12`)

### Login

`POST /api/login/`

Body:
```json
{ "username": "12-1", "password": "12" }
```

Response: `{ token, user }`

### Me

`GET /api/me/` with header:
`Authorization: Bearer <token>`

## Endpoints

- `GET /api/profile/notifications/`
- `POST /api/profile/notifications/<id>/read/`
- `POST /api/profile/notifications/<id>/delete/`
- `GET /api/profile/users/`
- `POST /api/profile/users/<id>/delete/`

- `GET /api/payments/`
- `GET /api/payments/history/?date=YYYY-MM-DD`
- `POST /api/payments/<id>/receipt/` (multipart field `file`)

### Payments response fields

`GET /api/payments/` returns items:
- `title` (название)
- `amount` (число)
- `currency` (строка, например `сом`)
- `amountText` (готовая строка, например `250 сом`)
- `dueDate` (ISO date или `null`)
- `payUrl` (ссылка для оплаты или `null`)
 - `statusText` (статус по‑русски)

Заметка: сами начисления (`PaymentCharge`) общие для всех квартир, а статус/чек хранится по квартире в `PaymentParticipation`.

- `GET /api/devices/status/`
- `POST /api/devices/gate/open/`
- `POST /api/devices/kalitka/<n>/open/` (`n`: 1..4)
- `POST /api/devices/entrance/<n>/open/` (`n`: 1..5)
- `POST /api/devices/entrance/<n>/lift/open/` (`n`: 1..5)
