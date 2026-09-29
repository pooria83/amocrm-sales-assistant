import type { AssistRequest, AssistResponse, RetrieveRequest, RetrieveResponse } from './types'

export class ApiError extends Error {
  status: number
  code: string

  constructor(status: number, code: string) {
    super(code)
    this.status = status
    this.code = code
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'network_error')
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as { detail?: string }
    throw new ApiError(response.status, payload.detail ?? `http_${response.status}`)
  }
  return (await response.json()) as T
}

export function retrieve(request: RetrieveRequest): Promise<RetrieveResponse> {
  return post<RetrieveResponse>('/api/retrieve', request)
}

export function assist(request: AssistRequest): Promise<AssistResponse> {
  return post<AssistResponse>('/api/assist', request)
}
