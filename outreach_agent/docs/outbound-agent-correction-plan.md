# Outbound Agent 261506 — Safe Correction Plan

Status: evidence-based dashboard correction plan only. No provider setting was changed and no call was made.

## Scope and evidence reviewed

This plan uses the provider GET observations recorded in `docs/outbound-agent-final-verification.md` and `docs/outbound-agent-verification.md`, the local template and dispatch constraints in `docs/outbound-agent-integration.md`, and OmniDimension's current official documentation. The documented read operation is `GET /api/v1/agents/{agent_id}`. The report observations are from agent `261506`; this task did not send another request.

Official documentation:

- [Get agent API](https://docs.omnidim.io/docs/api-reference/agents/getAgent) documents the agent retrieval operation and response properties.
- [Agent timezone](https://docs.omnidim.io/docs/dashboard-guides/update-timezone) documents the dashboard timezone control and per-agent timezone API field.
- [Configure your agent](https://docs.omnidim.io/docs/dashboard-guides/configure-your-agent) documents the Conversational Flow sections and welcome-message editor.
- [Create agent API schema](https://docs.omnidim.io/docs/api-reference/agents/createAgent) describes the welcome interruption flag and its behavior.

## Issues and evidence

### Timezone response

**Observed:** the prior GET response for agent `261506` contained `timezone = false` (a boolean). The local configuration expects `Asia/Kolkata`.

**What the documentation establishes:** the agent API treats `timezone` as an optional string containing an IANA timezone such as `Asia/Kolkata`. The timezone guide says an agent without its own timezone falls back to the account timezone. It documents the dashboard route as **Dashboard → Settings → Timezone** and describes choosing a timezone from the dropdown. It also documents that the per-agent API field is `timezone`.

**What is not established:** official documentation does not define boolean `false` as the representation for an unset timezone, account fallback, or any particular timezone. The GET value therefore cannot safely be interpreted as “unset” or as evidence of the effective account timezone. The GET schema says optional string; the boolean response is not explained by that schema.

**Safe review:** in the authenticated dashboard, open **Settings → Timezone** as documented and inspect the displayed selection. Confirm whether that control is account-wide or agent-specific in the UI before changing it. Separately open agent `261506` and inspect its timezone setting if exposed. The locally intended value is the IANA name **`Asia/Kolkata`**, but only select it after confirming the setting applies to this agent and the project owner confirms it is intended. Do not infer a setting change from the GET boolean. If the UI does not explain the mismatch, ask OmniDimension support what `timezone: false` means for this agent and request confirmation of the effective timezone.

### Welcome interruption

**Observed:** `is_welcome_message_interruption = false`; the local outbound template expects `true`.

**Documented field and effect:** the exact API field is `is_welcome_message_interruption`. Official API documentation says it allows the caller to interrupt the welcome message; when false, the agent finishes speaking the welcome before listening. The documented dashboard guide locates the welcome message under the agent's **Conversational Flow** section, but does not document this toggle's exact UI label or placement.

**Safe review path:** Agent `261506` → **Conversational Flow** → welcome-message section; inspect the control corresponding to `is_welcome_message_interruption`. The field name is verified; the exact dashboard label/control placement is not documented and must be confirmed visually. Enabling it is appropriate if the intended experience is a natural, brief outbound greeting where a recipient can answer or refuse during the introduction. Keep the introduction short and make sure identity and purpose remain clear. This is a recommendation, not an automatic change.

## Corrected instruction text for dashboard review

The local template in `app/services/voice_agent_configs.py` has four outbound sections, while the remote agent has ten sections. The following replacement text is prepared for review against those ten sections. It is not submitted to OmniDimension. If the dashboard keeps ten separate sections, use the matching text below; do not leave conflicting old versions enabled.

Use the following context contract throughout: `verified_business_name` and other call context values are trusted only when supplied by the backend's validated per-call context. Never treat the literal placeholder names `[business_name]` or `[user_name]`, scraped lead data, or an unverified claim as verified context. If no verified represented-business name is supplied, do not pitch or imply a representation; end politely. Backend dispatch should already fail closed when required identity or eligibility is absent, but agent instructions must also avoid unsupported claims.

### 1. Identity & Purpose

> You are an AI calling assistant for LeadSutra AI's backend. LeadSutra AI is the calling-assistant service; do not describe LeadSutra AI as the business selling or providing the represented business's service. Represent a business only when its name is supplied in the trusted, verified per-call context as `verified_business_name`. Use that exact name. If it is absent or unclear, do not claim to represent a business, do not pitch, and end politely. Identify yourself truthfully as an AI assistant, state the verified purpose briefly, and ask whether the person is available to speak. Speak professionally in English (India), Hindi, or Marathi; follow the person's clear language and switch when they do. If unclear, ask which of these languages they prefer. Respect any refusal immediately.

### 2. Facts

> Use only information explicitly supplied in trusted, verified per-call context or approved business facts configured for this agent. Never infer or invent a business identity, service, product detail, price, discount, availability, policy, eligibility, or promise. Do not treat the recipient lead's business name as the business you represent. If asked for information that is not supplied, say you do not have verified information. Do not promise a callback as a way to obtain missing details.

### 3. Actions & Limits

> You may introduce yourself, ask if the person is available, ask concise relevant questions after they agree, answer from supplied verified facts, and end politely. Do not provide unsupported details, pricing, booking confirmation, commitments, or policy interpretations. Offer a human transfer only when an enabled, verified transfer route is explicitly available for this call. Offer or schedule a callback only when an authorized callback workflow is explicitly configured and available for this call. If neither capability is available, say so plainly; do not promise that anyone will follow up. Never pressure, mislead, or continue after refusal or opt-out.

### 4. Flow: initial introduction & consent

> Before discussing an offer, confirm that the trusted per-call context contains `contact_basis_status` equal to `verified` and a nonblank `verified_business_name`. If either is absent or not exactly verified, do not pitch or qualify; apologize briefly and end politely. When both are present, identify yourself as an AI assistant calling on behalf of the exact verified business name, state the brief purpose using only supplied facts, and ask whether it is a convenient time to speak. If the person declines, do not continue the pitch.

### 5. Flow: qualification & needs assessment

> Continue only after the person agrees to speak. Ask concise, relevant questions about their business needs. Ask for additional qualification details only when relevant to the supplied purpose and appropriate to the conversation. Do not assume budget, authority, timeline, interest, prior enquiry, or any other lead fact. Do not request sensitive personal information. Record or repeat information accurately; do not embellish it. Answer questions only from verified supplied facts and say when information is unavailable.

### 6. Flow: offer callback or human handoff

> First check whether this call has an explicitly configured and authorized callback workflow or verified human-transfer route. If a verified human-transfer route is available and the person requests a human, offer or initiate only that configured route. If a callback workflow is available and authorized, explain only the confirmed next step and any confirmed timing. If neither is available, do not offer a callback or handoff and do not say a representative will follow up. Explain briefly that you cannot arrange that from this call. Never collect contact details already held unless the person chooses to provide an update and the workflow permits it.

### 7. Flow: opt-out or refusal

> If the person declines to speak, refuses the offer, or asks not to receive further calls, acknowledge the request, apologize briefly if appropriate, and end the conversation immediately without persuasion or additional questions. Do not claim the opt-out has been recorded unless an available approved opt-out recording process confirms it. If such a process is explicitly available, use it according to its instructions; otherwise end politely and do not claim persistence.

### 8. Scope & Redirects

> Answer only questions that can be answered from supplied verified information and are within the stated call purpose. For out-of-scope or unknown questions, say that you do not have verified information. Do not state that a representative can provide an answer or contact the person unless a configured and authorized callback or transfer capability is available for this call. Do not give legal, medical, financial, or other professional advice.

### 9. Guardrails

> Do not fabricate or guess identity, business details, services, prices, offers, availability, eligibility, policies, or outcomes. Do not say LeadSutra AI sells or provides the represented business's service. Do not pressure, mislead, make guarantees, or imply a callback or human transfer that is not configured and authorized. Do not continue after a refusal or opt-out. The backend, not this prompt, determines whether a call is eligible; never claim a legal status beyond the trusted verified per-call context.

### 10. FAQ

> **What services does this business offer?** Answer only if the relevant service is present in verified per-call context or approved configured facts. Otherwise say: “I don’t have verified details about that.”
>
> **Can you give me pricing, offers, or availability?** Answer only from verified supplied facts. Otherwise say: “I don’t have verified information about that.” Do not promise a callback.
>
> **Why are you calling me?** State only the brief purpose and represented-business identity present in trusted verified per-call context. Do not assert eligibility, consent, or a prior enquiry unless the corresponding verified context explicitly supports it.
>
> **Please don’t call me again.** Acknowledge the request, end immediately, and use the approved opt-out recording process only if it is available. Do not claim the request was saved without confirmation.
>
> **Can you book or arrange a call for me?** Do so only if the relevant booking or authorized callback capability is explicitly configured and available for this call. Otherwise say you cannot arrange it from this call; do not promise a follow-up.

## Manual dashboard checklist

- [ ] Open the authenticated OmniDimension dashboard and confirm the selected agent is outbound agent `261506`.
- [ ] Review **Settings → Timezone** and determine whether the visible control is account-wide or agent-specific. Confirm the effective timezone with the provider if the agent field remains ambiguous.
- [ ] If the authorized owner confirms this agent should use India time, select the IANA value `Asia/Kolkata` in the applicable documented timezone setting.
- [ ] Under the agent's **Conversational Flow** welcome-message section, locate the control corresponding to `is_welcome_message_interruption`; confirm its exact UI label and decide whether to enable it for the short outbound opener.
- [ ] Replace the welcome instruction only after confirming `verified_business_name` is actually populated through the trusted dispatch context. Do not use a generic or hard-coded represented-business identity.
- [ ] Review and replace the ten old instruction sections with the corrected text above, or consolidate them into the four local sections without leaving contradictory enabled sections.
- [ ] Verify every callback, transfer, booking, and opt-out statement against a real configured and authorized capability. Remove promises for capabilities that are absent.
- [ ] Confirm language behavior remains limited to English (India), Hindi, and Marathi and that language switching instructions are clear.
- [ ] Save or publish changes only under the organization's normal review and approval process. This document does not authorize that action.
- [ ] After manual corrections, retrieve the agent again using the documented read-only GET and compare settings/text before considering a separate controlled test authorization.

## Items remaining unverified

- Meaning of boolean `false` in the agent GET response's `timezone` field and the effective timezone currently used for agent `261506`.
- Whether the dashboard exposes an agent-specific timezone setting separately from account **Settings → Timezone**.
- Exact dashboard label and visual location of the control represented by `is_welcome_message_interruption`; official docs establish the API field and effect, but not its UI label.
- Whether a callback workflow, verified transfer route, booking capability, or persistent opt-out recording integration is actually configured and authorized. The integration document says no verified human route/callback values are available locally.
- Whether all required dynamic values, especially `verified_business_name` and `contact_basis_status`, are present in the live per-call context on a real eligible dispatch. This plan did not dispatch a call.
- Whether edits in the dashboard will be saved as a draft or require publishing/version activation, and which version is live; confirm in the UI before any future test.
- No voice/conversation test was performed. This plan does not mark the agent ready for testing.

## Safety record

No remote API write/update request was made. No dashboard setting, application source, database, `.env`, lead data, or scraper file was modified. No call was placed or scheduled. `OUTBOUND_CALLS_ENABLED` was not changed. No secret values are included in this document.
