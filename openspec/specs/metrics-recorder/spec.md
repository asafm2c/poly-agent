## Requirements

### Requirement: Metric events database table
The agent SHALL store operational metric events in a `metric_events` table with columns: `id` (INTEGER PRIMARY KEY AUTOINCREMENT), `timestamp` (TEXT NOT NULL, ISO8601), `event_type` (TEXT NOT NULL), and `data` (TEXT NOT NULL, JSON). The table SHALL be created via schema migration v3 in the existing migration array. An index SHALL exist on `(event_type, timestamp)`.

#### Scenario: Migration applied on startup
- **WHEN** the agent starts with a database at schema version 2
- **THEN** the `metric_events` table and its index are created, and schema_version is updated to 3

#### Scenario: Migration idempotent on already-migrated database
- **WHEN** the agent starts with a database already at schema version 3
- **THEN** no migration is applied and the existing table is unchanged

### Requirement: Metrics recorder module
The agent SHALL provide a `metrics.record(event_type, **data)` module-level function that inserts a single row into `metric_events` with the current UTC timestamp, the event type string, and the keyword arguments serialized as a JSON string. The function SHALL silently catch and log any database errors without disrupting the caller.

#### Scenario: Record a metric event
- **WHEN** `metrics.record("llm_call", model="sonnet", input_tokens=420, output_tokens=128, cost=0.003)` is called
- **THEN** a row is inserted into `metric_events` with `event_type="llm_call"` and `data` containing `{"model": "sonnet", "input_tokens": 420, "output_tokens": 128, "cost": 0.003}`

#### Scenario: Database not initialized
- **WHEN** `metrics.record()` is called before the database is initialized or the table doesn't exist
- **THEN** the error is logged at DEBUG level and the caller is not interrupted

### Requirement: LLM call instrumentation
The `LLMClient.complete()` method SHALL record a metric event of type `llm_call` after each successful call, including: `model` (string), `input_tokens` (int), `output_tokens` (int), `cost` (float, estimated), and `latency_ms` (int, wall-clock time of the API call).

#### Scenario: Successful LLM call
- **WHEN** the Anthropic API returns a successful response
- **THEN** a `llm_call` metric event is recorded with the model name, token counts from `response.usage`, estimated cost, and measured latency

#### Scenario: LLM call with retries
- **WHEN** the first attempt gets a RateLimitError and the second succeeds
- **THEN** one `llm_call` event is recorded (for the success) and one `api_error` event is recorded (for the rate limit)

### Requirement: API call instrumentation
The `GammaClient`, `ClobClient`, and `WebSearcher` classes SHALL record a metric event of type `api_call` for each HTTP request, including: `service` ("gamma", "clob", or "tavily"), `endpoint` (the URL path or method name), `status` (HTTP status code or "error"), and `latency_ms` (wall-clock time). On HTTP errors, an additional `api_error` event SHALL be recorded with the error message.

#### Scenario: Successful Gamma API call
- **WHEN** `GammaClient.fetch_markets()` receives a 200 response in 340ms
- **THEN** an `api_call` event is recorded with `service="gamma"`, `endpoint="/markets"`, `status=200`, `latency_ms=340`

#### Scenario: CLOB API error
- **WHEN** `ClobClient.get_price()` raises an httpx.HTTPError
- **THEN** an `api_call` event is recorded with `status="error"` and an `api_error` event is recorded with `service="clob"`, `endpoint="/price"`, and `error` containing the error message

#### Scenario: Tavily search call
- **WHEN** `WebSearcher.search()` executes successfully
- **THEN** an `api_call` event is recorded with `service="tavily"`, `endpoint="search"`, and the response status

### Requirement: Metric event retention cleanup
The scheduler's daily report job SHALL clean up metric events older than the configured retention period (default 30 days). A `cleanup_old_metrics(retention_days)` function SHALL delete rows where `timestamp` is older than the cutoff and return the count of deleted rows. The count SHALL be logged at INFO level.

#### Scenario: Daily cleanup removes old events
- **WHEN** the daily report job runs and metric events older than 30 days exist
- **THEN** those events are deleted and the count is logged

#### Scenario: No old events to clean
- **WHEN** the daily report job runs and no metric events are older than 30 days
- **THEN** the cleanup function returns 0 and no rows are deleted
