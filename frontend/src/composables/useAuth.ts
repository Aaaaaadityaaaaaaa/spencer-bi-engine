// Auth singleton (TASK-027): module-scoped reactive state mirroring useSession's
// idiom, so every component shares ONE token/user without Pinia. It owns the JWT and
// keeps three layers in sync on every user change:
//   1. the Axios layer (setAuthToken) so outgoing requests carry the bearer token,
//   2. the per-user convenience stores (query history + dashboards) so a shared
//      browser never shows one user another's data,
//   3. the session singleton (reset on logout so the next user starts clean).
//
// Deliberately does NOT import the router: router/index.ts imports THIS module for its
// navigation guard, so importing the router back would form a cycle. Navigation lives
// in the components that have a router context (AuthView after login, App.vue's logout
// button + its wired onUnauthorized handler).
import { reactive, computed, toRefs } from 'vue'
import type { AuthUser } from '../types'
import {
  registerUser,
  loginUser,
  fetchMe as apiFetchMe,
  setAuthToken,
  apiErrorMessage,
} from '../services/api'
import { loadForUser as loadQueryHistoryForUser } from './useQueryHistory'
import { loadForUser as loadDashboardsForUser } from './useDashboards'
import { loadForUser as loadActiveDashboardForUser } from './useActiveDashboard'
import { useSession } from './useSession'

const PERSIST_KEY = 'spencer.auth.v1'

interface AuthState {
  token: string | null
  user: AuthUser | null
  // True while a submit (login/register) is in flight, for button disabling.
  busy: boolean
  error: string | null
}

interface PersistedAuth {
  token: string
  user: AuthUser | null
}

const state = reactive<AuthState>({
  token: null,
  user: null,
  busy: false,
  error: null,
})

function persist(): void {
  try {
    if (!state.token) {
      localStorage.removeItem(PERSIST_KEY)
      return
    }
    const payload: PersistedAuth = { token: state.token, user: state.user }
    localStorage.setItem(PERSIST_KEY, JSON.stringify(payload))
  } catch {
    // localStorage may be unavailable (private mode / quota). Persistence is a
    // convenience; a failure must never break auth for the current tab.
  }
}

function readPersisted(): PersistedAuth | null {
  try {
    const raw = localStorage.getItem(PERSIST_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<PersistedAuth>
    if (!parsed || typeof parsed.token !== 'string') return null
    return { token: parsed.token, user: (parsed.user as AuthUser) ?? null }
  } catch {
    return null
  }
}

// Point the per-user client stores at this user's namespace (or clear them when null).
// Keyed by a stable string id so the same user always lands on the same keys.
function applyUserScope(userId: string | null): void {
  loadQueryHistoryForUser(userId)
  loadDashboardsForUser(userId)
  loadActiveDashboardForUser(userId)
}

// Adopt a fresh (token, user): update state, the Axios token, persistence, and the
// per-user store scope. Shared by login/register/restore.
function adopt(token: string, user: AuthUser | null): void {
  state.token = token
  state.user = user
  state.error = null
  setAuthToken(token)
  applyUserScope(user ? String(user.id) : null)
  persist()
}

async function login(email: string, password: string): Promise<boolean> {
  state.busy = true
  state.error = null
  try {
    const res = await loginUser(email, password)
    adopt(res.access_token, res.user)
    return true
  } catch (e) {
    state.error = apiErrorMessage(e)
    return false
  } finally {
    state.busy = false
  }
}

async function register(email: string, password: string): Promise<boolean> {
  state.busy = true
  state.error = null
  try {
    const res = await registerUser(email, password)
    adopt(res.access_token, res.user)
    return true
  } catch (e) {
    state.error = apiErrorMessage(e)
    return false
  } finally {
    state.busy = false
  }
}

// Clear all auth + per-user state. Navigation to /login is the caller's job (the
// component/handler that has a router context). Safe to call repeatedly.
function logout(): void {
  state.token = null
  state.user = null
  state.error = null
  setAuthToken(null)
  applyUserScope(null)
  // Drop the loaded dataset pointer so the next user never inherits it (the server
  // guard would 404 a foreign session anyway; this is belt-and-braces + clean UX).
  useSession().resetSession()
  persist()
}

// Confirm the persisted token is still valid and refresh the user record. Called once
// on boot from loadFromStorage. A 401 means the token is stale/expired -> log out; a
// transient/network error keeps the token so a later call can still succeed.
async function fetchMe(): Promise<void> {
  if (!state.token) return
  try {
    const user = await apiFetchMe()
    state.user = user
    applyUserScope(String(user.id))
    persist()
  } catch (e) {
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status === 401) logout()
  }
}

// Synchronous on boot (called from main.ts BEFORE mount) so the router guard sees the
// right auth state on the very first navigation. Rehydrates token+user and scopes the
// stores immediately; then fires a background fetchMe to validate the token.
function loadFromStorage(): void {
  const stored = readPersisted()
  if (!stored) return
  state.token = stored.token
  state.user = stored.user
  setAuthToken(stored.token)
  applyUserScope(stored.user ? String(stored.user.id) : null)
  void fetchMe()
}

const isAuthenticated = computed(() => !!state.token)

export function useAuth() {
  return {
    ...toRefs(state),
    isAuthenticated,
    login,
    register,
    logout,
    loadFromStorage,
    fetchMe,
  }
}
