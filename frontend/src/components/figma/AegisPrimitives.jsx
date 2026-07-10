import React from "react";
import { ArrowLeft, ChevronDown, LogOut, SlidersHorizontal, User, X } from "lucide-react";
import ThemeToggle from "../../theme/ThemeToggle.jsx";
import { useTheme } from "../../theme/useTheme.js";
import {
  capabilitySummary,
  firstNameFromIdentity,
  normalizeLanguage,
  readStoredLanguage,
  writeStoredLanguage,
} from "../../homeModel.js";

export function cx(...classes) {
  return classes.filter(Boolean).join(" ");
}

export function AegisLogo({ compact = false }) {
  return (
    <div className={cx("aegis-logo", compact && "compact")}>
      <div className="aegis-logo-mark">A</div>
      <div className="aegis-logo-copy">
        <span>Aegis</span>
        {!compact && <small>AI Governance Platform</small>}
      </div>
    </div>
  );
}

export function AegisBadge({ children, tone = "blue", className = "" }) {
  return <span className={cx("aegis-badge", `tone-${tone}`, className)}>{children}</span>;
}

export function AegisButton({
  children,
  variant = "primary",
  icon: Icon,
  className = "",
  ...props
}) {
  return (
    <button className={cx("aegis-button", `variant-${variant}`, className)} {...props}>
      {Icon && <Icon size={13} />}
      {children}
    </button>
  );
}

export function AegisCard({ children, className = "", as: Component = "section" }) {
  return <Component className={cx("aegis-card", className)}>{children}</Component>;
}

export function PageHeader({ eyebrow, title, description, actions, meta }) {
  return (
    <div className="aegis-page-header">
      <div>
        {eyebrow && <div className="aegis-eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {(actions || meta) && (
        <div className="aegis-page-actions">
          {meta}
          {actions}
        </div>
      )}
    </div>
  );
}

export function EmptyPanel({ icon: Icon, title, children, action }) {
  return (
    <div className="aegis-empty-panel">
      {Icon && (
        <div className="aegis-empty-icon">
          <Icon size={18} />
        </div>
      )}
      <h2>{title}</h2>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

function ProfilePanel({ profile = {}, claims = {}, onClose }) {
  const email = profile?.email || claims.email || "unknown";
  const tenant = profile?.tenant_id || claims.tenant_id || "not assigned";
  const team = profile?.team_id || claims.team_id || "not assigned";
  const role = profile?.role || claims.role || "not assigned";

  return (
    <div className="aegis-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="aegis-modal-panel" role="dialog" aria-modal="true" aria-labelledby="profile-panel-title" onMouseDown={(e) => e.stopPropagation()}>
        <div className="aegis-modal-head">
          <div>
            <div className="aegis-eyebrow">Profile</div>
            <h2 id="profile-panel-title">{firstNameFromIdentity(profile, claims)}</h2>
          </div>
          <button className="aegis-icon-button" type="button" aria-label="Close profile" onClick={onClose}>
            <X size={14} />
          </button>
        </div>
        <dl className="aegis-profile-details">
          <div><dt>Email</dt><dd>{email}</dd></div>
          <div><dt>Tenant</dt><dd>{tenant}</dd></div>
          <div><dt>Team</dt><dd>{team}</dd></div>
          <div><dt>Role</dt><dd>{role}</dd></div>
        </dl>
        <div className="aegis-capability-line">
          <span>Capability matrix</span>
          <p>{capabilitySummary(profile)}</p>
        </div>
      </section>
    </div>
  );
}

function CustomizePanel({ onClose }) {
  const { theme } = useTheme();
  const label = theme === "light" ? "Light / Bright" : "Dark";

  return (
    <div className="aegis-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="aegis-modal-panel" role="dialog" aria-modal="true" aria-labelledby="customize-panel-title" onMouseDown={(e) => e.stopPropagation()}>
        <div className="aegis-modal-head">
          <div>
            <div className="aegis-eyebrow">Customize</div>
            <h2 id="customize-panel-title">Customize your workspace</h2>
          </div>
          <button className="aegis-icon-button" type="button" aria-label="Close customize" onClick={onClose}>
            <X size={14} />
          </button>
        </div>
        <div className="aegis-customize-section">
          <div>
            <h3>Appearance</h3>
            <p>Current theme: {label}</p>
          </div>
          <ThemeToggle />
        </div>
      </section>
    </div>
  );
}

export function UserMenu({ profile, claims = {}, onLogout }) {
  const [open, setOpen] = React.useState(false);
  const [panel, setPanel] = React.useState(null);
  const name = firstNameFromIdentity(profile || {}, claims);
  const email = profile?.email || claims.email || "user";

  function openPanel(nextPanel) {
    setOpen(false);
    setPanel(nextPanel);
  }

  return (
    <div className="aegis-user-menu">
      <button
        type="button"
        className="aegis-user-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="aegis-user-trigger-avatar"><User size={13} /></span>
        <span className="aegis-user-trigger-copy">
          <strong>{name}</strong>
          <small>{email}</small>
        </span>
        <ChevronDown size={13} />
      </button>
      {open && (
        <div className="aegis-user-dropdown" role="menu">
          <button type="button" role="menuitem" onClick={() => openPanel("profile")}>
            <User size={13} />
            <span>Profile</span>
          </button>
          <button type="button" role="menuitem" onClick={() => openPanel("customize")}>
            <SlidersHorizontal size={13} />
            <span>Customize</span>
          </button>
          <button type="button" role="menuitem" onClick={onLogout}>
            <LogOut size={13} />
            <span>Log out</span>
          </button>
        </div>
      )}
      {panel === "profile" && <ProfilePanel profile={profile || {}} claims={claims} onClose={() => setPanel(null)} />}
      {panel === "customize" && <CustomizePanel onClose={() => setPanel(null)} />}
    </div>
  );
}

function TopBarLanguageToggle() {
  const [language, setLanguage] = React.useState(() => readStoredLanguage());
  const lang = normalizeLanguage(language);

  function setLang(next) {
    setLanguage(writeStoredLanguage(next));
  }

  return (
    <div className="aegis-language-toggle" role="group" aria-label="Language selector">
      <button type="button" className={lang === "en" ? "active" : ""} aria-pressed={lang === "en"} onClick={() => setLang("en")}>EN</button>
      <button type="button" className={lang === "fr" ? "active" : ""} aria-pressed={lang === "fr"} onClick={() => setLang("fr")}>FR</button>
    </div>
  );
}

export function ShellTopBar({ onBack, onLogout, profile, claims = {}, section }) {
  return (
    <header className="aegis-topbar">
      <div className="aegis-topbar-left">
        {onBack && (
          <AegisButton variant="ghost" icon={ArrowLeft} onClick={onBack}>
            Home
          </AegisButton>
        )}
        <AegisLogo compact />
        {section && <span className="aegis-topbar-section">{section}</span>}
      </div>
      <div className="aegis-topbar-right">
        <TopBarLanguageToggle />
        <UserMenu profile={profile} claims={claims} onLogout={onLogout} />
      </div>
    </header>
  );
}
