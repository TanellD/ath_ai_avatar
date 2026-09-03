import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    host: true,
    port: 5173,
    // Прокси не настраиваем: адреса сервисов приходят через VITE_API_URL /
    // VITE_WS_URL. Прокси в конфиге и переменная окружения — два источника
    // правды об одном адресе, и в референсном проекте они разошлись (там
    // /api до сих пор проксируется на несуществующий сервис).
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
