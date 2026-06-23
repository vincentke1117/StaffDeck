import { ConfigProvider, theme as antdTheme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { getAuthSession } from './api/client';
import ChatWindowPage from './pages/ChatWindowPage';
import EmployeeGalleryPage from './pages/EmployeeGalleryPage';
import LoginPage from './pages/LoginPage';
import SessionListPage from './pages/SessionListPage';
import { useThemeController } from './theme';

function RequireAuth({ children }: { children: JSX.Element }) {
  const location = useLocation();
  const from = `${location.pathname}${location.search}`;
  return getAuthSession() ? children : <Navigate to="/login" replace state={{ from }} />;
}

export default function App() {
  const { effectiveTheme } = useThemeController();
  const isDark = effectiveTheme === 'dark';

  return (
    <ConfigProvider
      locale={zhCN}
      button={{ autoInsertSpace: false }}
      theme={{
        algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: {
          colorPrimary: isDark ? '#e4b976' : '#0f766e',
          borderRadius: 8,
          colorBgBase: isDark ? '#0f172a' : '#fbfaf6',
          colorBgContainer: isDark ? '#111827' : '#ffffff',
          colorBgElevated: isDark ? '#1e293b' : '#ffffff',
          colorFillSecondary: isDark ? 'rgba(148, 163, 184, 0.16)' : '#f5f1eb',
          colorText: isDark ? '#f8fafc' : '#20201d',
          colorTextSecondary: isDark ? '#94a3b8' : '#6d726e',
          colorBorder: isDark ? 'rgba(148, 163, 184, 0.24)' : '#ded7cc',
          fontFamily:
            '"Avenir Next", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", system-ui, sans-serif',
        },
      }}
    >
      <BrowserRouter basename="/chat">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<RequireAuth><SessionListPage /></RequireAuth>} />
          <Route path="/employees" element={<RequireAuth><EmployeeGalleryPage /></RequireAuth>} />
          <Route path="/:sessionId" element={<RequireAuth><ChatWindowPage /></RequireAuth>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}
