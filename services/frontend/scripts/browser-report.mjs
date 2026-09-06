/**
 * Сводка по браузерным прогонам: метрики §9, которые видны только на клиенте.
 *
 *   node scripts/browser-report.mjs [файл.jsonl]
 */

import { readFileSync } from 'node:fs';

const FILE = process.argv[2] ?? 'browser-sweep.jsonl';
const runs = readFileSync(FILE, 'utf8')
  .split('\n')
  .filter(Boolean)
  .map((line) => JSON.parse(line));

const median = (xs) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2);
};
const pct = (xs, p) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.max(0, Math.min(s.length - 1, Math.round((s.length - 1) * p)))];
};
const row = (name, value) => console.log(`  ${name.padEnd(42)} ${value}`);

// Ходы с перебиванием в метрику 1 не идут: там первый старт принадлежит ещё
// не заглушенной старой реплике, а не ответу.
const ttfa = runs.flatMap((r) => r.turns.filter((t) => !t.interrupted).map((t) => t.ttfaMs));
const heard = ttfa.filter((v) => v !== null);
const silent = ttfa.length - heard.length;
const barge = runs.map((r) => r.bargeInMs).filter((v) => v !== null);
const openings = runs.map((r) => r.openingTtfaMs).filter((v) => v !== null);
const jsErrors = runs.flatMap((r) => [...r.consoleErrors, ...r.pageErrors]);
const noCanvas = runs.filter((r) => !r.avatarCanvas);
const notes = runs.filter((r) => r.note);

console.log(`\n=== БРАУЗЕРНЫХ ПРОГОНОВ: ${runs.length} ===\n`);

console.log('--- Метрика 1: время до первого звука (порог 3,0 с) ---');
row('ходов со звуком', `${heard.length} из ${ttfa.length}`);
row('ходов без звука', String(silent));
if (heard.length) {
  row('медиана', `${(median(heard) / 1000).toFixed(2)} с`);
  row('p95', `${(pct(heard, 0.95) / 1000).toFixed(2)} с`);
  row('уложились в 3,0 с', `${heard.filter((v) => v <= 3000).length} из ${heard.length}`);
}
if (openings.length) {
  // Открытие меряется от захода на страницу, поэтому в него входит не только
  // конвейер: сначала грузится 11-мегабайтная модель, потом создаётся сессия
  // (а это ещё и вызов LLM за деталями брифа), и лишь затем идёт реплика.
  // Одним числом это выглядит как провал метрики 1, хотя метрика 1 — про ход,
  // а не про холодный старт. Разложение показывает, за что платим на самом деле.
  const glb = runs.map((r) => r.glbReadyMs).filter((v) => v != null);
  const ready = runs.map((r) => r.sessionReadyMs).filter((v) => v != null);
  row('открытие, всего (медиана)', `${(median(openings) / 1000).toFixed(2)} с`);
  if (glb.length) row('  из них загрузка модели', `${(median(glb) / 1000).toFixed(2)} с`);
  if (ready.length) row('  из них создание сессии', `${(median(ready) / 1000).toFixed(2)} с`);
}

console.log('\n--- Метрика 3: остановка при перебивании (порог 300 мс, цель 150) ---');
row('замеров', String(barge.length));
if (barge.length) {
  row('медиана', `${median(barge)} мс`);
  row('p95', `${pct(barge, 0.95)} мс`);
  row('максимум', `${Math.max(...barge)} мс`);
  row('уложились в 300 мс', `${barge.filter((v) => v <= 300).length} из ${barge.length}`);
  row('уложились в цель 150 мс', `${barge.filter((v) => v <= 150).length} из ${barge.length}`);
}

console.log('\n--- Клиент ---');
row('ошибок JS', jsErrors.length ? String(jsErrors.length) : 'нет');
row('прогонов без canvas аватара', `${noCanvas.length} из ${runs.length}`);
row('прогонов с замечаниями', `${notes.length} из ${runs.length}`);
if (jsErrors.length) {
  const top = {};
  for (const e of jsErrors) top[e] = (top[e] ?? 0) + 1;
  console.log('\n  Тексты ошибок:');
  for (const [text, n] of Object.entries(top).sort((a, b) => b[1] - a[1]).slice(0, 8)) {
    console.log(`    ×${n}  ${text.slice(0, 110)}`);
  }
}
if (notes.length) {
  console.log('\n  Замечания:');
  for (const r of notes) console.log(`    #${r.index} ${r.note}`);
}

console.log('\n--- По сценариям ---');
for (const name of [...new Set(runs.map((r) => r.scenario))]) {
  const sub = runs.filter((r) => r.scenario === name);
  const t = sub.flatMap((r) => r.turns.filter((x) => !x.interrupted).map((x) => x.ttfaMs));
  const h = t.filter((v) => v !== null);
  row(name, `прогонов ${sub.length} · звук ${h.length}/${t.length} · медиана ${
    h.length ? `${(median(h) / 1000).toFixed(1)} с` : '—'}`);
}
