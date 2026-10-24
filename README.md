# ValutaTrade Hub

Учебный симулятор торговли валютами с локальным кэшем курсов и отдельным
**Parser Service**. Демонстрирует чистую архитектуру (`core` / `infra` /
`parser_service` / `cli`), паттерны **Singleton**, **Decorator**, доменные
исключения, атомарную запись JSON и логирование с ротацией.

## Идея

Пользователь регистрируется, получает стартовый баланс **10 000 USD**, покупает
и продаёт криптовалюты (**BTC**, **ETH**, **SOL**) и фиатные валюты
(**EUR**, **GBP**, **RUB**) по актуальным курсам к USD. Курсы обновляются
через внешние API (CoinGecko — крипто, ExchangeRate-API — фиат) и кэшируются
локально с TTL. Ядро (`core`) читает курсы только из кэша — без обращения к
сети; Parser Service (`parser_service`) отвечает за наполнение кэша по
команде `update-rates` или по расписанию (`scheduler.py`).

## Структура

```
finalproject_forgo_group/
├── data/                          # runtime, создаётся автоматически
│   ├── users.json
│   ├── portfolios.json
│   ├── rates.json                 # локальный кэш для Core Service
│   ├── exchange_rates.json        # журнал измерений Parser Service
│   └── session.json               # текущая сессия (login/logout)
├── logs/                          # ротация: app.log, parser.log
├── valutatrade_hub/
│   ├── __init__.py
│   ├── logging_config.py          # RotatingFileHandler × 2 (app + parser)
│   ├── decorators.py              # @log_action
│   ├── core/
│   │   ├── currencies.py          # справочник валют, INITIAL_USD_BALANCE
│   │   ├── exceptions.py          # ValutaTradeError + доменные подклассы
│   │   ├── models.py              # User, Wallet, Portfolio
│   │   ├── usecases.py            # register/login/buy/sell/get_rate/show_portfolio
│   │   └── utils.py               # ISO-8601, TTL
│   ├── infra/
│   │   ├── settings.py            # SettingsLoader — Singleton, TTL, пути
│   │   └── database.py            # DatabaseManager — Singleton, атомарный JSON IO
│   ├── parser_service/
│   │   ├── config.py              # ParserConfig, .env-loader
│   │   ├── api_clients.py         # BaseApiClient, CoinGeckoClient, ExchangeRateApiClient
│   │   ├── updater.py             # RatesUpdater
│   │   ├── storage.py             # RatesStorage (tmp→rename)
│   │   └── scheduler.py           # периодический запуск (опционально)
│   └── cli/
│       └── interface.py           # argparse, 9 команд
├── main.py                        # python main.py <cmd> — то же, что `valutatrade`
├── pyproject.toml                 # PEP 621, [project.scripts]
├── uv.lock
├── README.md
├── .env.example
└── .gitignore
```

Файлы в `data/*.json` и `logs/` создаются кодом при первом запуске и
**не коммитятся** (`.gitignore`). `.env` тоже не коммитится — там хранится
ключ ExchangeRate-API.

## Установка

Требуется Python 3.11+ и [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/unclearblast/finalproject_forgo_group.git
cd finalproject_forgo_group
uv sync
cp .env.example .env
# отредактировать .env — вставить ваш ключ ExchangeRate-API
uv run valutatrade --help
```

Установить как обычный CLI-скрипт (необязательно):

```bash
uv pip install -e .
valutatrade --help
```

## Parser Service: ключ и запуск

Ключ ExchangeRate-API хранится **только в `.env`** — переменная
`EXCHANGERATE_API_KEY`. Файл в `.gitignore`; в репозиторий попадает только
`.env.example` с заглушкой. Альтернатива — экспорт в окружение:

```bash
export EXCHANGERATE_API_KEY=ваш_ключ
```

CoinGecko используется через публичный эндпоинт без ключа.

Запуск обновления:

```bash
uv run valutatrade update-rates                       # оба источника
uv run valutatrade update-rates --source coingecko    # только CoinGecko
uv run valutatrade update-rates --source exchangerate # только ExchangeRate-API
```

Периодический запуск (опционально) — из кода:

```python
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient, ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.storage import RatesStorage
from valutatrade_hub.parser_service.updater import RatesUpdater
from valutatrade_hub.parser_service.scheduler import run_scheduler
from valutatrade_hub.infra.settings import SettingsLoader

cfg = ParserConfig()
s = SettingsLoader.get()
upd = RatesUpdater(
    [CoinGeckoClient(cfg), ExchangeRateApiClient(cfg)],
    RatesStorage(s.rates_path, s.history_path),
)
run_scheduler(upd, interval_seconds=cfg.SCHEDULER_INTERVAL_SECONDS)
```

## Кэш курсов и TTL

- **`data/rates.json`** — «снимок текущего мира»: последние корректные
  курсы для конкретных пар (`BTC_USD`, `EUR_USD`, …), `last_refresh`.
  Core Service читает именно этот файл.
- **`data/exchange_rates.json`** — «журнал»: одна запись на пару и момент
  времени, `id = "<FROM>_<TO>_<ISO>"`, дубликаты не пишутся.
- **TTL** задаётся через `VT_RATES_TTL` (по умолчанию **3600** секунд).
  Если курс старше TTL, `buy`/`sell` откажутся работать и попросят
  выполнить `update-rates`; `get-rate` покажет `[STALE]`.
- **Атомарность**: оба файла пишутся через `tmp → os.replace`, поэтому
  недописанный JSON не останется даже при `kill -9`.
- **«Свежее побеждает»**: запись с более старым `updated_at` не перетирает
  более новую (защита от откатов).

## CLI

| Команда | Назначение |
|---|---|
| `register <username> [--password ...]` | Регистрация (по умолчанию пароль спрашивается через `getpass`) |
| `login <username> [--password ...]` | Вход |
| `logout` | Выход |
| `show-portfolio` | Портфель (PrettyTable) + оценка в USD |
| `buy <currency> <amount>` | Купить валюту за USD |
| `sell <currency> <amount>` | Продать валюту за USD |
| `get-rate <currency> [--base USD]` | Курс к базе, с флагом `stale` |
| `update-rates [--source ...]` | Запустить Parser Service |
| `show-rates [--currency X] [--top N] [--base B]` | Показать кэш курсов |

### Пример сессии

```bash
$ uv run valutatrade register alice --password strongpass
Registered 'alice' at 2026-10-24T12:00:00Z

$ uv run valutatrade login alice --password strongpass
Logged in as alice

$ uv run valutatrade update-rates
Update successful. Total rates updated: 6. Last refresh: 2026-10-24T12:00:01Z

$ uv run valutatrade show-rates --top 2
Rates from cache (updated at 2026-10-24T12:00:01Z):
+---------+---------+-----------+----------------------+
|   Pair  |   Rate  |   Source  |      Updated at      |
+---------+---------+-----------+----------------------+
| BTC_USD |  80147  | CoinGecko | 2026-10-24T12:00:01Z |
| ETH_USD | 2314.38 | CoinGecko | 2026-10-24T12:00:01Z |
+---------+---------+-----------+----------------------+

$ uv run valutatrade buy BTC 0.01
Bought 0.01 BTC @ 80147 USD = 801.47 USD
New BTC balance: 0.01
USD balance: 9198.53

$ uv run valutatrade show-portfolio
Portfolio of alice
+----------+---------+
| Currency | Balance |
+----------+---------+
|   USD    | 9198.53 |
|   BTC    |   0.01  |
+----------+---------+
Total value in USD: 10000.00

$ uv run valutatrade sell BTC 0.005
Sold 0.005 BTC @ 80147 USD = 400.74 USD
New BTC balance: 0.005
USD balance: 9599.27

$ uv run valutatrade get-rate BTC
BTC_USD: 80147  [source=CoinGecko, updated_at=2026-10-24T12:00:01Z]
```

### Обработка ошибок

Доменные исключения (`InsufficientFundsError`, `CurrencyNotFoundError`,
`AuthenticationError`, `RatesNotAvailableError`, `ApiRequestError`, …)
пробрасываются из ядра; CLI ловит `ValutaTradeError` в `main()` и печатает
дружелюбное сообщение без traceback:

```bash
$ uv run valutatrade buy BTC 99999
Error: Insufficient funds in USD: have 9599.27, need 8.01e+09

$ uv run valutatrade buy XYZ 1
Error: Unknown currency: XYZ

$ uv run valutatrade get-rate ABC
Error: Unknown currency: ABC

$ uv run valutatrade login alice --password wrong
Error: Invalid username or password
```

Полные детали (включая traceback) — в `logs/app.log` и `logs/parser.log`
(ротация: 1 МБ × 3 бэкапа). Пароли в логи не попадают: `register`/`login` не
декорированы `@log_action`, аргументы не сериализуются.

## Архитектура и паттерны

- **Синглтоны** — `SettingsLoader` (TTL, пути, env-overrides) и
  `DatabaseManager` (атомарный JSON IO). Оба `.reset()` — для тестов.
- **Декоратор** — `@log_action` на `buy`/`sell`/`get_rate`/`show_portfolio`:
  логирует вход, длительность, результат, а при исключении —
  `logger.exception` с типом и сообщением.
- **Стратегия** — `BaseApiClient` (ABC) + `CoinGeckoClient`,
  `ExchangeRateApiClient`. Единый интерфейс `fetch_rates() -> dict[str, float]`.
- **Изоляция слоёв** — `core` не знает про сеть и CLI; `parser_service` не
  знает про CLI; `cli` только оркестрирует. Зависимости идут внутрь:
  `cli → parser_service → core → infra`.
- **TTL + «свежее побеждает»** — защита от откатов и устаревших данных.

## Технологии

Python 3.11+, **uv**, `pyproject.toml` (PEP 621), `requests`, `prettytable`,
**ruff**, GitHub Flow (`feature/*` → `--no-ff` merge), **asciinema**.

## Известные ограничения

- Хранилище — JSON-файлы, не СУБД: конкурентная запись из нескольких
  процессов не защищена (для учебного проекта приемлемо).
- Пользователь идентифицируется по `username`, не по email; менять пароль
  через CLI нельзя (только перерегистрация под другим именем).
- `register` даёт фиксированный стартовый баланс `10 000 USD`; команды
  `deposit`/`withdraw` в CLI нет — только `buy`/`sell`.
- Asciinema-демо в README записывается один раз; курсы на момент записи и
  на момент чтения могут различаться (историчность в `exchange_rates.json`).

## Демо

[![asciicast](https://asciinema.org/a/xXJnPmJim4m3swhG.svg)](https://asciinema.org/a/xXJnPmJim4m3swhG)
