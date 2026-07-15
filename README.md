# Game Service Quality Platform

面向游戏活动奖励发放场景的轻量质量平台。它用一个可运行的「活动奖励发放服务」模拟游戏后端，并提供：

- 奖励发放接口及幂等控制；
- SQLite 事务与奖励库存更新；
- 自动化 API 测试；
- 数据质量规则（重复发奖、孤儿数据、非法状态、负余额）及异常样本定位；
- JSON 质量报告与静态仪表盘。

## 项目能力映射

| 能力维度 | 项目对应实现 |
| --- | --- |
| 测试工具 / 平台前后端开发 | FastAPI 服务、质量检查接口、静态仪表盘 |
| 自动化测试 | `pytest` 覆盖正常、重复、库存不足、非法输入与数据异常 |
| HTTP / MySQL 等 Web 基础 | REST API、状态码、请求幂等键；SQLite 可替换为 MySQL |
| 事务与数据质量 | 事务扣减库存、质量规则、按严重级别输出报告 |
| 质量检查与报告 | 独立规则输出结构化结果与最多 3 条异常样本，便于定位问题数据 |

## 运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.seed_demo
uvicorn app.main:app --reload
```

访问 `http://127.0.0.1:8000/docs` 查看接口文档；访问 `/dashboard` 查看报告页面。

## 测试与报告

```bash
pytest -q
python -m scripts.run_quality_check
```

项目将把报告写入 `reports/latest.json`。测试数据库由环境变量 `GAME_QA_DB` 指定；未指定时使用 `data/game_quality.db`。

## 简历表述（按实际完成情况使用）

**游戏服务质量与数据校验平台｜个人项目**

- 基于 Python、FastAPI 与 SQLite 搭建活动奖励发放服务，设计幂等键、事务扣减与库存校验，覆盖重复请求、库存不足等常见异常场景。
- 编写自动化测试与数据质量规则，检查重复发奖、孤儿记录、非法状态和负余额；报告返回异常样本，页面展示严重级别与检查结论。
- 将数据质量检测、接口测试与异常定位整理为可复用的本地检查流程，并生成结构化质量报告。
