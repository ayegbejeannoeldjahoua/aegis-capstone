import React, { useEffect, useState } from "react";
import { logout } from "./auth/keycloak.js";
import { fetchMe, getProfile } from "./api/client.js";
import Home from "./Home.jsx";
import Console from "./Console.jsx";
import Chat from "./pages/Chat.jsx";

export default function App() {
  const [profile, setProfile] = useState(null);
  const [view, setView] = useState("home");

  useEffect(() => { fetchMe().then(setProfile).catch(() => setProfile(getProfile())); }, []);

  if (view === "console") return <Console onHome={() => setView("home")} />;
  if (view === "chat") return <Chat profile={profile} onHome={() => setView("home")} />;
  return <Home profile={profile} onLogout={logout} go={setView} />;
}
