<script setup lang="ts">
// Standalone auth screen (TASK-027): the ONLY view rendered without the app shell
// (App.vue drops the sidebar/header for public routes). A segmented Login/Register
// toggle drives one form; on success we route to ?redirect or /table. House style is
// borrowed from OpDialog (inputCls/labelCls) + the primary button used app-wide.
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Loader2, AlertCircle } from '@lucide/vue'
import { useAuth } from '../composables/useAuth'

const route = useRoute()
const router = useRouter()
const { login, register, busy, error } = useAuth()

type Mode = 'login' | 'register'
const mode = ref<Mode>('login')

const email = ref('')
const password = ref('')

// Client-side gate mirroring the server's RegisterRequest (password 8..72). Login only
// needs both fields present; the server is the real authority on either path.
const localError = ref<string | null>(null)
const canSubmit = computed(() => email.value.trim().length > 0 && password.value.length > 0)

function switchMode(next: Mode): void {
  if (mode.value === next) return
  mode.value = next
  localError.value = null
  error.value = null
}

async function submit(): Promise<void> {
  if (!canSubmit.value || busy.value) return
  localError.value = null
  if (mode.value === 'register' && password.value.length < 8) {
    localError.value = 'Password must be at least 8 characters.'
    return
  }
  const ok =
    mode.value === 'login'
      ? await login(email.value, password.value)
      : await register(email.value, password.value)
  if (!ok) return
  // ?redirect is set by the router guard when it bounces an unauthenticated deep-link.
  // Only honor an app-internal path (leading "/", not "//") so it can't be used as an
  // open redirect to another origin.
  const raw = route.query.redirect
  const redirect = typeof raw === 'string' && raw.startsWith('/') && !raw.startsWith('//') ? raw : '/table'
  await router.replace(redirect)
}

const inputCls =
  'w-full rounded-3 border border-outline-gray-2 bg-surface-base px-3 py-2 text-sm text-ink-gray-9 focus:border-primary-5 focus:outline-none'
const labelCls = 'block text-xs font-medium text-ink-gray-7 mb-1'
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-surface-gray-1 px-4 font-sans text-ink-gray-8">
    <div class="w-full max-w-sm">
      <!-- Brand -->
      <div class="mb-6 flex flex-col items-center gap-3">
        <div class="flex h-11 w-11 items-center justify-center rounded-4 bg-primary text-lg font-semibold text-ink-white shadow-sm">
          S
        </div>
        <div class="text-center">
          <h1 class="text-lg font-semibold text-ink-gray-9">Welcome to Spencer</h1>
          <p class="mt-0.5 text-sm text-ink-gray-5">
            {{ mode === 'login' ? 'Sign in to your workspace' : 'Create your workspace account' }}
          </p>
        </div>
      </div>

      <div class="rounded-5 border border-outline-gray-1 bg-surface-base p-6 shadow-sm">
        <!-- Segmented Login / Register toggle -->
        <div class="mb-5 grid grid-cols-2 gap-1 rounded-3 bg-surface-gray-2 p-1">
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
          <div>
            <label :class="labelCls" for="auth-email">Email</label>
            <input
              id="auth-email"
              v-model="email"
              type="email"
              autocomplete="email"
              :class="inputCls"
              placeholder="you@example.com"
              required
            />
          </div>
          <div>
            <label :class="labelCls" for="auth-password">Password</label>
            <input
              id="auth-password"
              v-model="password"
              type="password"
              :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
              :class="inputCls"
              :placeholder="mode === 'register' ? 'At least 8 characters' : '••••••••'"
              required
            />
          </div>

          <!-- Errors: local validation first, then the server/network message. -->
          <p v-if="localError || error" class="flex items-start gap-1.5 text-xs text-ink-red">
            <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" /> {{ localError || error }}
          </p>

          <button
            type="submit"
            class="inline-flex w-full items-center justify-center gap-1.5 rounded-3 bg-primary px-4 py-2 text-sm font-medium text-ink-white shadow-sm hover:bg-primary-7 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="!canSubmit || busy"
          >
            <Loader2 v-if="busy" class="h-4 w-4 animate-spin" />
            {{ mode === 'login' ? 'Sign in' : 'Create account' }}
          </button>
        </form>
      </div>

      <p class="mt-4 text-center text-xs text-ink-gray-4">
        {{ mode === 'login' ? "Don't have an account?" : 'Already have an account?' }}
        <button
          type="button"
          class="font-medium text-primary hover:underline"
          @click="switchMode(mode === 'login' ? 'register' : 'login')"
        >
          {{ mode === 'login' ? 'Register' : 'Sign in' }}
        </button>
      </p>
    </div>
  </div>
</template>
