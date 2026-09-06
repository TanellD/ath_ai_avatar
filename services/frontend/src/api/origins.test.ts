/**
 * Адреса сервисов решают, заработает ли приложение с телефона вообще: под
 * https страница обязана ходить в wss, а не в ws, иначе браузер режет сокет
 * как mixed content и сессия не открывается ни разу.
 */

import { describe, expect, test } from 'vitest';

import { resolveOrigins } from './origins';

const https = { protocol: 'https:', host: 'demo.trycloudflare.com' };
const http = { protocol: 'http:', host: 'localhost:5173' };

describe('resolveOrigins — один origin', () => {
  test('под https сокеты идут в wss, а не в ws', () => {
    const origins = resolveOrigins({}, https);

    expect(origins.ws).toBe('wss://demo.trycloudflare.com');
    expect(origins.speechWs).toBe('wss://demo.trycloudflare.com/speech');
  });

  test('под http остаётся ws', () => {
    expect(resolveOrigins({}, http).ws).toBe('ws://localhost:5173');
  });

  test('REST-сервисы получают путь прокси на том же хосте', () => {
    const origins = resolveOrigins({}, https);

    expect(origins.api).toBe('https://demo.trycloudflare.com/api');
    expect(origins.scenario).toBe('https://demo.trycloudflare.com/scenario');
    expect(origins.ai).toBe('https://demo.trycloudflare.com/ai');
  });

  test('база сокета сессии — без пути: маршрут шлюза сам начинается с /ws', () => {
    // Иначе sessionSocketUrl собрал бы /ws/ws/session/:id.
    expect(resolveOrigins({}, https).ws.endsWith('/ws')).toBe(false);
  });
});

describe('resolveOrigins — раздельные адреса', () => {
  test('VITE_* сильнее умолчания', () => {
    const origins = resolveOrigins(
      {
        VITE_API_URL: 'http://192.168.1.10:8000',
        VITE_WS_URL: 'ws://192.168.1.10:8000',
        VITE_SCENARIO_API_URL: 'http://192.168.1.10:8050',
        VITE_AI_API_URL: 'http://192.168.1.10:8030',
        VITE_SPEECH_WS_URL: 'ws://192.168.1.10:8010',
      },
      https,
    );

    expect(origins.api).toBe('http://192.168.1.10:8000');
    expect(origins.ws).toBe('ws://192.168.1.10:8000');
    expect(origins.speechWs).toBe('ws://192.168.1.10:8010');
  });

  test('переопределяется каждый адрес по отдельности', () => {
    const origins = resolveOrigins({ VITE_API_URL: 'http://gateway.local:8000' }, https);

    expect(origins.api).toBe('http://gateway.local:8000');
    expect(origins.scenario).toBe('https://demo.trycloudflare.com/scenario');
  });

  test('пустая строка — это «не задано», а не адрес', () => {
    // docker-compose подставляет пустое значение, если переменной нет в .env;
    // без этого получился бы запрос к «/sessions» от пустой базы.
    const origins = resolveOrigins({ VITE_API_URL: '', VITE_WS_URL: '   ' }, https);

    expect(origins.api).toBe('https://demo.trycloudflare.com/api');
    expect(origins.ws).toBe('wss://demo.trycloudflare.com');
  });

  test('хвостовой слэш не удваивается при склейке пути', () => {
    const origins = resolveOrigins({ VITE_API_URL: 'http://gateway.local:8000/' }, https);

    expect(origins.api).toBe('http://gateway.local:8000');
  });
});
