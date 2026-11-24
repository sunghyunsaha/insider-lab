.PHONY: install test lint demo data-check data sec prices backtest report score

install:
	python -m pip install -r requirements.txt && python -m pip install -e . --no-deps

test:
	python -m pytest

lint:
	ruff check . && ruff format --check .

demo:
	insiderlab demo

data-check:
	insiderlab data-check

sec:
	insiderlab fetch-sec

prices:
	insiderlab fetch-prices

data: sec prices

backtest:
	insiderlab backtest

report:
	insiderlab report

score:
	insiderlab ledger score
