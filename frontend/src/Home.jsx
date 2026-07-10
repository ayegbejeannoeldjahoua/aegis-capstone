import React, { useMemo, useState } from "react";
import {
  ChevronRight,
  DollarSign,
  FileText,
  Gavel,
  Heart,
  LayoutDashboard,
  MessageSquare,
  Search,
  Shield,
} from "lucide-react";
import { AegisBadge, AegisButton, AegisLogo, UserMenu } from "./components/figma/AegisPrimitives.jsx";
import {
  contextualGreeting,
  isPlatformAdmin,
  landingSections,
  normalizeLanguage,
  readStoredLanguage,
  writeStoredLanguage,
} from "./homeModel.js";

const CARD_ICONS = {
  chat: MessageSquare,
  dashboard: LayoutDashboard,
  audit: FileText,
  governance: Gavel,
  console: Shield,
  finops: DollarSign,
  values: Heart,
};

const COPY = {
  en: {
    askPlaceholder: "Ask Aegis",
    askButton: "Ask Aegis",
    quickAccess: "Quick Access",
    administration: "Administration",
    signedIn: "Signed in",
    platform: "Platform admin workspace",
    user: "Governed workspace",
    footer: "Policy checked · values-aware · audited",
  },
  fr: {
    askPlaceholder: "Demander à Aegis",
    askButton: "Demander à Aegis",
    quickAccess: "Accès rapide",
    administration: "Administration",
    signedIn: "Connecté",
    platform: "Espace administrateur plateforme",
    user: "Espace gouverné",
    footer: "Vérifié par la politique · valeurs appliquées · audité",
  },
};

function HomeCard({ card, onOpen }) {
  const Icon = CARD_ICONS[card.id] || Shield;
  return (
    <button className="aegis-home-card" onClick={() => onOpen(card.id)} type="button">
      <div className="aegis-home-card-icon"><Icon size={16} /></div>
      <div>
        <h2>{card.title}</h2>
        <p>{card.meta}</p>
      </div>
      <span className="aegis-home-card-cta">{card.cta}<ChevronRight size={12} /></span>
    </button>
  );
}

export default function Home({ profile, claims = {}, onLogout, go }) {
  const [language, setLanguage] = useState(() => readStoredLanguage());
  const [query, setQuery] = useState("");
  const lang = normalizeLanguage(language);
  const copy = COPY[lang] || COPY.en;
  const sections = useMemo(() => landingSections(profile || {}), [profile]);
  const platformAdmin = isPlatformAdmin(profile || {});
  const role = profile?.role || "user";
  const tenant = profile?.tenant_id || "tenant pending";
  const scope = profile?.admin_scope || "none";

  function setLang(next) {
    setLanguage(writeStoredLanguage(next));
  }

  function openCard(id) {
    if (id === "chat") go("chat");
    else if (id === "values") go("console", "values");
    else if (id === "dashboard") go("console", "dashboard");
    else if (id === "audit") go("console", "audit");
    else if (id === "governance") go("console", "governance");
    else if (id === "finops") go("console", "finops");
    else go("console");
  }

  function askAegis(event) {
    event.preventDefault();
    go("chat", query.trim() || null);
  }

  return (
    <div className="home aegis-home">
      <header className="aegis-topbar">
        <div className="aegis-topbar-left">
          <AegisLogo compact />
          <span className="aegis-topbar-section">Home</span>
        </div>
        <div className="aegis-topbar-right">
          <div className="aegis-language-toggle" role="group" aria-label="Language selector">
            <button type="button" className={lang === "en" ? "active" : ""} aria-pressed={lang === "en"} onClick={() => setLang("en")}>EN</button>
            <button type="button" className={lang === "fr" ? "active" : ""} aria-pressed={lang === "fr"} onClick={() => setLang("fr")}>FR</button>
          </div>
          <UserMenu profile={profile} claims={claims} onLogout={onLogout} />
        </div>
      </header>

      <main className="aegis-home-main">
        <section className="aegis-home-hero" aria-labelledby="home-title">
          <div className="aegis-home-hero-copy">
            <div className="aegis-eyebrow">{copy.signedIn}</div>
            <h1 id="home-title">{contextualGreeting(profile || {}, lang, new Date(), claims)}</h1>
            <p>{platformAdmin ? copy.platform : copy.user}</p>
          </div>
          <div className="aegis-profile-panel">
            <div className="aegis-profile-avatar">{(profile?.email || "A").slice(0, 1).toUpperCase()}</div>
            <div>
              <strong>{profile ? profile.email : "user"}</strong>
              <span>{role} · {tenant}</span>
            </div>
            <AegisBadge tone={scope === "platform" ? "blue" : "green"}>{scope}</AegisBadge>
          </div>
        </section>

        <form className="aegis-home-search" onSubmit={askAegis}>
          <Search size={16} />
          <input
            value={query}
            placeholder={copy.askPlaceholder}
            aria-label={copy.askPlaceholder}
            onChange={(event) => setQuery(event.target.value)}
          />
          <AegisButton type="submit">{copy.askButton}</AegisButton>
        </form>

        <section className="aegis-home-section" aria-labelledby="quick-access-title">
          <div className="aegis-home-section-head">
            <h2 id="quick-access-title">{copy.quickAccess}</h2>
          </div>
          <div className="aegis-home-grid">
            {sections.quickAccess.map((card) => <HomeCard key={card.id} card={card} onOpen={openCard} />)}
          </div>
        </section>

        {sections.administration.length > 0 && (
          <section className="aegis-home-section" aria-labelledby="administration-title">
            <div className="aegis-home-section-head">
              <h2 id="administration-title">{copy.administration}</h2>
            </div>
            <div className="aegis-home-grid">
              {sections.administration.map((card) => <HomeCard key={card.id} card={card} onOpen={openCard} />)}
            </div>
          </section>
        )}

        <footer className="aegis-home-footer">
          <span>{copy.footer}</span>
          <span>tenant {tenant}</span>
          <span>role {role}</span>
        </footer>
      </main>
    </div>
  );
}
