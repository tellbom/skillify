import { defineStore } from 'pinia'

// zh-cn only (D3 decision, docs/frontend-i18n-and-auth-module-plan.md §10). `langArray` is
// kept as a list rather than a bare string so a future locale can be added without reshaping
// this store's persisted contract.
export const useLocaleStore = defineStore('skillify-locale', {
  state: () => ({
    defaultLang: 'zh-cn',
    fallbackLang: 'zh-cn',
    langArray: [{ name: 'zh-cn' }],
  }),
  actions: {
    setLang(lang) {
      this.defaultLang = lang
    },
  },
  persist: { key: 'skillify-locale' },
})
