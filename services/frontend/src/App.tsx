import { Link, Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom';

import { AdminSessionDetail } from '@/pages/AdminSessionDetail';
import { AdminSessions } from '@/pages/AdminSessions';
import { MethodistReport } from '@/pages/MethodistReport';
import { MethodistScenarios } from '@/pages/MethodistScenarios';
import { MethodistSessions } from '@/pages/MethodistSessions';
import { TraineeSession } from '@/pages/TraineeSession';

/**
 * Две роли по постановке (Claude.md §2): методист и сотрудник.
 * Отдельной роли администратора нет — в кейсе её нет.
 *
 * `/admin/*` — не третья роль продукта, а инструмент отладки конвейера
 * (путь сессии + Gantt операций из app/tracing.py), поэтому вынесен из
 * сайдбара методиста и живёт отдельной приглушённой ссылкой снизу.
 *
 * Сайдбар — по макету front/Дашборд методиста.dc.html. Из макета не
 * воспроизведены: вкладка «Обзор» (агрегированная аналитика — в макете это
 * нарисованные числа, реального эндпоинта под них нет, а рисовать вымышленную
 * статистику в интерфейсе, который сам продаётся на «каждый балл проверяем за
 * 10 секунд», было бы прямым нарушением этого же принципа) и блок
 * «Команда»/карточка методиста (авторизации нет — §4, значит и личности
 * методиста в интерфейсе взяться неоткуда).
 *
 * Экран сессии (/session/:id) — без сайдбара: там свой полноэкранный хедер
 * из макета front/Экран сотрудника.dc.html (см. TraineeSession.tsx).
 */
export function App() {
  const location = useLocation();
  const isSession = location.pathname.startsWith('/session/');

  if (isSession) {
    return (
      <div className="app app--fullbleed">
        <Routes>
          <Route path="/session/:scenarioId" element={<TraineeSession />} />
        </Routes>
      </div>
    );
  }

  return (
    <div className="app app--shell">
      <aside className="sidebar">
        <Link to="/scenarios" className="app__brand sidebar__brand">
          <span className="app__brand-mark">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="m12 3.4 1.9 6 6 1.9-6 1.9-1.9 6-1.9-6-6-1.9 6-1.9Z" />
            </svg>
          </span>
          <span>
            Тренажёр
            <small>Кабинет методиста</small>
          </span>
        </Link>

        <div className="side-label">Обучение</div>
        <nav className="sidebar__nav">
          <NavLink to="/scenarios" className={({ isActive }) => `sidebar__link${isActive ? ' sidebar__link--active' : ''}`}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="m12 3.6 8.4 4.4-8.4 4.4-8.4-4.4Z" />
              <path d="m3.6 12.4 8.4 4.4 8.4-4.4" />
            </svg>
            Сценарии
          </NavLink>
          <NavLink to="/sessions" className={({ isActive }) => `sidebar__link${isActive ? ' sidebar__link--active' : ''}`}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3.6" y="3.6" width="7" height="7" rx="2.2" />
              <rect x="13.4" y="3.6" width="7" height="7" rx="2.2" />
              <rect x="3.6" y="13.4" width="7" height="7" rx="2.2" />
              <rect x="13.4" y="13.4" width="7" height="7" rx="2.2" />
            </svg>
            Сессии
          </NavLink>
        </nav>

        <NavLink to="/admin/sessions" className="sidebar__debug-link">
          Админ-панель (отладка)
        </NavLink>
      </aside>

      <div className="app__body">
        <Routes>
          <Route path="/" element={<Navigate to="/scenarios" replace />} />
          <Route path="/scenarios" element={<MethodistScenarios />} />
          <Route path="/sessions" element={<MethodistSessions />} />
          <Route path="/report/:sessionId" element={<MethodistReport />} />
          <Route path="/admin/sessions" element={<AdminSessions />} />
          <Route path="/admin/sessions/:sessionId" element={<AdminSessionDetail />} />
          <Route path="*" element={<p className="page">Страница не найдена</p>} />
        </Routes>
      </div>
    </div>
  );
}
