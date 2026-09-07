/**
 * Прогон тренировки в настоящем браузере — то, чего не даёт стенд по сокету.
 *
 * По сокету измеримы задержки и протокол отмены, но три вещи живут только на
 * клиенте: остановка звука при перебивании (метрика 3, ≤300 мс), сам факт
 * рендера 3D-аватара и ошибки JS в консоли. Здесь всё это снимается.
 *
 * Звук инструментуется на уровне WebAudio: AudioQueue проигрывает реплики через
 * AudioBufferSourceNode и глушит их source.stop() из stopAll(). Патч на prototype
 * ловит и старт, и остановку — это ближе к правде, чем любой опрос состояния
 * React'а, потому что метрика 3 определена именно как «звук замолчал».
 *
 * Перед первым запуском нужны бинарники браузера — npm-пакета мало:
 *
 *   npm install && npx playwright install chromium
 *
 *   npm run test:browser -- [прогонов] [сценарий]   # сценарий или `mix`
 *   npm run test:browser:report                     # сводка по browser-runs.jsonl
 *
 * Стек должен быть поднят: стенд ходит в браузер на APP_URL (по умолчанию
 * http://localhost:5173) и ждёт живой gateway.
 */

import { writeFileSync, appendFileSync } from 'node:fs';
import { chromium } from 'playwright';

const RUNS = Number(process.argv[2] ?? 1);
const SCENARIO_ARG = process.argv[3] ?? 'objection_price';
/** `mix` чередует сценарии: одна и та же тренировка 25 раз подряд меряет
 *  только её, а не сервис. */
const SCENARIOS = SCENARIO_ARG === 'mix'
  ? ['objection_price', 'interview_junior']
  : [SCENARIO_ARG];
const BASE = process.env.APP_URL ?? 'http://localhost:5173';
const OUT = process.env.OUT ?? 'browser-runs.jsonl';

const REPLIES = {
  objection_price: [
    'Здравствуйте! Меня зовут Пётр, компания Ортекс. Расскажите, как у вас сейчас устроены закупки?',
    'А какой объём вы берёте в месяц и что именно держит вас у текущего поставщика?',
    'Дорого относительно чего? У нас в цену входит доставка и замена брака без экспертизы.',
    'Давайте я пришлю расчёт до пятницы, а в понедельник в одиннадцать созвонимся на пятнадцать минут.',
    'Отлично, тогда до понедельника. Спасибо за время!',
  ],
  interview_junior: [
    'Здравствуйте, Павел! Не волнуйтесь, это обычный разговор. Над чем работали последнее время?',
    'Возьмём последний проект — какую часть делали вы сами и что было самым сложным?',
    'Понял. Вернёмся с ответом до конца недели, в пятницу напишу в любом случае.',
    'Спасибо, что пришли. До связи!',
  ],
};

/** Ставится ДО любого скрипта страницы: патчить прототип надо раньше аватара. */
const PROBE = () => {
  const probe = { starts: [], stops: [], errors: [], active: 0 };
  window.__probe = probe;

  // Живые источники со временем, на которое они ЗАПЛАНИРОВАНЫ. Разница
  // принципиальная: AudioQueue вызывает source.start(startAt) на будущий
  // момент (сама очередь считает это как leadMs), поэтому «источник стартовал»
  // и «звук слышно» — разные события. Метрика 3 определена от слышимого звука,
  // и мерить остановку ещё не зазвучавшего чанка значило бы отчитаться цифрой,
  // за которой ничего нет.
  const live = new Set();
  window.__audible = () => {
    for (const source of live) {
      if (source.context.currentTime >= source.__at) return true;
    }
    return false;
  };

  const proto = window.AudioBufferSourceNode?.prototype;
  if (proto) {
    const start = proto.start;
    const stop = proto.stop;
    proto.start = function (...args) {
      probe.starts.push(performance.now());
      const when = typeof args[0] === 'number' ? args[0] : this.context.currentTime;
      this.__at = Math.max(when, this.context.currentTime);
      live.add(this);
      // Счётчик живых источников. Состояние React (.indicator--speaking) для
      // этого не годится: оно отстаёт от звука, и на гонке остаточный чанк
      // засчитывался как первый звук нового ответа — 21 мс вместо восьми
      // секунд. Здесь считается сам WebAudio.
      probe.active += 1;
      if (!this.__counted) {
        this.__counted = true;
        this.addEventListener('ended', () => this.__release());
      }
      return start.apply(this, args);
    };
    // Освобождение считаем ровно один раз на источник. Одного 'ended' мало:
    // при перебивании очередь глушит источники и закрывает AudioContext, а в
    // закрытом контексте отложенные 'ended' уже не доставляются — счётчик
    // навсегда оставался положительным. Из-за этого после перебивания на
    // ходу 3 «говорящим» выглядел и ход 5, которого никто не перебивал.
    proto.__release = function () {
      if (this.__released) return;
      this.__released = true;
      live.delete(this);
      probe.active = Math.max(0, probe.active - 1);
    };
    proto.stop = function (...args) {
      probe.stops.push(performance.now());
      this.__release();
      return stop.apply(this, args);
    };
  }

  // Индикатор обязан ПРОДЕРЖАТЬСЯ в покое, а не мигнуть им. Очередь пустеет
  // между чанками потока, и приложение на миг рапортует «Ваш ход», пока
  // реплика ещё идёт: в прошлой серии из-за этого первый ход отправлялся
  // поверх недоговорившего персонажа и уходил в «перебитые».
  window.__idleHeld = (ms) => {
    if (!document.querySelector('.indicator--idle')) {
      window.__idleSince = null;
      return false;
    }
    if (window.__idleSince == null) window.__idleSince = performance.now();
    return performance.now() - window.__idleSince >= ms;
  };

  window.__mark = (name) => {
    probe[name] = performance.now();
  };
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Опрос страницы до истины. `arg` уезжает в браузер вместе с проверкой. */
async function waitFor(page, check, { timeout = 60000, step = 150 } = {}, arg = null) {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    if (await page.evaluate(check, arg)) return true;
    await sleep(step);
  }
  return false;
}

async function runOne(browser, index, SCENARIO) {
  const run = {
    index,
    scenario: SCENARIO,
    openingTtfaMs: null,
    /** До разблокировки кнопки старта: загрузка 12.7 МБ GLB и подъём сцены. */
    glbReadyMs: null,
    /** От клика до готовности сессии: создание + подбор деталей брифа. */
    sessionReadyMs: null,
    turns: [],
    bargeInMs: null,
    avatarCanvas: false,
    consoleErrors: [],
    pageErrors: [],
    note: '',
  };

  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    permissions: ['microphone'],
  });
  await context.addInitScript(PROBE);
  const page = await context.newPage();

  page.on('console', (msg) => {
    if (msg.type() === 'error') run.consoleErrors.push(msg.text().slice(0, 200));
  });
  page.on('pageerror', (err) => run.pageErrors.push(String(err).slice(0, 200)));

  try {
    const navStart = Date.now();
    await page.goto(`${BASE}/session/${SCENARIO}`, { waitUntil: 'domcontentloaded' });

    // Кнопка старта разблокируется, только когда аватар отдал AudioContext,
    // то есть после загрузки 12.7 МБ GLB — отсюда длинный срок ожидания.
    const start = page.getByRole('button', { name: /Начать тренировку/ });
    await start.waitFor({ state: 'visible', timeout: 120000 });
    if (!(await waitFor(page, () => {
      const b = [...document.querySelectorAll('button')].find((x) =>
        /Начать тренировку/.test(x.textContent ?? ''));
      return b && !b.disabled;
    }, { timeout: 180000 }))) {
      run.note = 'кнопка старта так и не разблокировалась — аватар не загрузился';
      return run;
    }

    run.avatarCanvas = await page.evaluate(() => !!document.querySelector('.avatar canvas'));

    const openedAt = Date.now();
    run.glbReadyMs = Math.round(openedAt - navStart);
    await start.click();

    // Сценарий с брифом делит оверлей на два шага: сначала готовится сессия,
    // потом сотрудник читает обстановку и входит в разговор.
    const enter = page.getByRole('button', { name: /Войти в разговор/ });
    try {
      await enter.waitFor({ state: 'visible', timeout: 90000 });
      // Сессия создана и детали брифа подобраны — дальше только LLM и TTS.
      run.sessionReadyMs = Math.round(Date.now() - openedAt);
      await enter.click();
    } catch {
      run.note = 'брифа не было — одношаговый старт';
    }

    // Открывающая реплика персонажа: инициативу держит агент (§1).
    await waitFor(page, () => window.__probe.starts.length > 0, { timeout: 120000 });
    const firstStart = await page.evaluate(() => window.__probe.starts[0] ?? null);
    if (firstStart !== null) run.openingTtfaMs = Math.round(Date.now() - openedAt);

    // «Реплика закончилась» — это .indicator--idle («Ваш ход»), а не active === 0.
    // Счётчик живых источников слишком дёрганый: TTS шлёт чанки потоком, и в
    // паузе между концом одного и приходом следующего он законно падает в ноль.
    // Ход 1 из-за этого получил «75 мс» — это был чанк ТОЙ ЖЕ открывающей
    // реплики, пришедший сразу после отправки. Приложение знает лучше: очередь
    // отдаёт idle, когда звук кончился и продолжения не ждут. На тот же признак
    // смотрит живой человек, решая, что настала его очередь говорить.
    await waitFor(page, (ms) => window.__idleHeld(ms), { timeout: 120000, step: 100 }, 1500);

    const composer = page.locator('.composer__input');
    const replies = REPLIES[SCENARIO];

    // Ровно одно перебивание за прогон, на третьем ходу: к нему разговор уже
    // разошёлся, а до конца сценария ещё есть запас.
    const INTERRUPT_ON = 3;

    for (let i = 0; i < replies.length; i += 1) {
      await composer.waitFor({ state: 'visible', timeout: 30000 });
      if (await composer.isDisabled()) await waitFor(page, () =>
        !document.querySelector('.composer__input')?.disabled, { timeout: 60000 });

      const before = await page.evaluate(() => window.__probe.starts.length);

      // Текст набираем ДО проверки «звучит ли»: fill и evaluate занимают
      // сотни миллисекунд, и на коротких репликах персонаж успевал договорить
      // между проверкой и Enter — глушить было нечего, метрика 3 не снималась.
      await composer.fill(replies[i]);
      if (i + 1 === INTERRUPT_ON) {
        await waitFor(page, () => window.__audible(), { timeout: 60000, step: 10 });
      }
      const speaking = await page.evaluate(() => window.__audible());

      // Счётчик остановок снимаем ДО Enter. AudioQueue.stopAll() синхронный и
      // отрабатывает внутри самого обработчика нажатия — если считать после,
      // остановка уже сосчитана, и мы ждём СЛЕДУЮЩУЮ, которой не будет.
      // Отсюда и брались пустые bargeInMs на заведомо перебитом ходу.
      const stopsBefore = await page.evaluate(() => window.__probe.stops.length);
      await page.evaluate(() => window.__mark('sentAt'));
      const sentWall = Date.now();
      await composer.press('Enter');

      // Перебивание: если персонаж говорил, звук обязан замолкнуть локально и
      // сразу — это и есть метрика 3.
      if (speaking && run.bargeInMs === null) {
        const stopped = await waitFor(page, (n) => window.__probe.stops.length > n, {
          timeout: 5000, step: 5,
        }, stopsBefore);
        if (stopped) {
          run.bargeInMs = await page.evaluate((n) => {
            const p = window.__probe;
            return Math.round(p.stops[n] - p.sentAt);
          }, stopsBefore);
        }
      }

      const heard = await waitFor(page, (n) => window.__probe.starts.length > n, {
        timeout: 120000, step: 100,
      }, before);

      run.turns.push({
        i: i + 1,
        // На перебитом ходу первый start — это ещё не заглушенный чанк старой
        // реплики, а не ответ. Такую цифру в метрику 1 брать нельзя.
        ttfaMs: speaking ? null : heard ? Date.now() - sentWall : null,
        interrupted: speaking,
      });

      // Дать реплике доиграть — кроме хода перед запланированным перебиванием:
      // там персонаж обязан ГОВОРИТЬ в момент отправки.
      if (i + 2 === INTERRUPT_ON) {
        // Перед ходом-перебиванием тишины НЕ ждём: персонаж должен говорить в
        // момент отправки. Само ожидание звука стоит вплотную к Enter выше.
      } else {
        await waitFor(page, (ms) => window.__idleHeld(ms), { timeout: 120000, step: 100 }, 1500);
      }
    }

    run.stages = await page.evaluate(() =>
      document.querySelectorAll('.session__progress-dot--done').length);
    run.chatLines = await page.evaluate(() =>
      document.querySelectorAll('.chatpanel__line').length);
  } catch (error) {
    run.note = `${error.name}: ${String(error.message).slice(0, 160)}`;
  } finally {
    if (index === 1) {
      await page.screenshot({ path: 'browser-run-1.png', fullPage: false }).catch(() => {});
    }
    await context.close();
  }
  return run;
}

const browser = await chromium.launch({
  args: [
    // Микрофон без окна разрешений и с синтетическим сигналом: реального
    // устройства в headless нет, а getUserMedia на localhost разрешён —
    // localhost браузер считает безопасным контекстом.
    '--use-fake-ui-for-media-stream',
    '--use-fake-device-for-media-stream',
    // Иначе WebGL в headless молча не поднимется и аватар не отрендерится.
    '--use-gl=angle',
    '--use-angle=swiftshader',
    '--ignore-gpu-blocklist',
  ],
});

writeFileSync(OUT, '');
/** Дождаться, пока шлюз снова отвечает: подряд идущие сессии его перегружали,
 *  и прогон падал с ERR_SOCKET_NOT_CONNECTED, а браузер сообщал это как
 *  ошибку CORS — на упавшем ответе просто нет CORS-заголовков. */
async function waitForGateway(url, tries = 30) {
  for (let n = 0; n < tries; n += 1) {
    try {
      const res = await fetch(`${url}/health`);
      if (res.ok) return true;
    } catch {
      // шлюз ещё не поднялся — пробуем дальше
    }
    await sleep(2000);
  }
  return false;
}

const GATEWAY = process.env.GATEWAY_URL ?? 'http://localhost:8000';

for (let i = 1; i <= RUNS; i += 1) {
  if (i > 1) {
    await sleep(5000);
    if (!(await waitForGateway(GATEWAY))) {
      console.log(`#${i} пропущен: шлюз не отвечает`);
      continue;
    }
  }
  const SCENARIO = SCENARIOS[(i - 1) % SCENARIOS.length];
  const run = await runOne(browser, i, SCENARIO);
  appendFileSync(OUT, `${JSON.stringify(run)}\n`);
  const heard = run.turns.filter((t) => t.ttfaMs !== null).length;
  console.log(
    `#${i} ${SCENARIO} | GLB ${run.glbReadyMs ?? '—'}мс + сессия ${
      run.sessionReadyMs ?? '—'}мс + звук ${run.openingTtfaMs ?? '—'}мс | ` +
    `ходов со звуком ${heard}/${run.turns.length} | ` +
    `перебивание ${run.bargeInMs ?? '—'}мс | canvas ${run.avatarCanvas ? 'да' : 'НЕТ'} | ` +
    `ошибок JS ${run.consoleErrors.length + run.pageErrors.length}` +
    (run.note ? ` | ${run.note}` : ''),
  );
}
await browser.close();
