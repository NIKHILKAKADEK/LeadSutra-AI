# OmniDimension Outbound Agent Verification

Audit date: 2026-10-05  
Agent ID: `261506`  
Scope: read-only verification. No provider settings were changed and no calls were placed.

## Method

Local configuration was inspected in `app/services/voice_agent_configs.py`, `app/services/omnidimension.py`, `app/services/call_dispatch.py`, `app/core/config.py`, and `docs/outbound-agent-integration.md`. The installed SDK exposes `Agent.get(agent_id)` as a GET operation, and OmniDimension documents the authenticated read operation at [Get agent](https://docs.omnidim.io/docs/api-reference/agents/getAgent). The documented GET endpoint was used to retrieve agent `261506`. Only selected configuration values and structure were inspected; the API key and authorization header were not printed or included in this document.

The remote response is evidence of the current provider record returned by that endpoint. It does not verify any separate dashboard-only behavior or how a future call will sound in practice.

## Configuration comparison

| Setting | Local expected value | Actual remote value | Status | Evidence or limitation |
|---|---|---|---|---|
| Agent ID | `261506` from backend settings default | `261506` | **Match** | GET response `id`; backend selects the ID server-side. |
| Agent name | Local outbound template: `LeadSutra Outbound Assistant` | `LeadSutra AI – Outbound Sales Agent` | **Different** | GET response `name`. The local template name differs from the existing remote agent name. |
| Call type | `Outgoing` | `Outgoing` | **Match** | GET response `bot_call_type`. |
| Languages | English (India), Hindi, Marathi | English (India), Hindi, Marathi | **Match** | GET response `languages` labels; remote Soniox language codes also report `en hi mr`. |
| Voice provider | Not represented by the local outbound template | `cartesia` | **Remote verified; local comparison unavailable** | GET response `voice_provider`. |
| Voice identity | Not represented by the local outbound template | `Riya` (`voice_name`) | **Remote verified; local comparison unavailable** | GET response `voice_name`; `voice_external_id` was also present. The external ID is omitted here because the display name is sufficient for this comparison. |
| Speech recognition provider | Local template declares `transcriber.provider = Soniox` | `Soniox` | **Match** | GET response `asr_service`. |
| Speech recognition languages | Local template does not specify provider language codes | `en hi mr` | **Remote verified; local comparison unavailable** | GET response `asr_soniox_language`. |
| LLM model | Not represented by the local outbound template | `gpt-4.1-mini` | **Remote verified; local comparison unavailable** | GET response `llm_service`. |
| Dynamic welcome enabled | `true` | `true` | **Match** | GET response `is_welcome_message_dynamic`. |
| Welcome interruption | `true` | `false` | **Mismatch** | GET response `is_welcome_message_interruption`; local `_OUTBOUND` expects true. |
| General interruption | `true` | `true` | **Match** | GET response `is_interruption_allowed`. |
| Timezone | `Asia/Kolkata` | `false` | **Mismatch** | GET response `timezone` was the boolean `false`, not a timezone string. This does not establish an effective timezone. |
| Welcome message content | Local template asks the agent to identify itself as AI, identify the verified represented business, check availability, and follow/switch among the three configured languages | A non-empty remote dynamic welcome message was returned; it differs from the local template | **Mismatch / content differs** | Remote `welcome_message` length was 143 characters; local template text is different. The provider message is not reproduced in this report. |
| Conversation instructions | Four local sections in `_OUTBOUND` | Ten enabled remote `context_breakdown` sections, including identity/purpose, facts, actions/limits, qualification, callback/handoff, opt-out/refusal, guardrails, and FAQ | **Not an exact match; semantic equivalence unverified** | Remote GET returned section titles, enabled flags, and bodies. The remote structure differs from the local template; this audit does not certify every instruction or FAQ fact as safe and aligned. |

## Verified matching settings

- Agent ID and outgoing call type match the backend’s intended configuration.
- The provider record lists all three configured languages: English (India), Hindi, and Marathi.
- Dynamic welcome is enabled, and general interruption is enabled.
- The remote voice is Cartesia with the display name Riya.
- The remote speech recognition provider is Soniox, with `en hi mr` configured.
- The remote LLM model is `gpt-4.1-mini`.

The last three settings are verified remote values, but are not represented in the local outbound template, so there is no local expected value against which to declare a local/remote match.

## Mismatches and unavailable verification

- **Timezone:** provider returned `false`; local configuration expects `Asia/Kolkata`.
- **Welcome interruption:** provider returned false; local configuration expects true.
- **Agent name:** local and remote names differ. This may be a naming-only discrepancy, but should be reconciled for operational clarity.
- **Welcome text:** remote text exists and differs from the local welcome template. Dynamic welcome is on, but the exact desired wording is not synchronized from the local template by dispatch.
- **Instructions:** the provider has ten enabled sections, while the local template has four. The section structure and titles were observed, but semantic parity, approved factual content, and FAQ accuracy are not certified.
- **No local model or voice expectation exists:** local `voice_agent_configs.py` specifies neither Cartesia/Riya nor `gpt-4.1-mini`. Those values are verified remotely only.
- No call was made, so audio quality, language switching in a live conversation, interruption behavior in practice, and generated welcome-message behavior were not tested.

## Recommended dashboard corrections

Before any controlled voice test, an authorized agent administrator should:

1. Set the agent timezone to `Asia/Kolkata` if that is the intended operating timezone.
2. Enable welcome-message interruption if the local setting remains authoritative.
3. Align the remote welcome wording with the approved local outbound introduction, including truthful AI identification, explicit represented-business identity only when verified, and a brief availability question.
4. Review all ten remote instruction sections and FAQs against approved business facts, consent/refusal and opt-out behavior, and human-handoff configuration. Do not copy unverified offering, pricing, callback, or identity claims into the agent.
5. Decide whether the local template name or the existing provider name is the operational name of record.

These are recommendations only. No dashboard changes were made. Provider editing should use its documented authenticated update workflow under an authorized change process; this audit did not use or test it.

## Readiness

**Not ready for a controlled internal voice test based on this audit.** The timezone value and welcome-interruption setting mismatch local expectations, and the remote welcome/instruction content has not been approved for semantic parity. A controlled test should wait until an authorized administrator has reconciled and reviewed these settings. This conclusion does not authorize an outbound production call.

## Safety and test results

- `OUTBOUND_CALLS_ENABLED` remains false: the application default and `.env.example` specify false; no change was made.
- No provider write, agent create/delete/update, or call-dispatch request was issued.
- No API key or authorization header is included in logs or this report.
- Attempted relevant tests with `python -m pytest ...` could not start because `python` is not available in the shell.
- Attempted the repository virtual environment runner; it could not start because its configured Python 3.12 executable is missing (`C:\Users\kakde\AppData\Local\Programs\Python\Python312\python.exe`). Therefore no tests ran in this environment.
