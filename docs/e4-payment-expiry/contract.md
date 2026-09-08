# E4 / PAYMENT_STATUS_EXPIRY_TIME_FORMAT_CONSISTENCY

The payment countdown must represent the instant supplied by the supported
payment-session timestamp. The previous code appended `Z` to an explicit UTC
offset and displayed `NaN:NaN` for valid PostgreSQL datetime serialization.

The parser accepts canonical dates with seconds, `T` or space separators,
optional one-to-six fractional digits, and `Z` or explicit `+/-HH:mm` offsets.
Legacy timestamps without an offset retain their UTC interpretation. Calendar
round-trip validation rejects impossible dates instead of normalizing them.
Wrong types, oversized strings and malformed dates display the fixed text
«Срок действия реквизитов уточняется.» without changing canonical order status.
The raw date is never interpolated into HTML.

The timer owns at most one interval; an initially expired countdown does not
register another interval after rendering the expiry view. Local expiry continues
to leave polling enabled. Receipt, verification, terminal and paid/sent precedence
and existing instruction availability rules remain unchanged.

Only inline payment-page JavaScript changes. Numeric payment rendering, Python
interpolations, API/database/authentication/redirect boundaries and all 16 retained
runtime dependencies stay exact. The primary authors code and focused tests;
acceptance independently owns exact-handler/browser fixtures; security reviews
the diff and adversarial cases; operations prepares reversible single-file rollout.
The two independent reviewers also assess the rollout recipe. Browser testing
uses the established non-root sandbox with a private network and verified cleanup.

Deployment changes only main.py and restarts Relay after tests, two reviews and
rollback/preflight checks. No production customer request, database operation,
provider call or payment is performed by this verification. Existing background
workers resume on restart; their ordinary effects are not claimed to be zero.
Autopilot remains stopped. No whole-project, PostgreSQL rehearsal or real
Telegram/iOS/WebKit/human acceptance is inferred from this bounded change.
