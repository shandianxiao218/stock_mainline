# A股板块主线雷达 Demo

个人使用的 A 股板块主线雷达 MVP demo，覆盖日度复盘榜单、主线详情、风险解释、持仓/自选风险、自然语言复盘、Excel 导出和 API 草案。

## Run

```powershell
python backend/server.py
```

Open:

```text
http://127.0.0.1:8000
```

## Main Files

- `MEMORY.md`: confirmed project decisions.
- `TODO.md`: implementation checklist.
- `docs/DESIGN.md`: MVP technical design.
- `docs/database.sql`: database DDL draft.
- `docs/API.md`: API draft.
- `backend/server.py`: local API/static server.
- `backend/scoring.py`: scoring and aggregation logic.
- `frontend/index.html`: Web dashboard.

## Notes

The current demo uses local sample data. Tushare is represented by `backend/tushare_adapter.py` and should be enabled after setting token, data quotas, and normalized persistence.

