## Purpose

Define the database schema for hypothesis tracking in `backtest.db`. Three new tables (`bt_hypotheses`, `bt_hypothesis_evidence`, `bt_hypothesis_actions`) store testable hypotheses about agent performance, link simulation evidence to those hypotheses, and translate confirmed findings into pipeline parameter adjustments. The schema supports a full status lifecycle (proposed/testing/confirmed/rejected/invalidated), per-hypothesis filter criteria for targeted simulation, and confidence decay parameters for temporal validity.

## Requirements

1. The backtest database SHALL include a `bt_hypotheses` table with columns: `id` (INTEGER PRIMARY KEY AUTOINCREMENT), `name` (TEXT NOT NULL UNIQUE), `description` (TEXT NOT NULL), `status` (TEXT NOT NULL DEFAULT 'proposed'), `confidence_score` (REAL DEFAULT 0.0), `category_filter` (TEXT, nullable), `volume_min` (REAL, nullable), `volume_max` (REAL, nullable), `model_filter` (TEXT, nullable), `temporal_filter` (TEXT, nullable -- JSON), `proposed_at` (TEXT NOT NULL), `first_tested_at` (TEXT, nullable), `confirmed_at` (TEXT, nullable), `last_evaluated_at` (TEXT, nullable), `invalidated_at` (TEXT, nullable), `decay_half_life_days` (INTEGER DEFAULT 90), `retest_threshold` (REAL DEFAULT 0.50), `proposed_by` (TEXT DEFAULT 'user'), and `notes` (TEXT, nullable).

2. The `status` column SHALL have a CHECK constraint restricting values to: `proposed`, `testing`, `confirmed`, `rejected`, `invalidated`.

3. The `name` column SHALL have a UNIQUE constraint to prevent duplicate hypotheses.

4. The backtest database SHALL include a `bt_hypothesis_evidence` table with columns: `id` (INTEGER PRIMARY KEY AUTOINCREMENT), `hypothesis_id` (INTEGER NOT NULL, FK to `bt_hypotheses.id`), `run_id` (INTEGER NOT NULL, FK to `bt_simulation_runs.id`), `recorded_at` (TEXT NOT NULL), `trial_count` (INTEGER NOT NULL), `agent_brier` (REAL, nullable), `market_brier` (REAL, nullable), `brier_diff` (REAL, nullable), `simulated_pnl` (REAL, nullable), `p_value` (REAL, nullable), `effect_size` (REAL, nullable), `supports_hypothesis` (INTEGER, nullable), and `evaluation_notes` (TEXT, nullable).

5. The `supports_hypothesis` column SHALL store: 1 (supports), 0 (contradicts), or NULL (inconclusive).

6. The backtest database SHALL include a `bt_hypothesis_actions` table with columns: `id` (INTEGER PRIMARY KEY AUTOINCREMENT), `hypothesis_id` (INTEGER NOT NULL, FK to `bt_hypotheses.id`), `action_type` (TEXT NOT NULL), `config` (TEXT NOT NULL -- JSON), `base_strength` (REAL NOT NULL DEFAULT 1.0), `active` (INTEGER NOT NULL DEFAULT 0), `created_at` (TEXT NOT NULL), `activated_at` (TEXT, nullable), and `deactivated_at` (TEXT, nullable).

7. The `action_type` column SHALL have a CHECK constraint restricting values to: `edge_override`, `category_target`, `category_avoid`, `model_preference`, `weight_adjustment`.

8. The database SHALL include indexes: `idx_bt_hypotheses_status` on `bt_hypotheses(status)`, `idx_bt_hyp_evidence_hyp` on `bt_hypothesis_evidence(hypothesis_id)`, `idx_bt_hyp_evidence_run` on `bt_hypothesis_evidence(run_id)`, `idx_bt_hyp_actions_hyp` on `bt_hypothesis_actions(hypothesis_id)`, `idx_bt_hyp_actions_active` on `bt_hypothesis_actions(active)`.

9. All three tables SHALL be created via `CREATE TABLE IF NOT EXISTS` statements added to the existing `SCHEMA_SQL` in `database.py`.

10. The `category_filter` column SHALL use NULL to represent null-category prediction markets and `*` to represent all categories.

11. The `temporal_filter` column SHALL store a JSON string with optional keys `horizon_days` (integer) and `regime` (string), or NULL when no temporal filter applies.

12. The `init_backtest_db()` function SHALL call `seed_hypotheses()` after schema creation to populate the initial four seed hypotheses when the `bt_hypotheses` table is empty.

13. The `seed_hypotheses()` function SHALL insert exactly 4 seed hypotheses (`probable-no-alpha`, `mid-volume-sweet-spot`, `high-volume-efficient`, `sports-no-alpha`) with `status='proposed'`, `proposed_by='seed'`, and their associated inactive actions, only when the `bt_hypotheses` table contains zero rows.

14. The `seed_hypotheses()` function SHOULD be idempotent: calling it when hypotheses already exist SHALL insert zero rows and return 0.

## Scenarios

#### Scenario: Schema tables created on DB init
- **GIVEN** a fresh backtest database with no hypothesis tables
- **WHEN** `init_backtest_db()` is called
- **THEN** the `bt_hypotheses`, `bt_hypothesis_evidence`, and `bt_hypothesis_actions` tables exist with all specified columns and constraints, and all five indexes are created

#### Scenario: Seed hypotheses populated on first init
- **GIVEN** a fresh backtest database where `bt_hypotheses` has zero rows
- **WHEN** `init_backtest_db()` completes
- **THEN** `bt_hypotheses` contains exactly 4 rows with names `probable-no-alpha`, `mid-volume-sweet-spot`, `high-volume-efficient`, `sports-no-alpha`, all with `status='proposed'` and `proposed_by='seed'`

#### Scenario: Seed hypothesis actions created as inactive
- **GIVEN** a fresh backtest database
- **WHEN** `seed_hypotheses()` completes
- **THEN** `bt_hypothesis_actions` contains rows linked to each seed hypothesis (e.g., `probable-no-alpha` has an `edge_override` action, `mid-volume-sweet-spot` has `edge_override` and `weight_adjustment` actions), and all have `active=0`

#### Scenario: Seed hypotheses idempotent on re-init
- **GIVEN** a backtest database that already contains the 4 seed hypotheses
- **WHEN** `seed_hypotheses()` is called again
- **THEN** zero new rows are inserted and the function returns 0

#### Scenario: Status constraint enforced
- **GIVEN** a `bt_hypotheses` table
- **WHEN** an INSERT or UPDATE attempts to set `status='unknown'`
- **THEN** the database raises a constraint violation error

#### Scenario: Unique name constraint enforced
- **GIVEN** a hypothesis with `name='probable-no-alpha'` already exists
- **WHEN** an INSERT attempts to create another hypothesis with `name='probable-no-alpha'`
- **THEN** the database raises a unique constraint violation error

#### Scenario: Action type constraint enforced
- **GIVEN** a `bt_hypothesis_actions` table
- **WHEN** an INSERT attempts to set `action_type='invalid_type'`
- **THEN** the database raises a constraint violation error

#### Scenario: Evidence foreign key references valid hypothesis
- **GIVEN** a `bt_hypothesis_evidence` table
- **WHEN** an INSERT references a `hypothesis_id` that does not exist in `bt_hypotheses`
- **THEN** the insert fails with a foreign key constraint error (when foreign keys are enforced)

#### Scenario: Null category filter represents prediction markets
- **GIVEN** a seed hypothesis `probable-no-alpha`
- **WHEN** its row is queried from `bt_hypotheses`
- **THEN** `category_filter` is NULL, indicating it applies to null-category prediction markets

#### Scenario: Temporal filter stores JSON
- **GIVEN** a seed hypothesis `probable-no-alpha` with a 7-day horizon filter
- **WHEN** its `temporal_filter` is loaded and parsed as JSON
- **THEN** the result is `{"horizon_days": 7}`
