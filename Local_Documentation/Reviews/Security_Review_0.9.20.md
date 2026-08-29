# Security Review 0.9.20

## Context
Review of commit `b02ea17` on branch `feature/v0.9.20-latency-placement` for Shared Memory Monitor. 
Focus areas:
- XSS: innerHTML vs textContent vs esc() on model, backend URL, rem.note, hint line, pool line
- No secrets in passthrough 
- No new routes, no token widening, credentials still do not flip deck status (I2)
- Constant href `/logs?source=credential_audit` only
- Safe width interpolation (`style=width:${frac}%` only when frac is a number)

## Findings

*   **XSS: `rem.note`** (FYI)
    Implemented securely using `.textContent`.
*   **XSS: `m.model`, `m.backend`, `nServ`, `nTot`** (FYI)
    Variables are properly escaped using the `esc()` function before insertion into HTML template literals.
*   **XSS: Hint Line** (FYI)
    The `hint.innerHTML` safely escapes dynamic data (`baseText`) via `esc()`. 
*   **Constant href** (FYI)
    The anchor tag in the hint uses a static, hardcoded `href="/logs?source=credential_audit"`. This prevents any user-controlled URL injection.
*   **No Secrets in Passthrough** (FYI)
    The `backend` attribute is passed through. Backend URLs are public-facing operational configuration and not secrets. No credentials or keys are exposed.
*   **Routes & Credentials (I2)** (FYI)
    No new backend routes are added, and no tokens are widened. Credential conditions (`token_verify_failed`, `audit_log_dropped`, `routeDenied`) are purely used to toggle UI warnings (`credsWarn`, `doorWarn`) and do not manipulate the underlying deck status.
*   **Numeric Width Interpolation** (Required)
    While the `isMixed` block enforces strict type checking (`typeof m.service_frac === "number" && typeof m.contention_frac === "number"`), the fallback `else` block (for non-wall, non-mixed metrics) lacks this check for `sf` and `cf`. To satisfy the requirement of interpolating widths *only* when the fraction is a number, the `else` block must also enforce `typeof sf === "number"` and `typeof cf === "number"` before injecting them into `style="width:...%"`.

## Verdict
**REQUEST CHANGES**
