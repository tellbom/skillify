<script setup>
import { computed } from 'vue'

const props = defineProps({
  navItems: { type: Array, default: () => [] },
})

const currentYear = new Date().getFullYear()

function collectLeafItems(items, result = []) {
  for (const item of items) {
    if (Array.isArray(item.children) && item.children.length > 0) {
      collectLeafItems(item.children, result)
    } else if (item.path && item.title) {
      result.push(item)
    }
  }
  return result
}

const quickLinks = computed(() => collectLeafItems(props.navItems))
</script>

<template>
  <footer class="app-footer">
    <div class="footer-inner">
      <div class="footer-grid">
        <section class="footer-brand" aria-labelledby="footer-brand-title">
          <h2 id="footer-brand-title" class="footer-logo">Skill<span>ify</span></h2>
          <p>面向内部团队的技能发现、共享与治理平台。</p>
          <p class="internal-note"><span class="status-dot" aria-hidden="true"></span>仅供内部使用</p>
        </section>

        <nav class="footer-section" aria-label="业务快捷入口">
          <h2>快捷入口</h2>
          <!-- <div v-if="quickLinks.length" class="footer-link-list">
            <router-link
              v-for="item in quickLinks"
              :key="item.name || item.path"
              :to="item.path"
              class="footer-nav-link"
            >
              {{ item.title }}
            </router-link>
          </div> -->
          <span class="empty-links">暂无可用入口</span>
        </nav>

        <section class="footer-section" aria-labelledby="footer-resources-title">
          <h2 id="footer-resources-title">支持与资源</h2>
          <div class="footer-link-list">
            <button type="button" class="placeholder-link" disabled>
              <span>使用文档</span>
              <span class="pending-badge">暂未开放</span>
            </button>
            <button type="button" class="placeholder-link" disabled>
              <span>问题反馈</span>
              <span class="pending-badge">暂未开放</span>
            </button>
          </div>
        </section>
      </div>

      <div class="footer-bottom">
        <span>© {{ currentYear }} Skillify</span>
        <span>让可靠的内部技能更容易被发现和复用</span>
      </div>
    </div>
  </footer>
</template>

<style scoped>
.app-footer {
  width: 100%;
  border-top: 1px solid #272727;
  background: #101010;
}

.footer-inner {
  box-sizing: border-box;
  width: 100%;
  max-width: 1320px;
  margin: 0 auto;
  padding: 34px 28px 20px;
}

.footer-grid {
  display: grid;
  grid-template-columns: minmax(260px, 1.7fr) minmax(180px, 1fr) minmax(220px, 1fr);
  gap: 48px;
  padding-bottom: 28px;
}

.footer-brand h2,
.footer-section h2 {
  margin: 0;
}

.footer-logo {
  color: #f0f0f0;
  font-size: 18px;
  font-weight: 750;
  letter-spacing: -0.2px;
}

.footer-logo span {
  color: #80cbc4;
}

.footer-brand p {
  max-width: 360px;
  margin: 10px 0 0;
  color: #777;
  font-size: 12.5px;
  line-height: 1.7;
}

.footer-brand .internal-note {
  display: flex;
  align-items: center;
  margin-top: 14px;
  color: #929292;
  gap: 7px;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #80cbc4;
  box-shadow: 0 0 0 3px rgb(128 203 196 / 10%);
}

.footer-section h2 {
  margin-bottom: 12px;
  color: #bcbcbc;
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0.04em;
}

.footer-link-list {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  flex-direction: column;
}

.footer-nav-link {
  border-radius: 5px;
  color: #777;
  font-size: 12.5px;
  line-height: 1.6;
  text-decoration: none;
  transition: color 0.15s ease;
}

.footer-nav-link:hover,
.footer-nav-link:focus-visible {
  color: #80cbc4;
  outline: none;
}

.empty-links {
  color: #555;
  font-size: 12.5px;
}

.placeholder-link {
  display: inline-flex;
  align-items: center;
  padding: 0;
  border: 0;
  color: #686868;
  background: transparent;
  font: inherit;
  font-size: 12.5px;
  gap: 8px;
  cursor: not-allowed;
}

.pending-badge {
  padding: 1px 6px;
  border: 1px solid #303030;
  border-radius: 999px;
  color: #5f5f5f;
  font-size: 10px;
  line-height: 1.5;
}

.footer-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 18px;
  border-top: 1px solid #242424;
  color: #5f5f5f;
  font-size: 11.5px;
}

@media (max-width: 760px) {
  .footer-inner {
    padding-inline: 20px;
  }

  .footer-grid {
    grid-template-columns: 1fr 1fr;
    gap: 28px;
  }

  .footer-brand {
    grid-column: 1 / -1;
  }
}

@media (max-width: 480px) {
  .footer-grid {
    grid-template-columns: 1fr;
  }

  .footer-brand {
    grid-column: auto;
  }

  .footer-bottom {
    align-items: flex-start;
    gap: 6px;
    flex-direction: column;
  }
}
</style>
