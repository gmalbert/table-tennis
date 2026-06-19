# GitHub Actions Node.js 24 Compatibility Fix

## What changed

Updated GitHub Actions workflow steps across the repository to use action versions compatible with Node.js 24.

Specifically:

- `actions/checkout@v4` → `actions/checkout@v5`
- `actions/setup-python@v5` → `actions/setup-python@v6`

## Why this fix was needed

GitHub Actions runners now force Node.js 24 for workflows, and older actions targeting Node.js 20 emit deprecation warnings or fail.

## Files updated

- `.github/workflows/nightly-predictions.yml`
- `.github/workflows/db-refresh.yml`
- `.github/workflows/flashscore-collect.yml`

## Result

All affected workflows now use modern action versions that support the current GitHub Actions runtime, eliminating the Node.js 20 deprecation warning.