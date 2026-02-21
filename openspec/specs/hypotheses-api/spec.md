## Purpose

Route module (`routes/hypotheses.py`) serving hypothesis-tracker data from `backtest.db` as JSON API endpoints under `/api/hypotheses/`. Reads from `bt_hypotheses`, `bt_hypothesis_evidence`, and `bt_hypothesis_actions` tables. All endpoints guard on both `backtest_db is None` and `table_exists("bt_hypotheses")` to handle cases where the backtest DB exists but the hypothesis schema has not been applied yet.

## Requirements

### Requirement 1: Hypothesis listing endpoint
The dashboard SHALL expose `GET /api/hypotheses/list` returning a JSON object with `available` (boolean, false if backtest DB missing), `tables_exist` (boolean, false if `bt_hypotheses` table missing), and a `hypotheses` array. Each hypothesis object SHALL include: `id`, `title`, `description`, `status`, `category`, `volume_min`, `volume_max`, `model`, `confidence`, `created_at`, `updated_at`, `evidence_count` (from LEFT JOIN on `bt_hypothesis_evidence`), and `last_evidence_at`. Hypotheses SHALL be ordered by `updated_at` descending. The endpoint SHALL accept an optional `status` query parameter to filter by hypothesis status.

#### Scenario: List all hypotheses
- **GIVEN** `backtest.db` exists with `bt_hypotheses` containing 5 hypotheses across statuses
- **WHEN** a client requests `GET /api/hypotheses/list`
- **THEN** the response has `available: true`, `tables_exist: true`, and `hypotheses` contains 5 objects ordered by `updated_at` descending

#### Scenario: Filter by status
- **GIVEN** 5 hypotheses exist: 2 testing, 1 confirmed, 1 proposed, 1 rejected
- **WHEN** a client requests `GET /api/hypotheses/list?status=testing`
- **THEN** the response contains only the 2 hypotheses with `status: "testing"`

#### Scenario: Invalid status parameter
- **GIVEN** hypotheses exist
- **WHEN** a client requests `GET /api/hypotheses/list?status=invalid_value`
- **THEN** the response contains an empty `hypotheses` array (no match)

#### Scenario: Backtest DB does not exist
- **GIVEN** `app.state.backtest_db` is `None`
- **WHEN** a client requests `GET /api/hypotheses/list`
- **THEN** the response is `{"hypotheses": [], "available": false, "tables_exist": false}`

#### Scenario: Backtest DB exists but hypothesis tables missing
- **GIVEN** `backtest.db` exists but the hypothesis-tracker migration has not run
- **WHEN** a client requests `GET /api/hypotheses/list`
- **THEN** the response is `{"hypotheses": [], "available": true, "tables_exist": false}`

### Requirement 2: Hypothesis evidence endpoint
The dashboard SHALL expose `GET /api/hypotheses/{id}/evidence` returning a JSON object with `hypothesis_id` and an `evidence` array. Each evidence object SHALL include: `id`, `run_id`, `brier_diff`, `p_value`, `sample_size`, `supports` (boolean), `notes`, `created_at`, `run_started_at` (from LEFT JOIN on `bt_simulation_runs`), `run_agent_brier`, and `run_market_brier`. Evidence SHALL be ordered by `created_at` descending.

#### Scenario: Hypothesis with evidence records
- **GIVEN** hypothesis_id 1 has 3 evidence records linked to simulation runs
- **WHEN** a client requests `GET /api/hypotheses/1/evidence`
- **THEN** the response has `hypothesis_id: 1` and `evidence` contains 3 objects with run-level Brier scores from the joined `bt_simulation_runs` table

#### Scenario: Hypothesis with no evidence
- **GIVEN** hypothesis_id 2 has been proposed but has no evidence records
- **WHEN** a client requests `GET /api/hypotheses/2/evidence`
- **THEN** the response has `hypothesis_id: 2` and `evidence: []`

#### Scenario: Invalid hypothesis ID
- **GIVEN** no hypothesis with id 999 exists
- **WHEN** a client requests `GET /api/hypotheses/999/evidence`
- **THEN** the response has `hypothesis_id: 999` and `evidence: []`

#### Scenario: Backtest DB unavailable
- **GIVEN** `app.state.backtest_db` is `None`
- **WHEN** a client requests `GET /api/hypotheses/1/evidence`
- **THEN** the response has `hypothesis_id: 1` and `evidence: []`

#### Scenario: Evidence linked to deleted run
- **GIVEN** an evidence record references `run_id: 5` but that run has been deleted from `bt_simulation_runs`
- **WHEN** a client requests `GET /api/hypotheses/1/evidence`
- **THEN** the evidence record is returned with `run_started_at: null`, `run_agent_brier: null`, and `run_market_brier: null` (LEFT JOIN produces nulls)

### Requirement 3: Hypothesis actions endpoint
The dashboard SHALL expose `GET /api/hypotheses/{id}/actions` returning a JSON object with `hypothesis_id` and an `actions` array. Each action object SHALL include: `id`, `action_type`, `config` (JSON string), `strength`, `active` (boolean), and `created_at`. Actions SHALL be ordered by `created_at` descending.

#### Scenario: Hypothesis with active actions
- **GIVEN** hypothesis_id 1 has 2 actions, one active and one inactive
- **WHEN** a client requests `GET /api/hypotheses/1/actions`
- **THEN** the response has `hypothesis_id: 1` and `actions` contains 2 objects ordered by `created_at` descending

#### Scenario: Hypothesis with no actions
- **GIVEN** hypothesis_id 3 has no actions
- **WHEN** a client requests `GET /api/hypotheses/3/actions`
- **THEN** the response has `hypothesis_id: 3` and `actions: []`

#### Scenario: Backtest DB unavailable
- **GIVEN** `app.state.backtest_db` is `None`
- **WHEN** a client requests `GET /api/hypotheses/1/actions`
- **THEN** the response has `hypothesis_id: 1` and `actions: []`

#### Scenario: Hypothesis tables missing
- **GIVEN** `backtest.db` exists but `bt_hypothesis_actions` table does not exist
- **WHEN** a client requests `GET /api/hypotheses/1/actions`
- **THEN** the response has `hypothesis_id: 1` and `actions: []`

### Requirement 4: Dual guard pattern
Every hypotheses endpoint SHALL first check `backtest_db is None` (returns `available: false` where applicable) and then check `table_exists("bt_hypotheses")` before executing queries (returns `tables_exist: false` where applicable). This two-level guard SHALL prevent crashes when the hypothesis-tracker schema has not been applied.

#### Scenario: Guard order
- **GIVEN** `backtest_db` is not `None` but `bt_hypotheses` table does not exist
- **WHEN** any hypotheses endpoint is called
- **THEN** the `table_exists` check runs (not the query) and the response indicates tables do not exist

## Scenarios

### Scenario: End-to-end hypothesis exploration
- **GIVEN** `backtest.db` contains 3 hypotheses, hypothesis_id 1 has 4 evidence records and 2 actions
- **WHEN** the frontend fetches `/list`, then `/1/evidence`, then `/1/actions`
- **THEN** the list shows all 3 hypotheses with correct evidence counts, the evidence detail shows 4 records with linked run data, and the actions detail shows 2 records

### Scenario: Forward compatibility
- **GIVEN** the hypothesis-tracker change has not been implemented yet
- **WHEN** all hypotheses endpoints are called
- **THEN** all return gracefully with empty data and `tables_exist: false`, allowing the frontend to display helpful guidance
