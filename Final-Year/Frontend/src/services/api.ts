import axios from 'axios'

// Local development uses the Vite proxy; deployed builds must provide a
// trusted same-origin API/BFF. Never put reviewer/admin tokens in VITE_* vars.
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.trim() || (import.meta.env.DEV ? '/' : '')
export const isApiConfigured = Boolean(API_BASE_URL)
export const DISCOVERY_API_BASE_URL = API_BASE_URL
export const isDiscoveryApiConfigured = isApiConfigured

function createApiClient(baseURL: string) {
  return axios.create({
  ...(baseURL ? { baseURL } : {}),
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
  })
}

export const api = createApiClient(API_BASE_URL)
export const discoveryApi = createApiClient(DISCOVERY_API_BASE_URL)
