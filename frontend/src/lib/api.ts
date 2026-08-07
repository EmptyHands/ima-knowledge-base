import { clearToken, getToken } from "./auth"

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json")
  }
  const token = getToken()
  if (token) {
    headers.set("Authorization", `Bearer ${token}`)
  }

  const resp = await fetch(path, { ...options, headers })

  if (resp.status === 401) {
    clearToken()
    if (!window.location.pathname.startsWith("/login")) {
      window.location.href = "/login"
    }
    throw new ApiError(401, "登录已过期，请重新登录")
  }

  const text = await resp.text()
  let body: any = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = text
    }
  }

  if (!resp.ok) {
    const detail =
      typeof body === "object" && body && typeof body.detail === "string"
        ? body.detail
        : `请求失败 (${resp.status})`
    throw new ApiError(resp.status, detail)
  }
  return body as T
}

export const api = {
  get<T>(path: string): Promise<T> {
    return request<T>(path)
  },
  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  },
  put<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: "PUT",
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  },
  del<T>(path: string): Promise<T> {
    return request<T>(path, { method: "DELETE" })
  },
  upload<T>(path: string, formData: FormData): Promise<T> {
    return request<T>(path, { method: "POST", body: formData })
  },
}
