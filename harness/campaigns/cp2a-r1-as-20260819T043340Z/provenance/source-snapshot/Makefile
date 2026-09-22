SHELL := /bin/bash

BUILD := build
LOSTBOUNDARIES_NAME := LostBoundaries
LOSTBOUNDARIES_HOTMOBILE_NAME := LostBoundariesHotMobile2027
CONTROLLER_EMPIRICAL_EVALUATION := ControllerEmpiricalEvaluation
HARNESS_SERIAL ?= emulator-5584
HARNESS_RUN_COUNT ?= 30
HARNESS_PASS_COUNT ?= 30
HARNESS_RUNS_DIR ?= harness/harness_runs
HARNESS_CAMPAIGN_PLAN ?=
PYTHON3 ?= python3
ACMART_VERSION := 2.19
ACMART_DATE := 2026/06/27
ACMART_COMMIT := 062edc8119be9067a346ce874281eab48b2c29a4
ACMART_URL := https://raw.githubusercontent.com/borisveytsman/acmart/$(ACMART_COMMIT)
ACMART_DTX_SHA256 := 4e2fd29fc8a45c3d02facb616ed29954d7932891883185460bf374303036f3e1
ACMART_INS_SHA256 := fa7daaa9375775ce699f33f909667bdb83c0408fd8d67606926df86c346c4044
ACMART_SHA256 := d754095d4c28eb01eae8683f60a9e16e5eea379d9015f8f78ca7ed4dce55fabc
BST_SHA256 := 8ec002c927068bfc5b3cfe71b66aa4767b9e485530ac3c67ba5c064df4c2e6ac
# microtype 3.2b and later support LaTeX's current \showhyphens definition.
# Pin the latest stable sources so acmart does not fall back to the host version.
MICROTYPE_VERSION := 3.2d
MICROTYPE_DATE := 2026/03/01
MICROTYPE_COMMIT := 5d3516ab2b239d3d249f30096e70cc28867e84c4
MICROTYPE_URL := https://raw.githubusercontent.com/schlcht/microtype/$(MICROTYPE_COMMIT)
MICROTYPE_DTX_SHA256 := b3daebb28aa8620660067ae037adbb1c1f8c75c59c1118891e7297d281ea0219
MICROTYPE_UTF_DTX_SHA256 := 9f0b6f2ff38855fd8c82f050f15f90607976189141f59b5107aa56882e898284
MICROTYPE_INS_SHA256 := 16ae1e080c47f0876e5b3f00e61b6987bfb73165c09559351832ecd79b6fd11e

.PHONY: all lostboundaries lostboundarieshotmobile controllerempiricalevaluation harness_runs harness_runs_csv harness_campaign_launch harness_campaign harness_campaign_stop harness_campaign_outputs harness_campaign_seal clean

# Every PDF target builds in private staging and moves only its completed PDF
# into build/. Existing build/ contents are otherwise left untouched.
.NOTPARALLEL:

all: lostboundaries lostboundarieshotmobile controllerempiricalevaluation

lostboundaries:
	@set -euo pipefail; \
	mkdir -p "$(BUILD)"; \
	work="$$(mktemp -d "$(abspath $(BUILD))/.LostBoundaries.XXXXXX")"; \
	cache="$(abspath $(BUILD))/.latex-cache"; \
	trap 'rm -rf -- "$$work" "$$cache"' EXIT; \
	mkdir -p "$$cache"; \
	fetch_cached() { \
		local name="$$1" url="$$2" expected="$$3" cached="$$cache/$$1"; \
		if [[ -f "$$cached" ]] && \
			printf '%s  %s\n' "$$expected" "$$cached" | sha256sum -c - >/dev/null 2>&1; then \
			cp -- "$$cached" "$$work/$$name"; \
			return; \
		fi; \
		curl --retry 4 --retry-delay 2 --retry-all-errors -fsSL "$$url" \
			-o "$$work/$$name.download"; \
		printf '%s  %s\n' "$$expected" "$$work/$$name.download" | sha256sum -c -; \
		cp -- "$$work/$$name.download" "$$cached"; \
		mv -- "$$work/$$name.download" "$$work/$$name"; \
	}; \
	fetch_cached acmart.dtx '$(ACMART_URL)/acmart.dtx' '$(ACMART_DTX_SHA256)'; \
	fetch_cached acmart.ins '$(ACMART_URL)/acmart.ins' '$(ACMART_INS_SHA256)'; \
	fetch_cached ACM-Reference-Format.bst '$(ACMART_URL)/ACM-Reference-Format.bst' '$(BST_SHA256)'; \
	fetch_cached microtype.dtx '$(MICROTYPE_URL)/microtype.dtx' '$(MICROTYPE_DTX_SHA256)'; \
	fetch_cached microtype-utf.dtx '$(MICROTYPE_URL)/microtype-utf.dtx' '$(MICROTYPE_UTF_DTX_SHA256)'; \
	fetch_cached microtype.ins '$(MICROTYPE_URL)/microtype.ins' '$(MICROTYPE_INS_SHA256)'; \
	(cd "$$work" && tex acmart.ins > acmart-install.log 2>&1); \
	printf '%s  %s\n' '$(ACMART_SHA256)' "$$work/acmart.cls" | sha256sum -c -; \
	printf '%s  %s\n' '$(BST_SHA256)' "$$work/ACM-Reference-Format.bst" | sha256sum -c -; \
	printf '%s  %s\n' '$(MICROTYPE_DTX_SHA256)' "$$work/microtype.dtx" | sha256sum -c -; \
	printf '%s  %s\n' '$(MICROTYPE_UTF_DTX_SHA256)' "$$work/microtype-utf.dtx" | sha256sum -c -; \
	printf '%s  %s\n' '$(MICROTYPE_INS_SHA256)' "$$work/microtype.ins" | sha256sum -c -; \
	(cd "$$work" && latex -interaction=nonstopmode -halt-on-error microtype.ins > microtype-install.log 2>&1); \
	grep -Fq '$(ACMART_DATE) v$(ACMART_VERSION)' "$$work/acmart.cls"; \
	grep -Fq '$(MICROTYPE_DATE) v$(MICROTYPE_VERSION)' "$$work/microtype.sty"; \
	grep -Fq '$(MICROTYPE_DATE) v$(MICROTYPE_VERSION)' "$$work/microtype-pdftex.def"; \
	TEXINPUTS="$$work:" BIBINPUTS=".:" BSTINPUTS="$$work:" \
		pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$$work" $(LOSTBOUNDARIES_NAME).tex > /dev/null; \
	(cd "$$work" && BIBINPUTS="$(CURDIR):" BSTINPUTS="$$work:" \
		bibtex "$(LOSTBOUNDARIES_NAME)" > /dev/null); \
	for pass in 1 2 3 4; do \
		TEXINPUTS="$$work:" BIBINPUTS=".:" BSTINPUTS="$$work:" \
			pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$$work" $(LOSTBOUNDARIES_NAME).tex > /dev/null; \
	done; \
	mv -f -- "$$work/$(LOSTBOUNDARIES_NAME).pdf" "$(BUILD)/$(LOSTBOUNDARIES_NAME).pdf"; \
	echo "Built $(BUILD)/$(LOSTBOUNDARIES_NAME).pdf"


lostboundarieshotmobile:
	@set -euo pipefail; \
	mkdir -p "$(BUILD)"; \
	work="$$(mktemp -d "$(abspath $(BUILD))/.LostBoundaries.XXXXXX")"; \
	cache="$(abspath $(BUILD))/.latex-cache"; \
	trap 'rm -rf -- "$$work" "$$cache"' EXIT; \
	mkdir -p "$$cache"; \
	fetch_cached() { \
		local name="$$1" url="$$2" expected="$$3" cached="$$cache/$$1"; \
		if [[ -f "$$cached" ]] && \
			printf '%s  %s\n' "$$expected" "$$cached" | sha256sum -c - >/dev/null 2>&1; then \
			cp -- "$$cached" "$$work/$$name"; \
			return; \
		fi; \
		curl --retry 4 --retry-delay 2 --retry-all-errors -fsSL "$$url" \
			-o "$$work/$$name.download"; \
		printf '%s  %s\n' "$$expected" "$$work/$$name.download" | sha256sum -c -; \
		cp -- "$$work/$$name.download" "$$cached"; \
		mv -- "$$work/$$name.download" "$$work/$$name"; \
	}; \
	fetch_cached acmart.dtx '$(ACMART_URL)/acmart.dtx' '$(ACMART_DTX_SHA256)'; \
	fetch_cached acmart.ins '$(ACMART_URL)/acmart.ins' '$(ACMART_INS_SHA256)'; \
	fetch_cached ACM-Reference-Format.bst '$(ACMART_URL)/ACM-Reference-Format.bst' '$(BST_SHA256)'; \
	fetch_cached microtype.dtx '$(MICROTYPE_URL)/microtype.dtx' '$(MICROTYPE_DTX_SHA256)'; \
	fetch_cached microtype-utf.dtx '$(MICROTYPE_URL)/microtype-utf.dtx' '$(MICROTYPE_UTF_DTX_SHA256)'; \
	fetch_cached microtype.ins '$(MICROTYPE_URL)/microtype.ins' '$(MICROTYPE_INS_SHA256)'; \
	(cd "$$work" && tex acmart.ins > acmart-install.log 2>&1); \
	printf '%s  %s\n' '$(ACMART_SHA256)' "$$work/acmart.cls" | sha256sum -c -; \
	printf '%s  %s\n' '$(BST_SHA256)' "$$work/ACM-Reference-Format.bst" | sha256sum -c -; \
	printf '%s  %s\n' '$(MICROTYPE_DTX_SHA256)' "$$work/microtype.dtx" | sha256sum -c -; \
	printf '%s  %s\n' '$(MICROTYPE_UTF_DTX_SHA256)' "$$work/microtype-utf.dtx" | sha256sum -c -; \
	printf '%s  %s\n' '$(MICROTYPE_INS_SHA256)' "$$work/microtype.ins" | sha256sum -c -; \
	(cd "$$work" && latex -interaction=nonstopmode -halt-on-error microtype.ins > microtype-install.log 2>&1); \
	grep -Fq '$(ACMART_DATE) v$(ACMART_VERSION)' "$$work/acmart.cls"; \
	grep -Fq '$(MICROTYPE_DATE) v$(MICROTYPE_VERSION)' "$$work/microtype.sty"; \
	grep -Fq '$(MICROTYPE_DATE) v$(MICROTYPE_VERSION)' "$$work/microtype-pdftex.def"; \
	TEXINPUTS="$$work:" BIBINPUTS=".:" BSTINPUTS="$$work:" \
		pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$$work" $(LOSTBOUNDARIES_HOTMOBILE_NAME).tex > /dev/null; \
	(cd "$$work" && BIBINPUTS="$(CURDIR):" BSTINPUTS="$$work:" \
		bibtex "$(LOSTBOUNDARIES_HOTMOBILE_NAME)" > /dev/null); \
	for pass in 1 2 3 4; do \
		TEXINPUTS="$$work:" BIBINPUTS=".:" BSTINPUTS="$$work:" \
			pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$$work" $(LOSTBOUNDARIES_HOTMOBILE_NAME).tex > /dev/null; \
	done; \
	mv -f -- "$$work/$(LOSTBOUNDARIES_HOTMOBILE_NAME).pdf" "$(BUILD)/$(LOSTBOUNDARIES_HOTMOBILE_NAME).pdf"; \
	echo "Built $(BUILD)/$(LOSTBOUNDARIES_HOTMOBILE_NAME).pdf"

controllerempiricalevaluation:
	@set -euo pipefail; \
	mkdir -p "$(BUILD)"; \
	work="$$(mktemp -d "$(abspath $(BUILD))/.ControllerEmpiricalEvaluation.XXXXXX")"; \
	trap 'rm -rf -- "$$work"' EXIT; \
	for pass in 1 2; do \
		pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$$work" \
			$(CONTROLLER_EMPIRICAL_EVALUATION).tex > /dev/null; \
	done; \
	mv -f -- "$$work/$(CONTROLLER_EMPIRICAL_EVALUATION).pdf" \
		"$(BUILD)/$(CONTROLLER_EMPIRICAL_EVALUATION).pdf"; \
	echo "Built $(BUILD)/$(CONTROLLER_EMPIRICAL_EVALUATION).pdf"

# Run the single-run harness repeatedly and retain each record in HARNESS_RUNS_DIR.
# The destination must not already exist, so retained records are never overwritten.
harness_runs:
	@set -euo pipefail; \
	count='$(HARNESS_RUN_COUNT)'; \
	serial='$(HARNESS_SERIAL)'; \
	if [[ ! "$$count" =~ ^[1-9][0-9]*$$ ]]; then \
		echo "HARNESS_RUN_COUNT must be a positive integer" >&2; \
		exit 2; \
	fi; \
	if [[ -z "$$serial" ]]; then \
		echo "HARNESS_SERIAL must not be empty" >&2; \
		exit 2; \
	fi; \
	exec 9>"$${TMPDIR:-/tmp}/lostboundaries-harness-runs.lock"; \
	if ! flock -n 9; then \
		echo "another harness campaign is already running" >&2; \
		exit 2; \
	fi; \
	output='$(HARNESS_RUNS_DIR)'; \
	if [[ -e "$$output" || -L "$$output" ]]; then \
		echo "refusing existing HARNESS_RUNS_DIR: $$output" >&2; \
		exit 2; \
	fi; \
	mkdir -- "$$output"; \
	echo "Harness evidence directory: $$output"; \
	for ((run = 1; run <= count; run++)); do \
		scratch="$$output/.attempt-evidence.json"; \
		if [[ -e "$$scratch" || -L "$$scratch" || \
		      -e "$$scratch.new" || -L "$$scratch.new" ]]; then \
			echo "refusing existing transient evidence path" >&2; \
			exit 2; \
		fi; \
		echo "[$$run/$$count] running probe harness"; \
		if $(PYTHON3) harness/probe_harness.py --serial "$$serial" \
				--evidence "$$scratch"; then \
			rc=0; \
		else \
			rc=$$?; \
		fi; \
		if [[ -e "$$scratch.new" ]]; then \
			echo "run $$run left an incomplete transient record" >&2; \
			exit 2; \
		fi; \
		if [[ ! -s "$$scratch" ]]; then \
			echo "run $$run produced no evidence record" >&2; \
			exit 2; \
		fi; \
		target="$${output}/evidence$${run}.json"; \
		if [[ -e "$$target" || -L "$$target" ]]; then \
			echo "refusing existing evidence target: $$target" >&2; \
			exit 2; \
		fi; \
		mv -- "$$scratch" "$$target"; \
		$(PYTHON3) -c 'import json, pathlib, sys; p, serial, rc = sys.argv[1], sys.argv[2], int(sys.argv[3]); d = json.loads(pathlib.Path(p).read_text()); assert d.get("schema") == 1 and d.get("experiment") == "public-api-controller-ranking"; assert isinstance(d.get("attempts"), list) and len(d["attempts"]) == 1; a = d["attempts"][0]; outcome = a.get("outcome"); assert a.get("serial") == serial; assert (outcome == "PASS" and rc == 0) or (outcome in {"FAIL", "ERROR"} and rc == 1); cleanup = a.get("cleanup"); assert isinstance(cleanup, dict) and cleanup.get("succeeded") is True' "$$target" "$$serial" "$$rc"; \
	done; \
	echo "Archived $$count harness records in $$output"

# Summarize an immutable evidence archive. The generator creates both outputs
# exclusively and refuses to replace CSV files that are already present.
harness_runs_csv:
	@set -euo pipefail; \
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -B harness/summarize_harness_runs.py \
		--input-dir '$(HARNESS_RUNS_DIR)' \
		--pass-count '$(HARNESS_PASS_COUNT)'

# Retain every attempt until 30 predeclared protocol qualifications are reached
# (at most 40 attempts). Headline outcomes never control cohort membership.
# This target is intentionally separate from the retained legacy CE2A archive.
harness_campaign_launch:
	@set -euo pipefail; \
	if [[ -z '$(HARNESS_CAMPAIGN_PLAN)' ]]; then \
		echo "HARNESS_CAMPAIGN_PLAN must identify a pre-run plan" >&2; \
		exit 2; \
	fi; \
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -B \
		harness/launch_campaign_emulator.py \
		--campaign-plan '$(HARNESS_CAMPAIGN_PLAN)'

harness_campaign:
	@set -euo pipefail; \
	if [[ -z '$(HARNESS_CAMPAIGN_PLAN)' ]]; then \
		echo "HARNESS_CAMPAIGN_PLAN must identify a pre-run plan" >&2; \
		exit 2; \
	fi; \
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -B harness/run_campaign.py \
		--campaign-plan '$(HARNESS_CAMPAIGN_PLAN)' \
		--serial '$(HARNESS_SERIAL)'

harness_campaign_stop:
	@set -euo pipefail; \
	if [[ -z '$(HARNESS_CAMPAIGN_PLAN)' ]]; then \
		echo "HARNESS_CAMPAIGN_PLAN must identify a completed campaign" >&2; \
		exit 2; \
	fi; \
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -B \
		harness/launch_campaign_emulator.py \
		--campaign-plan '$(HARNESS_CAMPAIGN_PLAN)' --stop

# Derive the raw/statistical cohort, allowance sensitivity, and paper cells.
harness_campaign_outputs:
	@set -euo pipefail; \
	if [[ -z '$(HARNESS_CAMPAIGN_PLAN)' ]]; then \
		echo "HARNESS_CAMPAIGN_PLAN must identify a completed campaign" >&2; \
		exit 2; \
	fi; \
	root="$$(dirname -- '$(HARNESS_CAMPAIGN_PLAN)')"; \
	runs="$$root/runs"; \
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -B harness/summarize_harness_runs.py \
		--input-dir "$$runs" --pass-count 30 --require-campaign; \
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -B \
		harness/summarize_allowance_sensitivity.py \
		--input-dir "$$runs" \
		--output "$$root/allowance_sensitivity.csv"; \
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -B harness/render_public_table.py \
		--statistics "$$runs/30_evidences_statistics.csv" \
		--output "$$root/table_values.csv"

harness_campaign_seal:
	@set -euo pipefail; \
	if [[ -z '$(HARNESS_CAMPAIGN_PLAN)' ]]; then \
		echo "HARNESS_CAMPAIGN_PLAN must identify a completed campaign" >&2; \
		exit 2; \
	fi; \
	root="$$(dirname -- '$(HARNESS_CAMPAIGN_PLAN)')"; \
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON3) -B harness/seal_campaign.py \
		--campaign-root "$$root"

# Remove every build product, including any staging or cache directory left
# behind by an interrupted run that never reached its cleanup trap.
clean:
	mkdir -p $(BUILD)
	find $(BUILD) -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
