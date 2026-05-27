import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { Activity, FlaskConical, PlayCircle, Settings } from "lucide-react";
import { LiveMonitor } from "./pages/LiveMonitor";
import { ExperimentStudio } from "./pages/ExperimentStudio";
import { ReplayAnalyzer } from "./pages/ReplayAnalyzer";
import { SettingsPage } from "./pages/SettingsPage";
import { useT } from "./i18n/context";

export default function App() {
  const { t, lang, setLang } = useT();

  return (
    <BrowserRouter>
      <div className="flex h-screen flex-col bg-slate-100">
        <nav className="flex h-11 shrink-0 items-center gap-1 border-b border-slate-200 bg-white px-4">
          <NavItem to="/" icon={<Activity size={15} />} label={t("nav.liveMonitor")} />
          <NavItem to="/experiments" icon={<FlaskConical size={15} />} label={t("nav.experimentStudio")} />
          <NavItem to="/replay" icon={<PlayCircle size={15} />} label={t("nav.replayAnalyzer")} />
          <NavItem to="/settings" icon={<Settings size={15} />} label={t("nav.settings")} />
          <div className="ml-auto flex items-center gap-3">
            <button
              onClick={() => setLang(lang === "zh" ? "en" : "zh")}
              className="rounded border border-slate-200 px-2 py-0.5 text-xs font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-700"
            >
              {t("lang.switch")}
            </button>
            <span className="text-xs text-slate-400">{t("app.title")}</span>
          </div>
        </nav>
        <div className="min-h-0 flex-1">
          <Routes>
            <Route path="/" element={<LiveMonitor />} />
            <Route path="/experiments" element={<ExperimentStudio />} />
            <Route path="/replay" element={<ReplayAnalyzer />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}

function NavItem({ to, icon, label }: { to: string; icon: React.ReactNode; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-xs font-medium transition ${
          isActive
            ? "bg-teal-50 text-teal-700"
            : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
        }`
      }
    >
      {icon}
      {label}
    </NavLink>
  );
}
