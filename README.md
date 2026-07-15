# Reward Delivery Reliability Lab

一个本地可靠性实验项目，用一条奖励发放链路验证“消息会重试，但余额副作用只能发生一次”。

## 唯一业务模型

```text
请求（幂等键）
  -> MySQL 事务：delivery_order + delivery_outbox_event
  -> Celery 任务经 Redis 队列执行实验
  -> delivery_wallet_ledger（order_id 唯一）
  -> 玩家余额变更
  -> 断言订单、Outbox、账本、余额与状态
```

订单与 Outbox 在一个事务中创建。消费者先尝试写入以 `order_id` 为唯一键的账本；只有成功写入账本才变更余额。重复消费会命中已有账本并跳过余额副作用。

## 实验场景

| 场景 | 验证点 | 预期结论 |
| --- | --- | --- |
| 重复请求 | 相同幂等键重复提交 | 只创建一张订单和一条 Outbox 事件 |
| 确认丢失后重试 | 首次入账后模拟未确认，再次消费 | 账本、余额仍各只有一次副作用 |
| 并行消费尝试 | 两个线程同时尝试处理同一订单 | 账本唯一约束只允许一笔入账 |
| 账本守卫失效对照 | 故意绕过账本直接改余额两次 | 断言检出余额重复变更（`detected`） |

最后一项不是“通过的业务路径”：它刻意制造错误，用于证明断言能抓到重复副作用，而不是让所有图表永远为绿。

## 运行

Docker 模式会启动 MySQL、Redis、FastAPI 和一个并发数为 4 的 Celery Worker。并行消费场景会提交两个独立的 Celery 消费任务，并在两者完成后由回调任务做最终断言：

```bash
docker compose up --build
```

打开 `http://localhost:8000/dashboard`（不要在地址末尾输入中文句号）。页面右上角会每 10 秒调用 `/health`：

- 数据库：执行 `SELECT 1`，并显示当前 SQLAlchemy 后端；
- Redis：建立 broker 连接；
- Worker：通过 Celery `control.ping` 获取响应。

若依赖没有响应，页面显示红色状态；这不是静态绿灯。

本地不使用 Docker 时，默认同步执行，使用 SQLite：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m uvicorn app.main:app --reload
```

## 接口与验证证据

| 接口 | 用途 |
| --- | --- |
| `GET /health` | 数据库、Redis、Worker 的真实探活结果 |
| `GET /reliability/scenarios` | 返回可运行实验场景 |
| `POST /reliability/runs` | 创建一次实验；Docker 模式会投递到 Celery |
| `GET /reliability/runs/{id}` | 查看持久化事件、实际值与断言结果 |
| `GET /reliability/trend` | 最近实验的验证率与对照检出记录 |

运行测试：

```bash
python3 -m pytest -q
```
