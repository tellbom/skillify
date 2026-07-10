import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/display.css'
import './style.css'
import './styles/workflow-tokens.scss'
import App from './App.vue'
import router from './router/index.js'
import { loadLang } from './lang/index.js'

// Load order matters (docs/frontend-i18n-and-auth-module-plan.md §3.3): pinia first (loadLang
// reads the locale store), then i18n before router/ElementPlus so every component sees a
// ready i18n instance on first render.
async function bootstrap() {
  const app = createApp(App)

  const pinia = createPinia()
  pinia.use(piniaPluginPersistedstate)
  app.use(pinia)

  await loadLang(app)

  app.use(router).use(ElementPlus).mount('#app')
}

bootstrap()
