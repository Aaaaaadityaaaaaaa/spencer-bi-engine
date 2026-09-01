<script setup lang="ts">
// Standalone auth screen (TASK-027): the ONLY view rendered without the app shell
// (App.vue drops the sidebar/header for public routes). A segmented Login/Register
// toggle drives one form; on success we route to ?redirect or /table.
//
// Batch 2 / Auth refinements:
//  • Value-prop line under the brand so first-time users know what they're getting.
//  • Show/hide password eye — a small habit-forming affordance.
//  • Password-strength meter on Register (three bars, only after the field has text).
//  • Live email checkmark — positive feedback that the form is going to submit.
//  • "Forgot password?" — honest placeholder: shows a toast (backend has no endpoint
//    yet) and explains, so the affordance is real but the gap is visible.
//  • Brand wordmark + tagline under the form so the screen stands on its own.
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Loader2, AlertCircle, Eye, EyeOff, Check, Sparkles } from '@lucide/vue'
import { useAuth } from '../composables/useAuth'
import { forgotPassword as apiForgot, resetPassword as apiReset } from '../services/api'
import { useToasts } from '../composables/useToast'

const route = useRoute()
const router = useRouter()
const { login, register, busy, error, user } = useAuth()
const { pushToast } = useToasts()

type Mode = 'login' | 'register' | 'forgot' | 'reset'
const mode = ref<Mode>('login')

const email = ref('')
const password = ref('')
const showPassword = ref(false)
const resetToken = ref(route.query.reset_token as string || '')
if (resetToken.value) {
  mode.value = 'reset'
}

// Client-side gate mirroring the server's RegisterRequest (password 8..72). Login only
// needs both fields present; the server is the real authority on either path.
const localError = ref<string | null>(null)
const canSubmit = computed(() => { if (mode.value === 'forgot') return email.value.trim().length > 0; if (mode.value === 'reset') return password.value.length > 0; return email.value.trim().length > 0 && password.value.length > 0 })

// Loose RFC-5322-ish check — just enough to gate the live "valid" checkmark; the
// server still has the final say.
const emailLooksValid = computed(() => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim()))
const emailIsComplete = computed(() => emailLooksValid.value && email.value.trim().length > 0)

// Three-segment strength: weak (only length), fair (length + letters OR digits),
// strong (length + letters + digits OR mixed case + symbol). Pure-function — no
// cleverness, no third-party zxcvbn dependency.
const passwordStrength = computed<0 | 1 | 2 | 3>(() => {
  const v = password.value
  if (!v) return 0
  let score = 0
  if (v.length >= 8) score++
  if (/[a-z]/.test(v) && /[A-Z]/.test(v)) score++
  else if (/[a-z]/.test(v) && /\d/.test(v)) score++
  if (/[^A-Za-z0-9]/.test(v)) score++
  if (v.length >= 12 && score >= 2) score = 3
  return Math.min(3, score) as 0 | 1 | 2 | 3
})
const strengthLabel = computed(() => ['', 'Weak', 'Fair', 'Strong'][passwordStrength.value])

function switchMode(next: Mode): void {
  if (mode.value === next) return
  mode.value = next
  localError.value = null
  error.value = null
  showPassword.value = false
}

function forgotPassword(): void {
  mode.value = 'forgot'
  localError.value = null
}

async function submit(): Promise<void> {
  if (!canSubmit.value || busy.value) return
  localError.value = null
  if ((mode.value === 'register' || mode.value === 'reset') && password.value.length < 8) {
    localError.value = 'Password must be at least 8 characters.'
    return
  }
  if (mode.value === 'forgot') {
    try {
      const res = await apiForgot(email.value)
      pushToast(res.message, 'success')
      mode.value = 'login'
    } catch (e: any) {
      localError.value = e?.response?.data?.detail || e.message
    }
    return
  }
  if (mode.value === 'reset') {
    try {
      const res = await apiReset(resetToken.value, password.value)
      pushToast(res.message, 'success')
      mode.value = 'login'
      router.replace('/login')
    } catch (e: any) {
      localError.value = e?.response?.data?.detail || e.message
    }
    return
  }
  const ok =
    mode.value === 'login'
      ? await login(email.value, password.value)
      : await register(email.value, password.value)
  if (!ok) return
  // Success toast
  const who = user.value?.email ?? 'your workspace'
  pushToast(
    mode.value === 'login' ? `Signed in as ${who}` : `Workspace created for ${who}`,
    'success'
  )
  const raw = route.query.redirect
  const redirect = typeof raw === 'string' && raw.startsWith('/') && !raw.startsWith('//') ? raw : '/table'
  await router.replace(redirect)
}

const inputCls =
  'w-full rounded-3 border border-outline-gray-2 bg-surface-base px-3 py-2 text-sm text-ink-gray-9 placeholder:text-ink-gray-4 focus:border-primary-5 focus:outline-none'
const labelCls = 'block text-xs font-medium text-ink-gray-7 mb-1'
</script>

<template>
  <div class="relative flex min-h-screen items-center justify-center bg-surface-gray-1 px-4 py-10 font-sans text-ink-gray-8">
    <!-- Decorative scrim-free backdrop: a single huge hairline ring so the screen
         has a sense of place without competing with the form. Two layered `::before`
         rings (defined globally below) live behind everything. -->
    <div aria-hidden="true" class="pointer-events-none absolute inset-0 overflow-hidden">
      <div class="auth-backdrop-ring absolute -left-40 -top-40 h-[420px] w-[420px] rounded-full border border-outline-gray-1" />
      <div class="auth-backdrop-ring absolute -right-32 bottom-[-180px] h-[420px] w-[420px] rounded-full border border-outline-gray-1" />
    </div>

    <div class="relative w-full max-w-sm">
      <!-- Brand + value prop -->
      <div class="mb-6 flex flex-col items-center gap-3 text-center">
        <div class="flex h-11 w-11 items-center justify-center rounded-4 bg-primary text-lg font-semibold text-ink-white shadow-sm">
          S
        </div>
        <div class="space-y-1">
          <h1 class="text-lg font-semibold text-ink-gray-9">
            {{ mode === 'login' ? 'Welcome back to Spencer' : mode === 'register' ? 'Welcome to Spencer' : mode === 'forgot' ? 'Reset Password' : 'New Password' }}
          </h1>
          <p class="mx-auto max-w-xs text-sm text-ink-gray-5">
            {{ mode === 'login' ? 'Pick up where you left off in your workspace.' : mode === 'register' ? 'Drop a CSV, ask in English, get a dashboard in seconds.' : mode === 'forgot' ? 'Enter your email to receive a reset link.' : 'Enter your new password below.' }}
          </p>
        </div>
      </div>

      <!-- Card -->
      <div class="rounded-5 border border-outline-gray-1 bg-surface-base p-6 shadow-sm">
        <!-- Segmented Login / Register toggle -->
        <div v-if="mode === 'login' || mode === 'register'" class="mb-5 grid grid-cols-2 gap-1 rounded-3 bg-surface-gray-2 p-1">
          <button
            type="button"
            class="rounded-2 px-3 py-1.5 text-sm font-medium transition-colors"
            :class="mode === 'login'
              ? 'bg-surface-base text-ink-gray-9 shadow-sm'
              : 'text-ink-gray-6 hover:text-ink-gray-8'"
            @click="switchMode('login')"
          >
            Sign in
          </button>
          <button
            type="button"
            class="rounded-2 px-3 py-1.5 text-sm font-medium transition-colors"
            :class="mode === 'register'
              ? 'bg-surface-base text-ink-gray-9 shadow-sm'
              : 'text-ink-gray-6 hover:text-ink-gray-8'"
            @click="switchMode('register')"
          >
            Register
          </button>
        </div>

        <form class="space-y-4" @submit.prevent="submit">
          <!-- Email -->
          <div v-if="mode !== 'reset'">
            <label :class="labelCls" for="auth-email">Email</label>
            <div class="relative">
              <input
                id="auth-email"
                v-model="email"
                type="email"
                autocomplete="email"
                spellcheck="false"
                :class="[inputCls, emailIsComplete ? 'pr-9' : '']"
                placeholder="you@example.com"
                required
              />
              <!-- Live validity checkmark (Batch 2): only shows once the address
                   looks well-formed. Pure positive feedback — disappears on edit. -->
              <Check
                v-if="emailIsComplete"
                aria-hidden="true"
                class="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-green-7"
              />
            </div>
          </div>

          <!-- Password + (optional) show/hide + strength meter (register only) -->
          <div v-if="mode !== 'forgot'">
            <div class="mb-1 flex items-baseline justify-between">
              <label :class="labelCls" for="auth-password">Password</label>
              <button
                v-if="mode === 'login'"
                type="button"
                class="text-[11px] font-medium text-primary-6 transition-colors hover:text-primary-7 hover:underline"
                @click="forgotPassword"
              >
                Forgot?
              </button>
            </div>
            <div class="relative">
              <input
                id="auth-password"
                v-model="password"
                :type="showPassword ? 'text' : 'password'"
                :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
                :class="[inputCls, 'pr-9']"
                :placeholder="mode === 'register' ? 'At least 8 characters' : '••••••••'"
                required
              />
              <button
                type="button"
                class="absolute right-2 top-1/2 -translate-y-1/2 rounded-2 p-1 text-ink-gray-5 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-8"
                :aria-label="showPassword ? 'Hide password' : 'Show password'"
                :aria-pressed="showPassword"
                @click="showPassword = !showPassword"
              >
                <component :is="showPassword ? EyeOff : Eye" class="h-4 w-4" />
              </button>
            </div>
            <!-- Strength meter: only meaningful on Register, and only after the user
                 has typed something. Three segments fill left -> right; color comes
                 from semantic tokens so it adapts if we ever add dark mode. -->
            <div v-if="mode === 'register' && password" class="mt-2 space-y-1">
              <div class="flex gap-1">
                <span
                  v-for="i in 3"
                  :key="i"
                  class="h-1 flex-1 rounded-full transition-colors"
                  :class="passwordStrength >= i
                    ? (passwordStrength === 1
                      ? 'bg-ink-red'
                      : passwordStrength === 2
                        ? 'bg-ink-amber'
                        : 'bg-ink-green-7')
                    : 'bg-surface-gray-2'"
                ></span>
              </div>
              <p class="text-[11px] text-ink-gray-5">
                Strength:
                <span
                  class="font-medium"
                  :class="passwordStrength === 1
                    ? 'text-ink-red'
                    : passwordStrength === 2
                      ? 'text-ink-amber'
                      : passwordStrength === 3
                        ? 'text-ink-green-7'
                        : 'text-ink-gray-5'"
                >{{ strengthLabel }}</span>
              </p>
            </div>
          </div>

          <!-- Errors: local validation first, then the server/network message. -->
          <p v-if="localError || error" class="flex items-start gap-1.5 text-xs text-ink-red">
            <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" /> {{ localError || error }}
          </p>

          <button
            type="submit"
            class="inline-flex w-full items-center justify-center gap-1.5 rounded-3 bg-primary px-4 py-2 text-sm font-medium text-ink-white shadow-sm transition-colors hover:bg-primary-7 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="!canSubmit || busy"
          >
            <Loader2 v-if="busy" class="h-4 w-4 animate-spin" />
            {{ mode === 'login' ? 'Sign in' : mode === 'register' ? 'Create account' : mode === 'forgot' ? 'Send Link' : 'Set Password' }}
          </button>
        </form>
      </div>

      <!-- Mode-switch prompt -->
      <p class="mt-4 text-center text-xs text-ink-gray-4">
        {{ mode === 'login' ? "Don't have an account?" : 'Already have an account?' }}
        <button
          type="button"
          class="font-medium text-primary-6 transition-colors hover:text-primary-7 hover:underline"
          @click="switchMode(mode === 'login' ? 'register' : 'login')"
        >
          {{ mode === 'login' ? 'Register' : 'Sign in' }}
        </button>
      </p>

      <!-- Brand wordmark + tagline (Batch 2) -->
      <div class="mt-8 flex items-center justify-center gap-1.5 text-[11px] text-ink-gray-4">
        <Sparkles class="h-3 w-3" />
        <span>Local-first analytics. Your data never leaves your machine.</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Subtle hairline ring motion; respects reduced-motion. */
.auth-backdrop-ring {
  animation: auth-drift 22s ease-in-out infinite alternate;
  opacity: 0.6;
}
.auth-backdrop-ring:nth-child(2) {
  animation-duration: 28s;
  animation-direction: alternate-reverse;
}
@keyframes auth-drift {
  from { transform: translate3d(0, 0, 0); }
  to   { transform: translate3d(20px, 18px, 0); }
}
@media (prefers-reduced-motion: reduce) {
  .auth-backdrop-ring { animation: none; }
}
</style>