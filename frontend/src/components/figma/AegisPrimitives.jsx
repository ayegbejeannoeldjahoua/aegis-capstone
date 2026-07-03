import React from "react";
import { ArrowLeft, LogOut } from "lucide-react";
import ThemeToggle from "../../theme/ThemeToggle.jsx";

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

export function ShellTopBar({ onBack, onLogout, profile, claims = {}, section }) {
  const email = profile?.email || claims.email || "user";
  const role = profile?.role || claims.role;
  const scope = profile?.admin_scope || profile?.tenant_id || claims.tenant_id;

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
        <ThemeToggle />
        <span className="aegis-user-email">{email}</span>
        {role && (
          <AegisBadge>
            {role}
            {scope ? <span>{scope}</span> : null}
          </AegisBadge>
        )}
        {onLogout && (
          <AegisButton variant="ghost" icon={LogOut} onClick={onLogout}>
            Log out
          </AegisButton>
        )}
      </div>
    </header>
  );
}
