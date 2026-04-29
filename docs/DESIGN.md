# MVP Technical Design

## Scope

The first demo is a personal-use daily review system for A-share theme radar analysis. It focuses on after-close ranking, explanation, risk warnings, portfolio/watchlist risk, natural-language review, and Excel export.

Out of scope for MVP: intraday refresh, trading orders, public investment advice, PDF export, and fully automated news interpretation.

## Architecture

```text
Tushare adapter / sample data
        |
        v
Daily snapshot normalizer
        |
        v
Sector scoring engine
  - heat score
  - continuation score
  - risk penalty
        |
        v
Automatic theme aggregation
  - core stock overlap
  - keyword similarity
  - branch/category grouping
        |
        v
Theme scoring and confidence
        |
        +--> Web dashboard
        +--> API responses
        +--> Excel export
        +--> Daily review text
```

## Module Plan

| Module | Responsibility |
| --- | --- |
| `backend/server.py` | Local HTTP server, API routing, static UI serving |
| `backend/scoring.py` | Heat, continuation, risk, confidence, aggregation |
| `backend/sample_data.py` | Demo market/sector/watchlist/portfolio data |
| `backend/tushare_adapter.py` | Future live data entry point |
| `frontend/index.html` | Dashboard shell |
| `frontend/styles.css` | Web UI styling |
| `frontend/app.js` | API calls and UI rendering |

## MVP Scoring

Theme score:

```text
theme_score = 0.4 * heat_score + 0.6 * continuation_score - risk_penalty
```

Risk penalty is capped at 20. Confidence uses liquidity, top theme score spread, risk stability, market breadth, and theme consistency.

## Data Source Strategy

Tushare is the Phase 1 data source. The first runnable demo does not call Tushare by default because it requires a user token and real quota. The adapter should later map Tushare data to normalized daily snapshots:

- Trading calendar.
- Daily stock quotes.
- Daily index quotes.
- Limit-up and limit-break approximations or a licensed source if Tushare coverage is insufficient.
- Sector/industry classification and constituent history.

## Sentiment Strategy

No sentiment vendor is available. MVP keeps `sentiment_momentum`, `sentiment_heat`, and `sentiment_overheat` as optional fields. If missing, the model should either use neutral values or reduce sentiment weight through model configuration.

## Persistence

The demo computes from local sample records. Production MVP should use PostgreSQL or SQLite with historical snapshot tables. The DDL in `docs/database.sql` is PostgreSQL-oriented and can be adapted to SQLite for local personal use.

## Run

```powershell
python backend/server.py
```

Then open:

```text
http://127.0.0.1:8000
```

