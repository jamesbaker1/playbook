.PHONY: test demo export clean

test:
	PYTHONPATH=src python -m pytest -q

demo:
	PYTHONPATH=src python -m playbook_legal.demo

export: demo
	python training/export_sft.py artifacts/demo_trajectory.json artifacts/demo_sft.jsonl

clean:
	rm -rf artifacts .pytest_cache src/*/__pycache__ tests/__pycache__
