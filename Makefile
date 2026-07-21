.PHONY: demo test test-unit test-integration benchmark up down

demo:
	./scripts/quick_demo.sh

test: test-unit

test-unit:
	python3 -m pytest -q -m "not integration"

test-integration:
	RUN_INTEGRATION=1 EXECUTION_MODE=celery \
		DATABASE_URL=mysql+pymysql://reliability_lab:reliability_lab_dev@127.0.0.1:3307/reliability_lab \
		CELERY_BROKER_URL=redis://127.0.0.1:6379/0 \
		CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0 \
		python3 -m pytest -q -m integration

benchmark:
	EXECUTION_MODE=celery \
		DATABASE_URL=mysql+pymysql://reliability_lab:reliability_lab_dev@127.0.0.1:3307/reliability_lab \
		CELERY_BROKER_URL=redis://127.0.0.1:6379/0 \
		CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0 \
		python3 -m scripts.run_concurrent_benchmark --runs 20

up:
	docker compose up --build

down:
	docker compose down -v
