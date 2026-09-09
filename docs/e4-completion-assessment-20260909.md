# E4 completion assessment — 2026-09-09

Reviewer: independent acceptance agent `/root/acceptance`. Scope: read-only
inspection of current action UI, handlers and existing acceptance/rollout
receipts; only this assessment was written. No customer records, external
provider calls, signatures, money actions or production changes.

**Full E4 cannot yet be marked VERIFIED after the TON Connect payload wait
fix alone.** The remaining work includes concrete website and bot action
disclosure gaps already recorded on September 8 and still present in the
unchanged source. This is not a new synthetic prerequisite chain. The current
Mini App patch can finish and deploy independently; these findings do not
block that bounded improvement.

## Canonical criteria and current evidence

Canonical source: `docs/ecosystem-master-roadmap.md:718–727`. The gate requires
the user to understand executor, custody, KYC, fees and irreversibility before
confirmation, and prevents dangerous actions from an accidental tap.

| Criterion | Established evidence | Current assessment |
| --- | --- | --- |
| Portfolio entry with explicit private/KYC lane | `relay/webapp.html` portfolio and exchange route buttons name ObsidianExchange/private and external CEX/KYC; CEX entry explicitly says trading connection unavailable. Existing site/bot ecosystem entry tests and portfolio rollout receipts support navigation. | Established for exposed navigation. Do not turn E4 into a requirement to enable CEX trading; that is E3 scope. |
| Identity/custody/fees/risk before action | Mini App shared review and Buy/Sell/wallet reviews; `e4-buy-custody-rollout.v1.json`, `e4-buy-estimate-rollout.v1.json`, `e4-sell-estimate-rollout.v1.json`, `e4-wallet-review-rollout.v1.json`. | Mini App has implemented disclosure. Website and bot gaps below remain; Mini App receipts do not prove those other paths. |
| Address book and receive/send without false server custody | Recipient-binding/intent/SDK-wait receipts, receive-address rollout and wallet preparation/handoff/reentry/cross-tab receipts. TON transfer review names wallet-held keys and external signature, separate network fee and irreversibility. | Established bounded code/runtime evidence; current payload response/body wait fix is the named remaining Mini App defect. SDK timeout quarantine cannot physically cancel a late modal, but removes its recipient authority. |
| Notifications, evidence and support | Activity refresh/deadline/receipt/session, order-support, payment status/instruction/terminal/expiry deployment receipts. UI explicitly describes wallet operations as remaining in Wallet. | Deployed bounded functionality exists. A new center redesign is not justified by this assessment. |
| Accessibility, localization, responsive UI and money-flow usability | Shared review has dialog semantics and deliberate acknowledgement; repeated isolated browser checks at 320/390, Linux WebKit evidence and owner iPhone Mini App acceptance. | Retain established scope. Website form labels visibly lack `for` or wrapping association; cross-surface action reviews need accessible controls and browser verification when implemented. No additional language target or compulsory device retest is inferred. |

Owner iPhone acceptance is **complete** under
`docs/e4-wallet-device-owner-acceptance.v1.json`: direct observation through
bot `/preview`, Mini App context confirmed, no local report prerequisite.
Older reviews saying this acceptance is missing are superseded. This
assessment does not ask the owner to repeat it.

## Concrete remaining gaps

1. **Website BUY/SELL have no unified pre-submission review.**
   `relay-fastapi/templates/dashboard_exchange.html:8` posts directly to
   `/dashboard/exchange`; its submit button is at line 100. It shows fee and
   destination inputs, but no transaction review naming executor/private lane,
   KYC responsibility, recipient custody and irreversible payout together.
   `dashboard_sell.html:34` similarly submits to `/dashboard/sell` (button at
   line 109), with pricing/payout fields but no complete custody/KYC/risk review.
   `relay-fastapi/main.py:928` and `:1287` are live registered authenticated
   POST handlers; they do not add an intervening review. This is a disclosure
   gap, not a claim that creating an unpaid order instantly moves money.

2. **Website SWAP promises a pre-confirmation amount it does not render.**
   `relay-fastapi/templates/dashboard_swap.html:10` says the user sees the
   final amount before confirmation, but the template contains only pair,
   amount and destination inputs and a direct POST button. There is no quote
   output or review script. `relay-fastapi/main.py:1536` requests a provider
   rate and then calls `create_swap` within the same submitted request;
   it does not return the rate for a separate deliberate confirmation first.
   The provider is `SwapUzProvider`, while the form's main disclosure does
   not name that executor. Its unconditional no-KYC/approximately-1%-with-no-
   separate-fees copy is not supported by a transaction-specific review.
   No external policy conclusion or real provider behavior was tested here.

3. **Telegram money-flow reviews remain incomplete.**
   `bot/main_bot.py:4125` `_finalize_order` creates an order after destination
   collection. The displayed card at `:4231` gives amount, fee and optional
   tag, but omits the full recipient/network and complete executor/custody/KYC
   explanation before payment-method selection. `process_swap_address` at
   `:2062` validates destination then calls `SwapUzProvider.create_swap`
   before a separate transaction review. SELL and optional DCA/gift scope is
   mapped in `docs/e4-money-flow-coverage/acceptance-coverage-matrix.json`;
   that matrix explicitly does not establish complete review on those paths.
   Existing inert handler tests prove validation/ownership boundaries, not
   review integration. These routes need an implementation and acceptance
   decision as a group, not an endless series of synthetic contracts.

The seven inspected site/bot source inputs are byte-identical to the September
8 coverage matrix, so later HTML-only Mini App deployments cannot have closed
these source gaps:

| Input | SHA-256 |
| --- | --- |
| `bot/main_bot.py` | `92a909790005af1b03839ef52f1089d776b37379e3031e7a9f0624b066eaf028` |
| `relay-fastapi/main.py` | `25624ac7bc9174ac9ec35d90402042c62bd344d6c74c1cf730593017a79ae26f` |
| `relay-fastapi/templates/index.html` | `bcbf8332ad7bb0418ae66307f66676fb294364e4ba78833c968f32cf65b70720` |
| `relay-fastapi/templates/rates.html` | `d7b123ba63672b1db42109ee0dfda30cad6a5406e3c38b946498d041d3111a3c` |
| `relay-fastapi/templates/dashboard_exchange.html` | `5c6c450f1568b717c55e306194108545377cd7e4d837d7e8b152ed3b2071628c` |
| `relay-fastapi/templates/dashboard_sell.html` | `5bc8c50a023842439cf471005136fb5388910cf3025fb9b1fa4e6d4199a62343` |
| `relay-fastapi/templates/dashboard_swap.html` | `afd1c004b3f07aa889a239498b01d89640ffbad15a6fc300f889daa036bd7e18` |

## Concrete next work and closure boundary

Finish the current payload wait fix, proportional regressions and reversible
deployment. Next implement **website BUY/SELL action review** as one bounded
code-bearing package: capture and disclose executor/private lane, custody,
KYC responsibility, existing fee/estimate and recipient/payout values; require
an explicit acknowledgement; preserve existing server validation and POST
payload; add associated labels, keyboard/cancel behavior and stale-input
invalidation. Verify both paths in a browser before template-only rollout.

Then address website/bot SWAP and bot BUY/SELL confirmation surfaces using
the same canonical review fields and real handler tests with inert provider/
persistence boundaries. If a flow intentionally hands off to a reviewed
canonical interface, verify the actual navigation and make the former path
nonexecuting rather than claiming it has an independent review. This is a
product decision to implement, not permission to silently remove features.

After these implemented paths have acceptance evidence, consolidate a final
criterion matrix and decide E4 truth against the canonical gate. Do not
promote dormant `025` proposal/rehearsal experiments, require new owner keys,
or relaunch the historical snapshot ceremony merely to close UX work: none
is shown to be a dependency of these existing route improvements.

No E4 completion or stage transition is asserted here. Any later transition
must follow `docs/autonomous-roadmap-transitions.md`; earlier gate status
cannot be inferred from E4 acceptance.
