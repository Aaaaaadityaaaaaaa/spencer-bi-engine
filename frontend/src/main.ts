import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import router from './router'
import { useAuth } from './composables/useAuth'

// Rehydrate the persisted token BEFORE mounting so the router's beforeEach guard sees
// the correct auth state on the very first navigation (no login-flash for a returning
// user). Synchronous: it reads localStorage + scopes the per-user stores immediately,
// then fires a background token-revalidation (see useAuth.loadFromStorage).
useAuth().loadFromStorage()

createApp(App).use(router).mount('#app')
