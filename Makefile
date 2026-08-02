.PHONY: test lint demo export render bench clean

test:
	PYTHONPATH=src python -m pytest -q

lint:
	PYTHONPATH=src python -m ruff check src tests training
	PYTHONPATH=src python -m playbook_legal.lint --all matters

demo:
	PYTHONPATH=src python -m playbook_legal.demo

export: demo
	PYTHONPATH=src python -m playbook_legal.export artifacts/demo_trajectory.json artifacts/demo_sft.jsonl

render: demo
	PYTHONPATH=src python -m playbook_legal.render artifacts/demo_trajectory.json artifacts/demo_trace.html

bench:
	PYTHONPATH=src python -m playbook_legal.bench --matters matters --runner replay --out artifacts/scorecard

clean:
	rm -rf artifacts .pytest_cache src/*/__pycache__ tests/__pycache__
