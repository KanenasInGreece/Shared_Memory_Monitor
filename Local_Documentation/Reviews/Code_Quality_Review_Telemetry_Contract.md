# Code Quality Review: Telemetry Contract (`last_error.superseded` & `last_error.age_seconds`)

**Reviewer:** Code Quality Reviewer Subagent  
**Date:** 2026-08-26  
**Target Files:**
- [`scratch/consolidation_proposal.py`](file:///home/xenofon/.gemini/antigravity-cli/brain/f1e8cf14-b063-4643-98a1-9d88db071765/scratch/consolidation_proposal.py)
- [`scratch/dashboard_proposal.html`](file:///home/xenofon/.gemini/antigravity-cli/brain/f1e8cf14-b063-4643-98a1-9d88db071765/scratch/dashboard_proposal.html)
- [`telemetry_contract_proposal.md`](file:///home/xenofon/.gemini/antigravity-cli/brain/f1e8cf14-b063-4643-98a1-9d88db071765/telemetry_contract_proposal.md)

---

## 1. Context & Scope

Review of the proposed telemetry contract changes implementing support for the gateway's `last_error.superseded` and `last_error.age_seconds` payload fields in consolidation cycle normalization and dashboard rendering.

---

## 2. Findings

### A. Telemetry Normalization ([`consolidation.py`](file:///home/xenofon/grok-labs/projects/shared-memory-monitor/src/sm_telemetry_monitor/consolidation.py))
- **Contract Extraction**: `_normalize_cycle` properly extracts `age_seconds` via `_num_or_none(err.get("age_seconds"))` and extracts/casts `superseded` via `bool(superseded)` when present.
- **Humanized Duration**: Computes `age_human` using the existing [`humanize_age`](file:///home/xenofon/grok-labs/projects/shared-memory-monitor/src/sm_telemetry_monitor/consolidation.py#L110-L128) helper when `age_seconds` is not `None`.
- **Backward Compatibility**: If `superseded` is `None` (omitted by older gateway versions), the fallback logic accurately reproduces the prior filtering semantics (`superseded = not (outcome not in ("completed", "deferred") or consecutive_failures > 0)`).
- **Structure Integrity**: Returns a consistent dictionary structure containing `class`, `msg`, `superseded`, `age_seconds`, and `age_human` whenever `last_error` is a dict, and `None` otherwise.

### B. Frontend Rendering ([`dashboard.html`](file:///home/xenofon/grok-labs/projects/shared-memory-monitor/static/dashboard.html))
- **Superseded Display**: When `c.last_error.superseded` is `true`, renders `last err <class> <age> ago` (handling `age_human` whether or not it already contains the suffix `"ago"`). Falls back cleanly to `last err <class>` when `age_human` is absent.
- **Active Error Display**: When `c.last_error.superseded` is `false`, preserves standard error formatting (`${c.last_error.class}: ${c.last_error.msg || ""}`).
- **Null Safety**: Optional chaining (`c.last_error?.class`) ensures no runtime errors if `last_error` is null or undefined.

### C. Security & Robustness
- **XSS Protection**: Dynamic error strings continue to be properly escaped via `esc(err)` before insertion into the table cell DOM.
- **Message Sanitization**: Error messages remain passed through `sanitize_error()` on the backend, preventing leak of sensitive tokens or unescaped control characters.
- **Defensive Type Handling**: `_num_or_none` safely handles string, integer, float, and unexpected types without raising unhandled exceptions.

### D. Test Suite Considerations
- **FYI / Merge Note**: In [`tests/test_consolidation.py`](file:///home/xenofon/grok-labs/projects/shared-memory-monitor/tests/test_consolidation.py#L192-L214), `test_stale_last_error_suppressed_after_completion` currently asserts `self.assertIsNone(fact["last_error"])` because older code dropped the error dictionary entirely. With the new contract, the dictionary is retained with `fact["last_error"]["superseded"] is True`. When merging, this assertion should be updated and test cases added for `superseded`, `age_seconds`, and `age_human`.

---

## 3. Verdict

**APPROVE**

The proposed implementation in `scratch/consolidation_proposal.py` and `scratch/dashboard_proposal.html` accurately implements the contract specification, maintains backward compatibility, and upholds code quality and security standards.
