#!/usr/bin/env bash
set -euo pipefail
# Run from any directory; first argument optionally overrides the log root.
decision_root="$(cd "$(dirname "$0")" && pwd)"
project_root="$(dirname "$decision_root")"
log_root="${1:-/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_7/RA}"
cd "$project_root"
c++ -std=c++17 -O2 -ffunction-sections -fdata-sections \
  -I source/Lib -I thirdparty/sadl -I thirdparty \
  decisionTree/extract.cpp source/Lib/CommonLib/Mv.cpp \
  -Wl,--gc-sections -o decisionTree/extract
decisionTree/extract "$log_root" decisionTree/data
# train.py validates aggregate count, but re-extraction could keep the count
# while changing content. Always rebuild aggregation in the full pipeline.
python decisionTree/train.py --rebuild-aggregate
