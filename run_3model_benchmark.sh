#!/bin/bash
# Run 10 ICLR paper test with 3 different models, capturing timing
cd /datadrive/refchecker

echo "=========================================="
echo "Starting 3-model benchmark: $(date)"
echo "=========================================="

# Run 1: GPT-5-mini (OpenAI)
echo ""
echo ">>> [1/3] GPT-5-mini starting at $(date)"
START1=$(date +%s)
python run_refchecker.py --paper-list test_10papers.txt \
  --llm-provider openai --llm-model gpt-5-mini \
  --report-file output/iclr10_gpt5mini_results.json \
  --report-format json --max-workers 6 2>&1 | tee /tmp/gpt5mini_run.log
END1=$(date +%s)
ELAPSED1=$((END1 - START1))
echo ">>> GPT-5-mini completed in ${ELAPSED1}s at $(date)"

# Run 2: Claude Haiku (Anthropic)
echo ""
echo ">>> [2/3] Claude Haiku starting at $(date)"
START2=$(date +%s)
python run_refchecker.py --paper-list test_10papers.txt \
  --llm-provider anthropic --llm-model claude-haiku-4-5-20250414 \
  --report-file output/iclr10_haiku_results.json \
  --report-format json --max-workers 6 2>&1 | tee /tmp/haiku_run.log
END2=$(date +%s)
ELAPSED2=$((END2 - START2))
echo ">>> Claude Haiku completed in ${ELAPSED2}s at $(date)"

# Run 3: GPT-5-nano (OpenAI)
echo ""
echo ">>> [3/3] GPT-5-nano starting at $(date)"
START3=$(date +%s)
python run_refchecker.py --paper-list test_10papers.txt \
  --llm-provider openai --llm-model gpt-5-nano \
  --report-file output/iclr10_gpt5nano_results.json \
  --report-format json --max-workers 6 2>&1 | tee /tmp/gpt5nano_run.log
END3=$(date +%s)
ELAPSED3=$((END3 - START3))
echo ">>> GPT-5-nano completed in ${ELAPSED3}s at $(date)"

echo ""
echo "=========================================="
echo "TIMING SUMMARY"
echo "=========================================="
echo "GPT-5-mini:    ${ELAPSED1}s ($(echo "scale=1; $ELAPSED1/60" | bc)min)"
echo "Claude Haiku:  ${ELAPSED2}s ($(echo "scale=1; $ELAPSED2/60" | bc)min)"
echo "GPT-5-nano:    ${ELAPSED3}s ($(echo "scale=1; $ELAPSED3/60" | bc)min)"
echo "=========================================="
echo "All runs complete at $(date)"
