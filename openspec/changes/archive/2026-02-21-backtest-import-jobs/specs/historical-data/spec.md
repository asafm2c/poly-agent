## MODIFIED Requirements

### Requirement: Collection progress tracking and resumption
The system SHALL track collection progress so that interrupted runs can resume without re-fetching already-collected data. Every collection run SHALL be recorded in `bt_import_jobs` with progress counters updated per batch, enabling external observers (dashboard, CLI) to monitor status without blocking the collection process.

#### Scenario: Interrupted collection resumes
- **WHEN** collection is interrupted after fetching 5,000 of 30,000 markets' price histories
- **THEN** re-running `backtest collect` skips the 5,000 already-collected markets and continues with the remaining 25,000

#### Scenario: Collection progress logged
- **WHEN** collection is in progress
- **THEN** the system logs progress every 100 markets: "Collected 100/30000 markets (0.3%), 15 skipped (no tokens)"

#### Scenario: Collection progress written to bt_import_jobs
- **WHEN** collection is in progress
- **THEN** the `bt_import_jobs` row for the current run is updated with current `markets_done`, `histories_done`, `histories_skipped`, and `updated_at` at least every 50 records

#### Scenario: Job row status reflects terminal state
- **WHEN** collection completes successfully
- **THEN** the job row has `status='done'` and `completed_at` set

#### Scenario: Job row reflects cancellation via SIGTERM
- **WHEN** the collection process receives SIGTERM
- **THEN** the job row has `status='cancelled'` before the process exits
