## Purpose

Extend the calibration tracker's LLM prompt export to include summaries of confirmed hypotheses. This gives the estimation pipeline (specifically Pass 3 -- calibration adjustment) awareness of the agent's own validated strengths and weaknesses, enabling the LLM to calibrate its estimates in light of statistically validated patterns from backtesting.

## MODIFIED Requirements

### Requirement: Confirmed hypothesis summaries in calibration export
The `export_calibration_for_llm()` function SHALL, after the existing category breakdown section, append a summary of all confirmed hypotheses by calling `get_confirmed_hypotheses_summary()`. If no confirmed hypotheses exist or the hypothesis system is not initialized, this section SHALL be silently omitted.

#### Scenario: Calibration export includes confirmed hypotheses
- **GIVEN** two confirmed hypotheses: "probable-no-alpha" at 0.75 confidence and "mid-volume-sweet-spot" at 0.60 confidence
- **WHEN** `export_calibration_for_llm()` is called
- **THEN** the returned text includes a "Validated Findings from Backtesting" section listing both hypotheses with their names, confidence percentages, and descriptions

#### Scenario: Calibration export with no confirmed hypotheses
- **GIVEN** all hypotheses are in `proposed` or `testing` status
- **WHEN** `export_calibration_for_llm()` is called
- **THEN** the returned text does not contain a hypothesis section; the output is identical to the current behavior

#### Scenario: Calibration export when hypothesis system not initialized
- **GIVEN** the backtest database does not exist or the hypothesis tables have not been created
- **WHEN** `export_calibration_for_llm()` is called
- **THEN** the hypothesis section is silently omitted (exception caught), and the rest of the calibration export is returned normally

### Requirement: Hypothesis summary format
The `get_confirmed_hypotheses_summary()` function SHALL return a markdown-formatted string containing: a "Validated Findings from Backtesting" header, a list of confirmed hypotheses (each showing name in bold, confidence as a percentage, and description), and a closing instruction for the LLM to consider these findings during calibration. Hypotheses SHALL be ordered by confidence score descending.

#### Scenario: Summary format for single hypothesis
- **GIVEN** one confirmed hypothesis "probable-no-alpha" with `confidence_score=0.80` and description "Agent outperforms market on markets where the market price implies probable NO"
- **WHEN** `get_confirmed_hypotheses_summary()` is called
- **THEN** the returned text contains: a header line, a bullet point `- **probable-no-alpha** (confidence: 80%): Agent outperforms market on markets where the market price implies probable NO`, and a closing instruction line

#### Scenario: Summary returns None when no confirmed hypotheses
- **GIVEN** zero hypotheses with `status='confirmed'`
- **WHEN** `get_confirmed_hypotheses_summary()` is called
- **THEN** the function returns None

#### Scenario: Multiple confirmed hypotheses ordered by confidence
- **GIVEN** three confirmed hypotheses with confidence scores 0.80, 0.60, and 0.45
- **WHEN** `get_confirmed_hypotheses_summary()` is called
- **THEN** the hypotheses are listed in descending confidence order: 80%, 60%, 45%

### Requirement: Hypothesis context informs LLM estimation
The hypothesis summaries appended to the calibration export SHALL be phrased as factual findings for the LLM to consider, not as directives. The LLM retains full autonomy to override these findings based on market-specific context.

#### Scenario: Hypothesis text is informational, not directive
- **GIVEN** a confirmed hypothesis summary is included in the calibration export
- **WHEN** the LLM reads the calibration prompt during Pass 3
- **THEN** the text presents findings as "statistically validated patterns in your own prediction performance" and asks the LLM to "consider these findings when calibrating", not to blindly apply them
