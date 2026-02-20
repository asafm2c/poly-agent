## 1. Fix analyze CLI tuple unpacking

- [x] 1.1 Unpack `build_recommendation()` return value into `(rec, adj_edge, req_threshold)` in `cli/main.py`
- [x] 1.2 Display adjusted edge and required threshold in CLI output when trade is recommended
- [x] 1.3 Verify `if rec:` correctly evaluates to `False` when `rec is None`

## 2. Fix simulation per-trial cost tracking

- [x] 2.1 Snapshot cumulative cost before each trial in `run_simulation()` loop
- [x] 2.2 Compute trial cost as delta (current - previous) after estimation
- [x] 2.3 Update `total_cost` to use sum of deltas instead of final cumulative value

## 3. Tests

- [x] 3.1 Add test verifying per-trial cost delta computation
- [x] 3.2 Run full test suite to confirm no regressions
