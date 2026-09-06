import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

/**
 * Vite с 5.4.12 проверяет заголовок Host и отвечает 403 всему, кроме
 * localhost. Туннель (cloudflared/ngrok) шлёт свой домен — и dev-сервер
 * молча отдаёт «Blocked request», из-за чего телефон видит пустую страницу,
 * хотя всё остальное настроено верно.
 *
 * По умолчанию оставляем как есть: dev-сервер, открытый наружу без спроса, —
 * это не то, что должно включаться само. Открывается одной переменной:
 *
 *     VITE_ALLOWED_HOSTS=.trycloudflare.com   # поддомены (точка в начале)
 *     VITE_ALLOWED_HOSTS=true                 # любой хост
 *
 * Прод-раздачи это не касается: там nginx, у него такой проверки нет.
 */
function allowedHosts(): true | string[] | undefined {
  const raw = process.env.VITE_ALLOWED_HOSTS?.trim();
  if (!raw) return undefined;
  if (raw === 'true') return true;
  return raw.split(',').map((host) => host.trim()).filter(Boolean);
}

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    host: true,
    port: 5173,
    allowedHosts: allowedHosts(),
    // Раньше здесь стояло «прокси не настраиваем: два источника правды об
    // одном адресе». С переходом на один origin эта причина переворачивается —
    // источник правды становится ровно один, и это прокси: адреса сервисов
    // больше не приходят из VITE_* (см. src/api/origins.ts).
    //
    // Понадобилось это ради телефона: микрофон работает только по HTTPS, а под
    // HTTPS четыре сервиса на четырёх портах означали бы четыре туннеля и
    // четыре сертификата, да ещё `ws://` со страницы по https браузер режет
    // как mixed content.
    //
    // Пути обязаны совпадать с nginx.conf и с PATHS в src/api/origins.ts.
    proxy: {
      '/api': { target: 'http://gateway:8000', rewrite: (path) => path.replace(/^\/api/, '') },
      '/scenario': {
        target: 'http://scenario-service:8050',
        rewrite: (path) => path.replace(/^\/scenario/, ''),
      },
      '/ai': { target: 'http://ai-service:8030', rewrite: (path) => path.replace(/^\/ai/, '') },
      // Префикс не срезаем: маршрут шлюза сам начинается с /ws/session/:id.
      '/ws': { target: 'ws://gateway:8000', ws: true },
      '/speech': {
        target: 'ws://speech-service:8010',
        ws: true,
        rewrite: (path) => path.replace(/^\/speech/, ''),
      },
    },
    watch: {
      // Контейнер видит исходники через bind-mount с Windows-хоста —
      // нативные inotify-события оттуда часто не долетают (docker-compose.override.yml),
      // и Vite молча продолжает отдавать закешированный трансформ старого
      // файла, хотя на диске уже другой. Поллинг это чинит ценой CPU.
      usePolling: true,
      interval: 300,
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});
