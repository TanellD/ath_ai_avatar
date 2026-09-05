import { Link, Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom';

import { AdminSessionDetail } from '@/pages/AdminSessionDetail';
import { AdminSessions } from '@/pages/AdminSessions';
import { AvatarLab } from '@/pages/AvatarLab';
import { EmotionLab } from '@/pages/EmotionLab';
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
 * основной навигации и живёт отдельной ссылкой.
 *
 * Авторизации нет: §4 выводит её из скоупа. Роль определяется маршрутом.
 *
 * Шапка (логотип + переключатель разделов) скрыта на экране сессии
 * (/session/:id) — там свой полноэкранный хедер из макета
 * front/Экран сотрудника.dc.html (см. TraineeSession.tsx), второй сверху
 * был бы просто дублирующим шумом.
 */
const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `app__nav-link${isActive ? ' app__nav-link--active' : ''}`;

/** Отладочные инструменты — приглушены, чтобы не спорить с ролевыми разделами. */
const mutedLinkClass = ({ isActive }: { isActive: boolean }) =>
  `app__nav-link app__nav-link--muted${isActive ? ' app__nav-link--active' : ''}`;

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
            <NavLink to="/scenarios" className={navLinkClass}>
              Сценарии
            </NavLink>
            <NavLink to="/sessions" className={navLinkClass}>
              Тренировки
            </NavLink>
            <NavLink to="/emotion-lab" className={mutedLinkClass}>
              Эмоции
            </NavLink>
            <NavLink to="/avatar-lab" className={mutedLinkClass}>
              Модели
            </NavLink>
            <NavLink to="/admin/sessions" className={mutedLinkClass}>
              Админ-панель
            </NavLink>
          </nav>
        </header>
      )}

      <div className="app__body">
        <Routes>
          <Route path="/" element={<Navigate to="/scenarios" replace />} />
          <Route path="/scenarios" element={<MethodistScenarios />} />
          <Route path="/sessions" element={<MethodistSessions />} />
          <Route path="/session/:scenarioId" element={<TraineeSession />} />
          <Route path="/emotion-lab" element={<EmotionLab />} />
          <Route path="/avatar-lab" element={<AvatarLab />} />
          <Route path="/report/:sessionId" element={<MethodistReport />} />
          <Route path="/admin/sessions" element={<AdminSessions />} />
          <Route path="/admin/sessions/:sessionId" element={<AdminSessionDetail />} />
          <Route path="*" element={<p className="page">Страница не найдена</p>} />
        </Routes>
      </div>
    </div>
  );
}
