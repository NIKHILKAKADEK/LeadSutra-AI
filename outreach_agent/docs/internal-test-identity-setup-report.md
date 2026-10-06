# Internal Test Identity Setup Report

Audit date: 2026-10-05  
Scope: local configuration presence check only. No values from `.env` were displayed, no secrets were inspected or exposed, no configuration was changed, and no provider request or call was made.

## Required variable names

Confirmed in `app/core/config.py`, `.env.example`, and `docs/test-business-configuration-guide.md`:

| Purpose | Exact environment variable | Source default |
|---|---|---|
| Represented business name | `OUTBOUND_REPRESENTED_BUSINESS_NAME` | Unset / `None` |
| Identity verification attestation | `OUTBOUND_REPRESENTED_BUSINESS_IDENTITY_VERIFIED` | `false` |
| Outbound agent ID | `OMNIDIM_OUTBOUND_AGENT_ID` | `261506` |
| Outbound dispatch enablement | `OUTBOUND_CALLS_ENABLED` | `false` |

## Local validation results

The `.env` file exists. The check examined only whether the four names above were present and nonempty; it did not print or return any `.env` values. None of the four names is present in `.env` or in the current process environment.

Therefore, based on the source defaults in `app/core/config.py::Settings`, the effective fallback values are:

- Agent ID: `261506`.
- Dispatch enablement: `false`.
- Represented business name: unset.
- Identity verification attestation: `false`.

Dispatch remains disabled. The identity settings are not configured. No runtime settings object was printed or queried, and the API key and token settings were not read by this check.

## Values needed for an authorized controlled internal test

Use the exact organization name that the organization has authorized LeadSutra to represent for this internal test. Verify the identity and authorization with the organization's responsible owner/operator first; do not use a made-up company or assume a fictional name grants authority.

The setting values should be managed as follows:

- `OUTBOUND_REPRESENTED_BUSINESS_NAME`: the authorized organization's verified business name.
- `OUTBOUND_REPRESENTED_BUSINESS_IDENTITY_VERIFIED`: keep `false` unless an authorized operator explicitly approves that specific identity for this internal test and verifies it. No such identity or approval was supplied for this task, so this report does not recommend setting it to `true` yet.
- `OMNIDIM_OUTBOUND_AGENT_ID`: the existing server-selected agent ID, `261506`; no override is needed for the configured agent.
- `OUTBOUND_CALLS_ENABLED`: keep `false` for this configuration step. Do not enable it as part of identity setup.

A valid name and verification attestation do not satisfy consent, suppression, telecom preference/route, calling-hours, or attempt-limit checks. They also do not prove provider-side dynamic-variable substitution. All existing eligibility requirements and a separately authorized test decision remain necessary before any real dispatch.

## Safe manual setup instructions

No change was made here. When an organization-approved name and explicit test authorization are available, an operator may configure the exact settings locally using the existing `.env` mechanism, or in the PowerShell process used to start the backend. Do not copy or display secret entries while editing `.env`.

Example PowerShell setup, with the business name deliberately left as a prompt for the authorized operator to replace and verification left false until separately approved:

```powershell
$env:OMNIDIM_OUTBOUND_AGENT_ID = '261506'
$env:OUTBOUND_CALLS_ENABLED = 'false'
$env:OUTBOUND_REPRESENTED_BUSINESS_NAME = '<authorized organization verified name>'
$env:OUTBOUND_REPRESENTED_BUSINESS_IDENTITY_VERIFIED = 'false'
```

Do not leave the angle-bracket placeholder in place. Do not set the attestation to true based solely on the example or because the application accepts it. A process-scoped setting takes precedence over `.env`; restart the app after configuration changes because `get_settings()` is cached and the app reads settings during import.

## Safe PowerShell checks

These commands report only file existence and whether the four named settings are present/nonempty. They do not display setting values or inspect other variables such as API keys or tokens.

```powershell
$keys = @(
  'OUTBOUND_REPRESENTED_BUSINESS_NAME',
  'OUTBOUND_REPRESENTED_BUSINESS_IDENTITY_VERIFIED',
  'OMNIDIM_OUTBOUND_AGENT_ID',
  'OUTBOUND_CALLS_ENABLED'
)
$envPath = Join-Path (Get-Location) '.env'
"DOTENV_FILE_EXISTS=$([bool](Test-Path -LiteralPath $envPath))"
if (Test-Path -LiteralPath $envPath) {
  $fileMap = @{}
  foreach ($line in [System.IO.File]::ReadLines($envPath)) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
      $fileMap[$matches[1].ToUpperInvariant()] = $matches[2].Trim()
    }
  }
  foreach ($key in $keys) {
    if ($fileMap.ContainsKey($key)) {
      $state = if ($fileMap[$key].Length -gt 0) { 'PRESENT_NONEMPTY' } else { 'PRESENT_EMPTY' }
      "$key .env=$state"
    } else { "$key .env=MISSING" }
  }
}
foreach ($key in $keys) {
  $item = Get-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue
  if ($null -eq $item) { "$key process=MISSING" }
  else {
    $state = if ([string]::IsNullOrWhiteSpace($item.Value)) { 'PRESENT_EMPTY' } else { 'PRESENT_NONEMPTY' }
    "$key process=$state"
  }
}
```

To validate effective dispatch status through application settings without displaying a value, run this from the backend virtual environment:

```powershell
python -c "from app.core.config import get_settings; s=get_settings(); print('OUTBOUND_CALLS_ENABLED=' + ('false' if not s.outbound_calls_enabled else 'true'))"
```

Expected result is `OUTBOUND_CALLS_ENABLED=false`. Stop if it reports `true`; do not make dispatch requests. This check prints only the boolean dispatch state, not credentials or identity values.

## Remaining blockers

1. No represented-business name is configured, and no organization-specific authorization for this test was provided. The identity flag must remain false until both authorization and verification are established.
2. No outbound environment overrides are set; the `.env` file currently does not contain these settings. The source defaults keep calls disabled and select Agent `261506`.
3. This task did not validate consent or telecom evidence, suppression state, calling hours, attempt budget, remote agent state, or runtime placeholder substitution. Those are separate prerequisites.
4. No files or environment settings were changed. Dispatch remains disabled; no provider requests or calls were made.
