@echo off
cd /d c:\source\refchecker\web-ui
call npx playwright install chromium > install_log.txt 2>&1
call npx playwright test semantic_scholar_validation.spec.js --project=chromium > test_log.txt 2>&1
