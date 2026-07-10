import React, { useEffect, useState } from "react";
import { keycloak, logout } from "./auth/keycloak.js";
import { fetchMe, getProfile } from "./api/client.js";
import Home from "./Home.jsx";
import Console from "./Console.jsx";
import Chat from "./pages/Chat.jsx";

export default function App() {
  const [profile, setProfile] = useState(null);
  const [view, setView] = useState("home");
  const [consoleInitialTab, setConsoleInitialTab] = useState(null);

  useEffect(() => { fetchMe().then(setProfile).catch(() => setProfile(getProfile())); }, []);

  function go(nextView, initialTab = null) {
    setConsoleInitialTab(nextView === "console" ? initialTab : null);
    setView(nextView);
  }

  const claims = keycloak.tokenParsed || {};

  if (view === "console") return <Console onHome={() => setView("home")} initialTab={consoleInitialTab} />;
  if (view === "chat") return <Chat profile={profile} claims={claims} onHome={() => setView("home")} onLogout={logout} go={go} />;
  return <Home profile={profile} claims={claims} onLogout={logout} go={go} />;
}
