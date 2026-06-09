import { ConfigProvider, theme as antdTheme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { getAuthSession } from './api/client';
import ChatWindowPage from './pages/ChatWindowPage';
import LoginPage from './pages/LoginPage';
import SessionListPage from './pages/SessionListPage';
import { useThemeController } from './theme';

function RequireAuth({ children }: { children: JSX.Element }) {
  return getAuthSession() ? children : <Navigate to="/login" replace />;
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
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/chat" element={<RequireAuth><SessionListPage /></RequireAuth>} />
          <Route path="/chat/:sessionId" element={<RequireAuth><ChatWindowPage /></RequireAuth>} />
          <Route path="*" element={<Navigate to="/chat" replace />} />
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}
