## ADDED Requirements

### Requirement: Retry with exponential backoff on transient LLM errors
The LLMClient SHALL automatically retry failed API calls when the error is transient (HTTP 429 rate-limit or `overloaded_error`). Retries SHALL use exponential backoff with full jitter: `wait = min(cap, base * 2^attempt) * uniform(0.5, 1.5)` where `base = settings.llm_retry_base_delay` (default 1.0s) and `cap = 60s`. Maximum retry count SHALL be governed by `settings.llm_max_retries` (default 3).

#### Scenario: Rate limit triggers retry with backoff
- **WHEN** a call to `LLMClient.complete()` receives a `RateLimitError`
- **THEN** the client waits `min(60, 1.0 * 2^attempt) * uniform(0.5, 1.5)` seconds and retries, up to `llm_max_retries` times

#### Scenario: Overloaded error triggers retry
- **WHEN** a call receives an `APIError` with `overloaded_error` type and `settings.llm_retry_on_overloaded` is True
- **THEN** the client retries with the same backoff schedule as rate-limit errors

#### Scenario: Max retries exhausted raises original error
- **WHEN** all retry attempts are exhausted
- **THEN** the final error is re-raised to the caller

#### Scenario: Non-transient errors are not retried
- **WHEN** a call receives a 4xx error that is not 429 (e.g., 400 invalid request, 401 auth failure)
- **THEN** the error is raised immediately without retrying

### Requirement: Jitter prevents thundering herd under parallel load
The retry backoff SHALL include random jitter so that multiple concurrent callers hitting the same rate limit do not all retry at the same moment.

#### Scenario: Concurrent retries spread over time
- **WHEN** 5 concurrent trials all hit a rate-limit at the same time
- **THEN** their retry waits are individually randomized within the jitter range, not all identical

### Requirement: Retry configuration via settings
The retry behavior SHALL be configurable via environment variables / config:
- `LLM_MAX_RETRIES` → `settings.llm_max_retries` (default: 3)
- `LLM_RETRY_BASE_DELAY` → `settings.llm_retry_base_delay` (default: 1.0)
- `LLM_RETRY_ON_OVERLOADED` → `settings.llm_retry_on_overloaded` (default: True)

#### Scenario: Max retries overridden via config
- **WHEN** `LLM_MAX_RETRIES=5` is set in `.env`
- **THEN** all LLMClient instances retry up to 5 times on transient errors
