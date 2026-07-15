# Game Service Quality Platform

面向游戏活动奖励发放场景的服务测试与数据质量平台。项目的核心是一个可运行的「奖励发放可靠性实验」：在重复请求、确认丢失后重试、并发重复消费三类场景中，验证一次奖励最终只产生一笔账本流水和一次余额变更。

它用一个可运行的活动奖励服务模拟后端，并提供：

- 奖励发放接口及幂等控制；
- SQLite / MySQL 可切换的事务与奖励库存更新；
- 自动化 API 测试和可执行服务场景；
- 数据质量规则（重复发奖、孤儿数据、非法状态、负余额、奖励金额不一致、库存账实不一致）及异常样本定位；
- 质量检查运行快照、测试运行历史与本地可视化控制台；
- Docker Compose 启动 MySQL、Redis、API 与 Celery Worker，异步执行服务测试任务。

## 核心：奖励发放可靠性实验

`/dashboard` 的主流程不是静态看板，而是一条可执行的可靠性验证链路：

```text
奖励请求（幂等键）
  → MySQL 事务：创建 delivery_order + Outbox event
  → Redis / Celery Worker 消费事件
  → 写入以 order_id 为唯一键的钱包账本
  → 更新玩家余额、完成 Outbox
  → 校验订单数、事件数、账本数、余额和最终状态
```

账本表对 `order_id` 设置唯一约束，且消费者先写账本再更新余额。因此即使 Worker 再次收到同一事件，也会命中已有账本并跳过余额变更。实验会保存完整事件时间线、每一步的载荷与最终断言。

可选择的场景：

- **重复请求**：相同幂等键连续提交两次，验证订单和 Outbox 不重复创建；
- **确认丢失后重试**：首次消费已完成入账但未确认，重试后验证余额不重复增加；
- **并发重复消费**：两个消费者处理同一事件，验证唯一账本只允许一个副作用提交。

## 项目能力映射

| 能力维度 | 项目对应实现 |
| --- | --- |
| 测试工具 / 平台前后端开发 | FastAPI 服务、可靠性实验运行接口、事件时间线与本地控制台 |
| 自动化测试 | `pytest` 覆盖 API、质量规则、服务场景和奖励可靠性实验；实验持久化订单、事件、账本和最终断言 |
| HTTP / MySQL / Redis | REST API、状态码、请求幂等键；`DATABASE_URL` 选择 SQLite 或 MySQL；Docker 环境通过 Redis/Celery 投递实验任务 |
| 事务与并发 | 订单与 Outbox 同一事务写入；账本 `order_id` 唯一约束隔离重复消费副作用；覆盖 MySQL 并发消费与库存扣减 |
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

## 工作台怎么用

新版 `/dashboard` 不只是展示结果，提供四个可操作的验证流程：

1. 在“服务测试配置”选择要执行的场景，并传入初始库存、单玩家领取上限和账号状态。运行会保存所选场景和参数；历史记录中的“重跑”会复用同一份配置。
2. 在“测试用例证据”点击“证据”，查看该场景实际生成的请求、响应、断言、耗时和失败原因。
3. 在“故障注入”选择一个本地故障类型。平台写入带 `fault_` 前缀的演示数据并立即执行质量检查，展示对应告警和样本；“清理故障数据”只删除这些演示记录并重新检查。
4. “运行趋势”和“服务测试历史”展示最近运行的通过率、用例汇总和可回看的执行详情。

故障注入是为了演示质量规则的定位链路，不会写入真实外部系统，也不会影响 `qa_<run>_*` 服务测试数据。

## Docker：MySQL、Redis 与异步 Worker

```bash
docker compose up --build
```

启动后访问 `http://127.0.0.1:8000/dashboard`。此环境使用 MySQL 持久化订单、Outbox、账本、实验事件和测试结果；点击“运行可靠性实验”会先创建 `queued` 运行记录，再由 Celery Worker 从 Redis 队列消费。页面会展示最终不变量与每个持久化事件。可在终端查看：

```bash
docker compose logs -f worker
curl -X POST http://127.0.0.1:8000/test-runs
curl -X POST http://127.0.0.1:8000/reliability/runs -H 'Content-Type: application/json' -d '{"scenario":"acknowledgement_loss"}'
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
- 使用 Docker Compose 编排 MySQL、Redis、API 与 Celery Worker；实现订单与 Outbox 同事务写入、`order_id` 唯一账本去重，并通过重复请求、确认丢失重试和并发消费实验验证奖励只产生一次余额副作用。
