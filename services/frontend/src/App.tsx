import { Link, Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom';

import { AdminSessionDetail } from '@/pages/AdminSessionDetail';
import { AdminSessions } from '@/pages/AdminSessions';
import { MethodistReport } from '@/pages/MethodistReport';
import { MethodistScenarios } from '@/pages/MethodistScenarios';
import { TraineeSession } from '@/pages/TraineeSession';

/**
 * Две роли по постановке (Claude.md §2): методист и сотрудник.
 * Отдельной роли администратора нет — в кейсе её нет.
 *
 * `/admin/*` — не третья роль продукта, а инструмент отладки конвейера
 * (путь сессии + Gantt операций из app/tracing.py), поэтому вынесен из
 * основной навигации и живёт отдельной ссылкой.
 *
 * Авторизации нет: §4 выводит её из скоупа. Роль определяется маршрутом.
 *
 * Шапка (логотип + переключатель разделов) скрыта на экране сессии
 * (/session/:id) — там свой полноэкранный хедер из макета
 * front/Экран сотрудника.dc.html (см. TraineeSession.tsx), второй сверху
 * был бы просто дублирующим шумом.
 */
export function App() {
  const location = useLocation();
  const isSession = location.pathname.startsWith('/session/');

  return (
    <div className="app">
      {!isSession && (
        <header className="app__nav">
          <Link to="/scenarios" className="app__brand">
            <span className="app__brand-mark">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="m12 3.4 1.9 6 6 1.9-6 1.9-1.9 6-1.9-6-6-1.9 6-1.9Z" />
              </svg>
            </span>
            Тренажёр
          </Link>
          <nav className="app__nav-links">
            <NavLink to="/scenarios" className={({ isActive }) => `app__nav-link${isActive ? ' app__nav-link--active' : ''}`}>
              Сценарии
            </NavLink>
            <NavLink
              to="/admin/sessions"
              className={({ isActive }) => `app__nav-link app__nav-link--muted${isActive ? ' app__nav-link--active' : ''}`}
            >
              Админ-панель
            </NavLink>
          </nav>
        </header>
      )}

      <div className="app__body">
        <Routes>
          <Route path="/" element={<Navigate to="/scenarios" replace />} />
          <Route path="/scenarios" element={<MethodistScenarios />} />
          <Route path="/session/:scenarioId" element={<TraineeSession />} />
          <Route path="/report/:sessionId" element={<MethodistReport />} />
          <Route path="/admin/sessions" element={<AdminSessions />} />
          <Route path="/admin/sessions/:sessionId" element={<AdminSessionDetail />} />
          <Route path="*" element={<p className="page">Страница не найдена</p>} />
        </Routes>
      </div>
    </div>
  );
}
