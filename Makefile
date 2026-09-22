SHELL := /bin/bash

PYTHON3 ?= python3
HARNESS_SERIAL ?= emulator-5584
HARNESS_CAMPAIGN_PLAN ?=

.PHONY: verify verify-deep reanalyze reanalyze-deep \
	campaign-launch campaign-run campaign-stop campaign-outputs campaign-seal

verify:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -I verify_artifacts.py

verify-deep:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -I verify_artifacts.py --deep

reanalyze:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -I reanalyze_campaign.py

reanalyze-deep:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -I reanalyze_campaign.py --deep

campaign-launch:
	@set -euo pipefail; \
	test -n '$(HARNESS_CAMPAIGN_PLAN)' || \
		{ echo "HARNESS_CAMPAIGN_PLAN must identify a new pre-run plan" >&2; exit 2; }; \
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -B \
		harness/launch_campaign_emulator.py \
		--campaign-plan '$(HARNESS_CAMPAIGN_PLAN)'

campaign-run:
	@set -euo pipefail; \
	test -n '$(HARNESS_CAMPAIGN_PLAN)' || \
		{ echo "HARNESS_CAMPAIGN_PLAN must identify a new pre-run plan" >&2; exit 2; }; \
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -B harness/run_campaign.py \
		--campaign-plan '$(HARNESS_CAMPAIGN_PLAN)' \
		--serial '$(HARNESS_SERIAL)'

campaign-stop:
	@set -euo pipefail; \
	test -n '$(HARNESS_CAMPAIGN_PLAN)' || \
		{ echo "HARNESS_CAMPAIGN_PLAN must identify a new campaign" >&2; exit 2; }; \
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -B \
		harness/launch_campaign_emulator.py \
		--campaign-plan '$(HARNESS_CAMPAIGN_PLAN)' --stop

campaign-outputs:
	@set -euo pipefail; \
	test -n '$(HARNESS_CAMPAIGN_PLAN)' || \
		{ echo "HARNESS_CAMPAIGN_PLAN must identify a new completed campaign" >&2; exit 2; }; \
	root="$$(dirname -- '$(HARNESS_CAMPAIGN_PLAN)')"; \
	runs="$$root/runs"; \
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -B harness/summarize_harness_runs.py \
		--input-dir "$$runs" --pass-count 30 --require-campaign; \
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -B \
		harness/summarize_allowance_sensitivity.py \
		--input-dir "$$runs" --output "$$root/allowance_sensitivity.csv"; \
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -B harness/render_public_table.py \
		--statistics "$$runs/30_evidences_statistics.csv" \
		--output "$$root/table_values.csv"

campaign-seal:
	@set -euo pipefail; \
	test -n '$(HARNESS_CAMPAIGN_PLAN)' || \
		{ echo "HARNESS_CAMPAIGN_PLAN must identify a new completed campaign" >&2; exit 2; }; \
	root="$$(dirname -- '$(HARNESS_CAMPAIGN_PLAN)')"; \
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -B harness/seal_campaign.py \
		--campaign-root "$$root"
