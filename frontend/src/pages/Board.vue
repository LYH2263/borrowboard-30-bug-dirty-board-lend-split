<template>
  <div class="split">
    <section class="pane">
      <h2>可借物</h2>
      <div v-for="i in board.available" :key="i.id" class="item">
        <strong>{{ i.title }}</strong>
        <span class="chip chip-ok">计入可借</span>
        <div class="muted">物主 {{ i.owner || '—' }}</div>
        <input v-model="forms[i.id].borrower" placeholder="借用人" />
        <input v-model="forms[i.id].due_date" placeholder="应还日 YYYY-MM-DD" />
        <button @click="lend(i.id)">借出通过</button>
        <div v-if="results[i.id]" class="deny-note">未放行：{{ results[i.id] }}（未产生借单）</div>
      </div>

      <h3 class="blocked-head">暂不可借（不计入可借数）</h3>
      <div v-for="i in board.blocked" :key="i.id" class="item blocked">
        <strong>{{ i.title }}</strong>
        <span class="chip chip-block">不予放行</span>
        <div class="muted">物主 {{ i.owner || '（空）' }}</div>
        <div class="muted">
          不可借原因：{{ blockedText(i) }}
        </div>
      </div>
      <div v-if="!board.blocked || !board.blocked.length" class="muted">—</div>
    </section>
    <section class="pane">
      <h2>在借 / 逾期</h2>
      <div v-for="l in [...board.overdue, ...board.active]" :key="l.id" class="item" :class="{ overdue: l.overdue }">
        <strong>{{ l.title }}</strong> → {{ l.borrower }}
        <div class="muted">应还 {{ l.due_date }} {{ l.overdue ? '· 逾期' : '' }}</div>
        <button @click="ret(l.id)">归还</button>
      </div>
    </section>
  </div>
</template>
<script setup>
import { inject, reactive, watch } from 'vue'
import { api } from '../api'
const board = inject('board')
const reload = inject('reloadBoard')
const forms = reactive({})
const results = reactive({})
const reasonText = {
  owner_missing: '无主',
  dirty_data: '脏数据',
  already_on_loan: '已有在借',
  item_not_available: '当前不可借',
}
watch(board, (b) => {
  for (const i of [...(b.available || []), ...(b.blocked || [])]) {
    if (!forms[i.id]) forms[i.id] = { borrower: '邻居', due_date: '2026-12-31' }
  }
}, { immediate: true, deep: true })
function blockedText(i) {
  if (i.active_loans) return reasonText.already_on_loan
  if (i.blocked_reasons && i.blocked_reasons.length) {
    return i.blocked_reasons.map((r) => reasonText[r] || r).join('、')
  }
  return reasonText.item_not_available
}
async function lend(id) {
  results[id] = ''
  try {
    await api('/items/' + id + '/lend', { method: 'POST', body: JSON.stringify(forms[id]) })
    await reload()
  } catch (e) {
    // 被拒：后端不产生 loan、不改状态，这里明确告诉操作者本次没扣到，
    // 可借栏也不做乐观移除——重新以服务端 board 为唯一资格世界。
    results[id] = reasonText[e.message] || e.message
    await reload()
  }
}
async function ret(id) {
  await api('/loans/' + id + '/return', { method: 'POST', body: '{}' })
  await reload()
}
</script>
