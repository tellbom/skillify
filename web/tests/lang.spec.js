import { describe, it, expect } from 'vitest'
import { createApp } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { loadLang } from '../src/lang/index.js'

describe('loadLang', () => {
  it('creates a zh-cn i18n instance with element-plus + page-scoped messages merged', async () => {
    setActivePinia(createPinia())
    const app = createApp({ render: () => null })
    const i18n = await loadLang(app)

    expect(i18n.global.locale.value).toBe('zh-cn')
    // page-scoped: src/lang/zh-cn/common.js -> messages['zh-cn'].common.loading
    expect(i18n.global.t('common.loading')).toBe('加载中…')
    // element-plus locale merged in under the 'el' namespace
    expect(i18n.global.getLocaleMessage('zh-cn').el).toBeTruthy()
    expect(i18n.global.getLocaleMessage('zh-cn').name).toBe('zh-cn')
  })
})
