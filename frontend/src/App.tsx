import { Routes, Route, Navigate } from "react-router-dom";
import TikTokProfile from "./pages/TikTokProfile";
import Accounts from "./pages/Accounts";
import AccountDetail from "./pages/AccountDetail";
import ProfilesPage from "./pages/Profiles";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Accounts />} />
      <Route path="/accounts" element={<Navigate to="/" replace />} />
      <Route path="/analytics" element={<Accounts initialTab="analytics" />} />
      <Route path="/accounts/:id" element={<AccountDetail />} />
      <Route path="/profiles" element={<ProfilesPage />} />
      <Route path="/tiktok/:username" element={<TikTokProfile />} />
      <Route path="/settings" element={<Settings />} />
    </Routes>
  );
}
