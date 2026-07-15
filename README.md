# Game Service Quality Platform

面向游戏活动奖励发放场景的服务测试与数据质量平台。它用一个可运行的「活动奖励发放服务」模拟游戏后端，并提供：

- 奖励发放接口及幂等控制；
- SQLite / MySQL 可切换的事务与奖励库存更新；
- 自动化 API 测试和可执行服务场景；
- 数据质量规则（重复发奖、孤儿数据、非法状态、负余额、奖励金额不一致、库存账实不一致）及异常样本定位；
- 质量检查运行快照、测试运行历史与本地可视化控制台；
- Docker Compose 启动 MySQL、Redis、API 与 Celery Worker，异步执行服务测试任务。

## 项目能力映射

| 能力维度 | 项目对应实现 |
| --- | --- |
| 测试工具 / 平台前后端开发 | FastAPI 服务、质量检查与服务测试运行接口、运行快照与本地控制台 |
| 自动化测试 | `pytest` 覆盖 API、质量规则与服务场景；平台运行后会保存每个场景的请求、响应、断言和耗时 |
| HTTP / MySQL / Redis | REST API、状态码、请求幂等键；`DATABASE_URL` 选择 SQLite 或 MySQL；Docker 环境通过 Redis/Celery 投递测试运行 |
| 事务与并发 | SQLite `BEGIN IMMEDIATE` / MySQL 行锁与条件更新，覆盖库存扣减和并发不超卖场景 |
| 质量检查与报告 | 六条质量规则输出结构化结果与最多 3 条异常样本；每次执行可保存快照并回看历史结果 |

## 运行

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m scripts.seed_demo
python3 -m uvicorn app.main:app --reload
```

访问 `http://127.0.0.1:8000/docs` 查看接口文档；访问 `/dashboard` 查看本地控制台。点击“运行质量检查”会创建一条本地运行快照，控制台可回看最近的执行结果和异常样本。

本地模式的“执行服务测试”同步运行，方便调试；每次运行会创建独立的 `qa_<run>_*` 测试数据，执行完清理业务表中的临时数据，并在 `test_runs` / `test_case_results` 留下可回看的请求、响应、断言与耗时。

## Docker：MySQL、Redis 与异步 Worker

```bash
docker compose up --build
```

启动后访问 `http://127.0.0.1:8000/dashboard`。此环境使用 MySQL 持久化业务数据、质量快照和测试结果；点击“执行服务测试”会先创建 `queued` 运行记录，再由 Celery Worker 从 Redis 队列消费。可在终端查看：

```bash
docker compose logs -f worker
curl -X POST http://127.0.0.1:8000/test-runs
```

开发密码只用于本地 Compose 示例；部署到其他环境时应通过环境变量替换。

## 测试与报告

```bash
python3 -m pytest -q
python3 -m scripts.run_quality_check
python3 -m scripts.run_service_tests
```

项目将把报告写入 `reports/latest.json`。测试数据库由环境变量 `GAME_QA_DB` 指定；未指定时使用 `data/game_quality.db`。

## 异常演示

默认 `seed_demo` 写入的是全部通过质量检查的本地数据。需要演示完整定位流程时，运行：

```bash
python3 -m scripts.seed_issue_demo
python3 -m scripts.run_quality_check
```

此脚本仅在本地 SQLite 数据库中构造重复发奖、孤儿记录、非法状态、负余额、奖励金额不一致和库存账实不一致六类数据。随后访问 `/dashboard`，可查看规则的失败计数、严重级别和异常样本；重新运行 `python3 -m scripts.seed_demo` 即可恢复为通过状态。测试场景见 [测试用例矩阵](docs/test-cases.md)。

## 简历表述（按实际完成情况使用）

**游戏服务质量与数据校验平台｜个人项目**

- 基于 Python、FastAPI 与 SQLAlchemy 搭建活动奖励发放服务，支持 SQLite / MySQL 配置切换；设计幂等键、事务扣减和库存校验，覆盖重复请求、领取上限与库存不足等场景。
- 实现服务测试运行器，隔离构造测试数据，执行正常发奖、幂等重试、账号状态和并发库存等 5 类场景，持久化每条场景的请求、响应、断言和耗时。
- 使用 Docker Compose 编排 MySQL、Redis、API 与 Celery Worker；在容器环境将测试运行异步投递到 Redis 队列，并保留质量规则和异常样本定位结果。
