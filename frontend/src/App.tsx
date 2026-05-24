import { useEffect } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { CommandPalette } from "./components/common/CommandPalette";
import { useGlobalShortcuts } from "./hooks/useShortcuts";
import { useAuth } from "./store/auth";
import { useUi } from "./store/ui";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Inbox from "./pages/Inbox";
import Review from "./pages/Review";
import Upload from "./pages/Upload";
import Onboarding from "./pages/Onboarding";
import SettingsOrganizations from "./pages/Settings/Organizations";
import SettingsMailboxes from "./pages/Settings/Mailboxes";
import SettingsProviders from "./pages/Settings/Providers";
import SettingsClients from "./pages/Settings/Clients";
import SettingsConnectors from "./pages/Settings/Connectors";
import SettingsCloudInbox from "./pages/Settings/CloudInbox";
import SettingsSyncInspector from "./pages/Settings/SyncInspector";
import SettingsAccount from "./pages/Settings/Account";
import SettingsUsers from "./pages/Settings/Users";
import SettingsRouting from "./pages/Settings/Routing";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const user = useAuth((s) => s.user);
  const hydrate = useAuth((s) => s.hydrate);
  useEffect(() => { hydrate(); }, [hydrate]);
  if (user === undefined) return null; // still hydrating
  if (user === null) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  const navigate = useNavigate();
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);

  useGlobalShortcuts({
    onOpenPalette: () => setPaletteOpen(true),
    onGoInbox: () => navigate("/inbox"),
    onGoDashboard: () => navigate("/"),
    onGoReview: () => navigate("/review"),
    onGoSettings: () => navigate("/settings/organizations"),
    onGoUpload: () => navigate("/upload"),
  });

  return (
    <>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<RequireAuth><AppShell /></RequireAuth>}>
          <Route index element={<Dashboard />} />
          <Route path="inbox" element={<Inbox />} />
          <Route path="review" element={<Review />} />
          <Route path="upload" element={<Upload />} />
          <Route path="onboarding" element={<Onboarding />} />
          <Route path="settings" element={<Navigate to="organizations" replace />} />
          <Route path="settings/organizations" element={<SettingsOrganizations />} />
          <Route path="settings/mailboxes" element={<SettingsMailboxes />} />
          <Route path="settings/providers" element={<SettingsProviders />} />
          <Route path="settings/clients" element={<SettingsClients />} />
          <Route path="settings/connectors" element={<SettingsConnectors />} />
          <Route path="settings/cloud-inbox" element={<SettingsCloudInbox />} />
          <Route path="settings/sync-inspector" element={<SettingsSyncInspector />} />
          <Route path="settings/routing" element={<SettingsRouting />} />
          <Route path="settings/users" element={<SettingsUsers />} />
          <Route path="settings/account" element={<SettingsAccount />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
      <CommandPalette />
    </>
  );
}
