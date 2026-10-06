<script setup lang="ts">
// One Storefront checkout as a span tree, before and after the v4.1.0 release.
// Two real Storefront traces from the harness in Bronto, 6 Oct 2026:
// v4.0.0 trace 19c2a332… (checkout p50 117 ms) and v4.1.0 trace ea3af037… (p50 1,121 ms).
// The client span between web and shop-checkout is left out; the PSP call is
// shop-payments's outbound POST (the PSP itself isn't instrumented).
const props = withDefaults(defineProps<{ bad?: boolean }>(), { bad: false })

const GOOD = [
  { d: 0, name: 'POST /checkout', svc: 'shop-web', ms: 121.3, tag: 'http' },
  { d: 1, name: 'POST /checkout', svc: 'shop-checkout', ms: 117.0, tag: 'http' },
  { d: 2, name: 'POST /charge', svc: 'shop-payments', ms: 106.4, tag: 'http' },
  { d: 3, name: 'POST → PSP', svc: 'shop-payments', ms: 83.7, tag: 'ext' },
  { d: 2, name: 'storefront.insert · orders', svc: 'shop-checkout', ms: 5.2, tag: 'db' },
]
const BAD = [
  { d: 0, name: 'POST /checkout', svc: 'shop-web', ms: 1154.1, tag: 'http' },
  { d: 1, name: 'POST /checkout', svc: 'shop-checkout', ms: 1149.8, tag: 'http' },
  { d: 2, name: 'storefront.aggregate · orders', svc: 'shop-checkout', ms: 1039.3, tag: 'db', err: true },
  { d: 2, name: 'POST /charge', svc: 'shop-payments', ms: 99.2, tag: 'http' },
  { d: 3, name: 'POST → PSP', svc: 'shop-payments', ms: 75.6, tag: 'ext' },
  { d: 2, name: 'storefront.insert · orders', svc: 'shop-checkout', ms: 5.6, tag: 'db' },
]
const MAX = 1154.1
</script>

<template>
  <div class="it">
    <div v-for="(r, i) in (props.bad ? BAD : GOOD)" :key="r.name + i" class="row" :class="[r.tag, { err: r.err }]">
      <div class="label" :style="{ paddingLeft: r.d * 1.1 + 'rem' }"><span class="dot" />{{ r.name }}</div>
      <div class="svc">{{ r.svc }}</div>
      <div class="bar-wrap"><div class="bar" :style="{ width: Math.max(1, (r.ms / MAX) * 100) + '%' }" /></div>
      <div class="ms">{{ r.ms.toLocaleString(undefined, { maximumFractionDigits: 1 }) }} ms</div>
    </div>
  </div>
</template>

<style scoped>
.it { display: flex; flex-direction: column; gap: 0.3rem; font-size: 0.78rem; }
.row { display: grid; grid-template-columns: 19rem 9rem 1fr 6rem; align-items: center; gap: 0.6rem; }
.label { font-family: 'Geist Mono', monospace; white-space: nowrap; display: flex; align-items: center; gap: 0.45rem; overflow: hidden; }
.svc { color: var(--ink-dim); white-space: nowrap; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: var(--sapphire); }
.db .dot { background: #00684A; }
.ext .dot { background: var(--ink-dim); }
.err .dot { background: var(--claim); }
.bar-wrap { height: 10px; background: var(--border); border-radius: 5px; overflow: hidden; }
.bar { height: 100%; border-radius: 5px; background: var(--sapphire-soft); transition: width 0.4s ease; }
.db .bar { background: #8FD6B8; }
.err .bar { background: var(--claim); }
.err .label { color: var(--claim); font-weight: 600; }
.ms { font-family: 'Geist Mono', monospace; color: var(--ink-dim); text-align: right; white-space: nowrap; }
</style>
