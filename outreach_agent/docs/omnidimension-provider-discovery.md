# OmniDimension provider discovery

Account-scoped provider catalog inspected on 2026-10-03 through the documented
`GET /api/v1/providers/all` endpoint. The API key was read from the existing
backend configuration and was not printed or saved in this report.

The installed SDK is `omnidimension 0.4.2`. Its `Agent.create` method accepts
`name`, `context_breakdown`, `call_type`, `timezone`, `transcriber`, `voice`,
`languages`, `welcome_message`, and `is_welcome_message_dynamic`. It accepts
additional API fields through `**kwargs`. No agent was created.

## Account catalog

The provider catalog returned these STT entries (catalog ID and exact name):

| ID | Provider |
| ---: | --- |
| 5 | `Azure` |
| 2 | `deepgram_stream` |
| 4 | `Sarvam` |
| 58 | `Smallest-STT` |
| 49 | `Soniox` |
| 3 | `Cartesia` |

It returned these TTS entries:

| ID | Provider |
| ---: | --- |
| 29 | `deepgram` |
| 35 | `hume` |
| 59 | `smallest-tts` |
| 36 | `inworld` |
| 37 | `sarvam` |
| 33 | `rime` |
| 34 | `playht` |
| 38 | `openAI` |
| 30 | `google` |
| 31 | `eleven_labs` |
| 32 | `cartesia` |

The account voice catalog returned 5,598 entries. Its voice records included
IDs, names, display names, service names, and sample URLs, but no supported
language list. The documented voice detail response also has no language
compatibility field. Voice names that mention Hindi or English do not prove
support for all three required languages, so this integration deliberately
does not select a voice ID. OmniDimension's voice library marks multilingual
voices, but the catalog response available to this integration did not expose
that marker.

## Language and STT compatibility

Use the exact language picker labels `English (India)`, `Hindi`, and `Marathi`.
The current docs list those labels in the agent create schema and document all
three language families in platform language support.

The multilingual language guide documents:

- `Soniox`: recognizes English, Hindi, and Marathi in multilingual switching
  mode. The account catalog identifier is `Soniox` (catalog ID 49).
- `Smallest-STT`: supports English, Hindi, and Marathi. Its documented
  language grouping supports this trio together. The account catalog
  identifier is `Smallest-STT` (catalog ID 58).
- `Sarvam`: documented as automatic language detection for Indian languages;
  supported language switching does not need explicit per-language config.
  The account catalog identifier is `Sarvam` (catalog ID 4).

The reusable configs choose `Soniox`, whose provider and multilingual
switching support are both documented. No TTS voice was selected pending an
explicit language-compatibility listing or provider-side confirmation.

## References

- [Create agent API](https://docs.omnidim.io/docs/api-reference/agents/createAgent)
- [Voices and languages](https://docs.omnidim.io/docs/dashboard-guides/voices-and-languages)
- [Per-call languages and STT behavior](https://docs.omnidim.io/docs/per-call-languages)
- [List all providers](https://docs.omnidim.io/docs/api-reference/providers/listAllProviders)
- [List voices](https://docs.omnidim.io/docs/api-reference/providers/listVoices)
- [Get voice details](https://docs.omnidim.io/docs/api-reference/providers/getVoice)
