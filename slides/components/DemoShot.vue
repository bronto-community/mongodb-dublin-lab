<script setup lang="ts">
import { ref } from 'vue'

// A screenshot from the live demo, shown when the live version can't be (wifi,
// a slow query, a login). Until the image exists it shows a dashed box naming
// the file, so the deck still builds and the gap is obvious in rehearsal.
const props = withDefaults(defineProps<{
  src: string
  caption?: string
  tag?: string
}>(), { tag: 'backup' })

const missing = ref(false)
</script>

<template>
  <figure class="shot">
    <div v-if="missing" class="ph">{{ props.src }}</div>
    <img v-else :src="props.src" @error="missing = true" />
    <span class="tag">{{ props.tag }}</span>
    <figcaption v-if="caption">{{ caption }}</figcaption>
  </figure>
</template>

<style scoped>
.shot { position: relative; margin: 0; }
.shot img {
  display: block; width: 100%; height: auto;
  border: 1px solid var(--border); border-radius: 8px;
  box-shadow: 0 12px 32px -20px rgba(43, 38, 32, 0.45);
}
.ph {
  display: flex; align-items: center; justify-content: center;
  aspect-ratio: 16 / 9; border: 2px dashed var(--border); border-radius: 8px;
  font-family: 'Geist Mono', monospace; font-size: 0.75rem; color: var(--ink-dim);
}
.tag {
  position: absolute; top: 0.5rem; right: 0.5rem;
  font-family: 'Geist Mono', monospace; font-size: 0.6rem; text-transform: uppercase; letter-spacing: 0.12em;
  background: var(--surface); color: var(--ink-dim); border: 1px solid var(--border); border-radius: 4px;
  padding: 0.1rem 0.4rem;
}
figcaption { font-size: 0.75rem; color: var(--ink-dim); margin-top: 0.4rem; }
</style>
