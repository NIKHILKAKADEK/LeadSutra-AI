import axios from 'axios'

export type ApiFailure = { kind: 'network-error' | 'server-error'; message: string }
export function classifyApiError(error: unknown): ApiFailure {
  if (axios.isAxiosError(error)) {
    if (error.response) {
      if (error.response.status === 401 || error.response.status === 403) {
        return { kind: 'server-error', message: 'Your secure workspace session does not have access to this data.' }
      }
      if (error.response.status === 503) {
        const response = error.response.data
        const detail = typeof response === 'object' && response !== null && 'detail' in response
          ? response.detail
          : undefined
        const code = typeof detail === 'object' && detail !== null && 'code' in detail
          ? detail.code
          : undefined
        if (code === 'email_configuration_unavailable') {
          return { kind: 'server-error', message: 'Email preview needs a valid SMTP_FROM_ADDRESS in Backend/.env.' }
        }
        return { kind: 'server-error', message: 'The lead source is unavailable right now.' }
      }
      if (error.response.status === 422) {
        const response = error.response.data
        const detail = typeof response === 'object' && response !== null && 'detail' in response
          ? response.detail
          : undefined
        const code = typeof detail === 'object' && detail !== null && 'code' in detail
          ? detail.code
          : undefined
        const emailErrors: Record<string, string> = {
          proposal_invalid: 'The generated proposal could not be read. Generate the proposal again, then retry the email preview.',
          recipient_unavailable: 'No recipient email is available for this lead. Add a verified business email before creating an email preview.',
          email_business_name_invalid: 'This lead is missing a valid business name. Update the lead record before creating an email preview.',
          email_draft_invalid: 'The edited subject or message is not valid. Check its length and try again.',
        }
        if (typeof code === 'string' && emailErrors[code]) {
          return { kind: 'server-error', message: emailErrors[code] }
        }
        return { kind: 'server-error', message: 'The request data was rejected by the backend. Review the selected lead and try again.' }
      }
      return { kind: 'server-error', message: `The server could not complete this request (${error.response.status}).` }
    }
    return { kind: 'network-error', message: 'Could not reach the secure API connection. Check the connection and try again.' }
  }
  return { kind: 'server-error', message: 'Something went wrong while loading this lead data.' }
}
