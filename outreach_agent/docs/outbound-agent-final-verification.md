# OmniDimension Outbound Agent 261506 — Final Read-Only Verification

Verification date: 2026-10-05  
Method: documented authenticated read-only `GET /api/v1/agents/{agent_id}` for agent `261506`.

No API key or authorization header was printed or recorded. The GET response is the evidence for current remote values. Local intent was checked against `app/services/voice_agent_configs.py::outbound_agent_config()`, `app/core/config.py`, and `docs/outbound-agent-integration.md`.

Official references: [Get agent API](https://docs.omnidim.io/docs/api-reference/agents/getAgent), [configure your agent](https://docs.omnidim.io/docs/dashboard-guides/configure-your-agent), and [agent timezone guide](https://docs.omnidim.io/docs/dashboard-guides/update-timezone).

## Summary

The current remote welcome message contains the exact `{{verified_business_name}}` variable. Dynamic welcome and welcome interruption are both enabled. Call type, three requested languages, Cartesia/Riya, Soniox with `en hi mr`, `gpt-4.1-mini`, and ten enabled instruction sections were verified.

The agent GET still returns `timezone = false` as a boolean. The documented API defines the timezone field as an optional IANA timezone string and does not document boolean `false` as a timezone value or as a particular fallback state. Timezone remains unverified.

## Configuration comparison

| Setting | Local/project intent | Actual remote evidence | Status | Notes |
|---|---|---|---|---|
| Agent ID | `261506` | `id = 261506` | **VERIFIED** | Exact match. |
| Agent name | Local template: `LeadSutra Outbound Assistant` | `name = LeadSutra AI – Outbound Sales Agent` | **MISMATCH** | Names differ; ID identifies the configured agent. |
| Call type | `Outgoing` | `bot_call_type = Outgoing` | **VERIFIED** | Exact match. |
| Languages | English (India), Hindi, Marathi | Returned labels: English (India), Hindi, Marathi | **VERIFIED** | All requested languages are present. |
| Voice | Target: Cartesia / Riya | `voice_provider = cartesia`; `voice_name = Riya`; `voice_external_id = faf0731e-dfb9-4cfc-8119-259a79b27e12`; `voice = 2325` | **VERIFIED** | Remote provider/name match requested target. The local template does not set voice. |
| STT | Soniox with English/Hindi/Marathi codes `en`, `hi`, `mr` | `asr_service = Soniox`; `asr_soniox_language = en hi mr`; `asr_smallest_language = en hi mr` | **VERIFIED** | Matches requested provider and language codes. |
| LLM | `gpt-4.1-mini` | `llm_service = gpt-4.1-mini` | **VERIFIED** | Matches requested model. |
| Dynamic welcome | `true` | `is_welcome_message_dynamic = true` | **VERIFIED** | Enabled. |
| Welcome interruption | `true` | `is_welcome_message_interruption = true` | **VERIFIED** | Enabled; callers may interrupt the welcome according to the documented field semantics. |
| General interruption | `true` | `is_interruption_allowed = true` | **VERIFIED** | Enabled; matches local configuration. |
| Agent-specific timezone | `Asia/Kolkata` | `timezone = false` (JSON boolean) | **NOT EXPOSED / UNVERIFIABLE** | The documented field is an optional IANA timezone string. Boolean `false` has no documented meaning here, so it is not interpreted as an IANA zone or proof of fallback. |
| Account timezone | Intended effective timezone: India Standard Time / `Asia/Kolkata` | The documented agent GET returned no account-timezone field. | **NOT EXPOSED / UNVERIFIABLE** | Cannot verify the reported account setting change or the effective timezone through this endpoint. |

## Current welcome message

Remote `welcome_message` returned by GET:

> Hello! I'm an AI assistant calling on behalf of {{verified_business_name}}. Is this a convenient time to speak with you?

**Status: VERIFIED.** The exact variable `{{verified_business_name}}` is present. The message does not hard-code a represented business name. It truthfully identifies the assistant as AI and asks whether it is convenient to speak, consistent with local welcome intent.

This verifies the text stored in the GET response; it does not test whether OmniDimension resolves the variable at runtime. The local dispatch integration declares `verified_business_name` as a dynamic variable and supplies it only after backend identity verification and eligibility checks. No dispatch was performed.

## Remote conversational-flow sections

The GET response returned ten sections, all with `is_enabled = true`. Their titles differ from the four sections in the local template, but their returned instructions align with the local safety intent. Status evaluates the current remote section content against the local requirements for verified identity, lawful preconditions, factual accuracy, polite refusal, opt-out, and conditional follow-up capabilities.

| Remote section | Enabled | Comparison | Status |
|---|---:|---|---|
| Identity & Purpose | Yes | Identifies the assistant as AI, distinguishes LeadSutra AI as calling service from the represented seller, uses only trusted `verified_business_name`, supports the three languages, and ends if identity is missing. | **VERIFIED** |
| Facts | Yes | Uses trusted/approved information only and prohibits invented identity, services, prices, availability, policies, eligibility, and unsupported callback promises. | **VERIFIED** |
| Actions & Limits | Yes | Leaves eligibility to backend checks; allows transfer/callback only when configured and available; respects refusals and opt-outs. | **VERIFIED** |
| Flow: initial introduction & consent | Yes | Requires `contact_basis_status = verified` and a nonblank verified business name before pitching; asks permission and ends on refusal. | **VERIFIED** |
| Flow: qualification & needs assessment | Yes | Continues after agreement, limits questions to relevant needs, avoids assumptions and sensitive information, and uses verified facts. | **VERIFIED** |
| Flow: offer callback or human handoff | Yes | Requires an authorized callback workflow or verified transfer route; prohibits invented availability and follow-up promises. | **VERIFIED** |
| Flow: opt-out or refusal | Yes | Acknowledges and ends immediately; does not claim persistent opt-out recording without confirmation. | **VERIFIED** |
| Scope & Redirects | Yes | Redirects unknown/out-of-scope questions without unconfigured callback or transfer promises. | **VERIFIED** |
| Guardrails | Yes | Prohibits fabricated claims, pressure, unsupported eligibility statements, and unconfigured callback/transfer/booking promises. | **VERIFIED** |
| FAQ | Yes | Uses verified facts, does not claim eligibility without evidence, respects opt-out, and avoids unconfigured follow-up promises. | **VERIFIED** |

The sections are remote configuration text. Their presence does not prove that any particular real call context contains the required values or that an opt-out persistence workflow is available.

## Mismatches and limitations

- **Name mismatch:** remote display name differs from the local template name. This does not change the verified agent ID.
- **Timezone:** unresolved. Agent `timezone` remains boolean false; the documented API does not define its meaning. The GET endpoint does not expose account timezone.
- **Runtime variable resolution:** the exact variable is present in the welcome text, but no call was made to test its substitution. The local dispatch flow supplies the verified value only on an eligible enabled path.
- **Call behavior:** language switching, speech quality, caller interruption timing, and generated welcome behavior were not tested in a conversation.
- Local configuration is not automatically synchronized to the provider. The GET confirms current remote text/instructions only.

## Dispatch safety and tests

- `.env` does not set `OUTBOUND_CALLS_ENABLED`; `app/core/config.py` defaults it to `False`. It was not changed.
- No agent create/update/delete/deploy operation was used.
- No dispatch, test call, or other call operation was used.
- Relevant tests were not run: this was a read-only verification with no code changes, and previous environment checks found no available Python interpreter.
- No source files, database records, environment variables, scraper files, or `leads.json` were modified.
