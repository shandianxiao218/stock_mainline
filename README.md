# A股板块主线雷达 Demo

个人使用的 A 股板块主线雷达 MVP demo，覆盖日度复盘榜单、主线详情、风险解释、持仓/自选风险、自然语言复盘、Excel 导出和 API 草案。

## 东方财富数据导入

二进制 `.dat` 文件读取只由 C 程序完成，默认东方财富路径为：

```text
C:\eastmoney
```

构建导入器：

```powershell
clang --target=x86_64-w64-windows-gnu --sysroot=C:\ProgramData\mingw64\mingw64 -O2 -std=c11 -Wall -Wextra -o tools\eastmoney_import.exe tools\eastmoney_import.c
```

导入最近数据到 CSV：

```powershell
tools\eastmoney_import.exe C:\eastmoney backend\data\eastmoney 20200101
```

输出文件：

- `backend\data\eastmoney\stocks.csv`
- `backend\data\eastmoney\daily_quotes.csv`

## 运行

```powershell
python backend/server.py
```

打开：

```text
http://127.0.0.1:8000
```

## 主要文件

- `MEMORY.md`: 已确认的项目决策。
- `TODO.md`: 实施清单。
- `docs/DESIGN.md`: MVP 技术设计。
- `docs/database.sql`: 数据库 DDL 草案。
- `docs/API.md`: API 草案。
- `tools/eastmoney_import.c`: 东方财富本地二进制日线 C 导入器。
- `backend/server.py`: 本地 API/静态页面服务。
- `backend/scoring.py`: 评分与聚合逻辑。
- `frontend/index.html`: Web 看板。

## 说明

当前主线评分 demo 仍使用本地样例板块数据；东方财富 C 导入器已经可导出个股日线 CSV。下一步是把 CSV 装载到模型快照表，并生成真实板块评分输入。Tushare 保留为后续补充源。
