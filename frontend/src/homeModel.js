export const LANGUAGE_STORAGE_KEY = "aegis.language";
export const SUPPORTED_LANGUAGES = ["en", "fr"];
export const USER_MENU_ITEMS = ["Profile", "Customize", "Log out"];
export const LANDING_CARD_ICON_IDS = ["chat", "dashboard", "audit", "governance", "console", "finops", "values"];

const PLATFORM_QUICK_ACCESS = [
  {
    id: "chat",
    title: "AI Assistant (Chat)",
    meta: "governed assistant",
    cta: "Open chat",
  },
  {
    id: "dashboard",
    title: "Dashboard",
    meta: "requests, correctness, latency",
    cta: "View dashboard",
  },
  {
    id: "audit",
    title: "Audit",
    meta: "trace and decision log",
    cta: "Open audit",
  },
];

const PLATFORM_ADMINISTRATION = [
  {
    id: "governance",
    title: "Governance & Policy",
    meta: "capabilities and policy matrix",
    cta: "Open governance",
  },
  {
    id: "console",
    title: "Console",
    meta: "administration workspace",
    cta: "Open console",
  },
  {
    id: "finops",
    title: "FinOps",
    meta: "spend, budgets, denials",
    cta: "View FinOps",
  },
];

const USER_QUICK_ACCESS = [
  {
    id: "chat",
    title: "AI Assistant (Chat)",
    meta: "governed assistant",
    cta: "Open chat",
  },
  {
    id: "values",
    title: "Values",
    meta: "your active values cascade",
    cta: "Open values",
  },
];

export function normalizeLanguage(value) {
  return SUPPORTED_LANGUAGES.includes(value) ? value : "en";
}

export function readStoredLanguage(storage = globalThis.localStorage) {
  try {
    return normalizeLanguage(storage?.getItem(LANGUAGE_STORAGE_KEY));
  } catch (_) {
    return "en";
  }
}

export function writeStoredLanguage(language, storage = globalThis.localStorage) {
  const next = normalizeLanguage(language);
  try {
    storage?.setItem(LANGUAGE_STORAGE_KEY, next);
  } catch (_) {
    // Language persistence is best-effort.
  }
  return next;
}

function titleCase(value) {
  if (!value) return "";
  return String(value)
    .replace(/[._-]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

export function firstNameFromIdentity(profile = {}, claims = {}) {
  const rawName = profile.name || claims.name || claims.given_name || profile.preferred_username || claims.preferred_username;
  if (rawName) {
    const first = String(rawName).trim().split(/\s+/)[0];
    if (first && !first.includes("@")) return titleCase(first);
  }
  const email = profile.email || claims.email || profile.preferred_username || claims.preferred_username;
  if (email && String(email).includes("@")) {
    return titleCase(String(email).split("@")[0]);
  }
  if (rawName) return titleCase(rawName);
  return "there";
}

export function greetingForHour(hour, language = "en") {
  const h = Number(hour);
  const bucket = h >= 5 && h < 12
    ? "morning"
    : h >= 12 && h < 17
      ? "afternoon"
      : h >= 17 && h < 22
        ? "evening"
        : "night";
  const labels = normalizeLanguage(language) === "fr"
    ? {
        morning: "Bonjour",
        afternoon: "Bon après-midi",
        evening: "Bonsoir",
        night: "Bon retour",
      }
    : {
        morning: "Good morning",
        afternoon: "Good afternoon",
        evening: "Good evening",
        night: "Welcome back",
      };
  return labels[bucket];
}

export function contextualGreeting(profile = {}, language = "en", date = new Date(), claims = {}) {
  return `${greetingForHour(date.getHours(), language)}, ${firstNameFromIdentity(profile, claims)}`;
}

export function isPlatformAdmin(profile = {}) {
  return profile?.admin_scope === "platform" || profile?.role === "platform-admin";
}

export function landingSections(profile = {}) {
  if (isPlatformAdmin(profile)) {
    return {
      quickAccess: PLATFORM_QUICK_ACCESS,
      administration: PLATFORM_ADMINISTRATION,
    };
  }
  return {
    quickAccess: USER_QUICK_ACCESS,
    administration: [],
  };
}

export function assistantNavItems(profile = {}) {
  const base = [
    { id: "home", label: "Home", target: "home" },
    { id: "chat", label: "AI Assistant", target: "chat" },
  ];
  const values = { id: "values", label: "Values", target: "values" };

  if (isPlatformAdmin(profile)) {
    return [
      ...base,
      { id: "dashboard", label: "Dashboard", target: "dashboard" },
      { id: "audit", label: "Audit", target: "audit" },
      { id: "governance", label: "Governance & Policy", target: "governance" },
      { id: "console", label: "Console", target: "console" },
      { id: "finops", label: "FinOps", target: "finops" },
      values,
    ];
  }

  if (profile?.admin_scope && profile.admin_scope !== "none") {
    const items = [...base, { id: "dashboard", label: "Dashboard", target: "dashboard" }];
    if (profile?.audit_scope && profile.audit_scope !== "none") {
      items.push({ id: "audit", label: "Audit", target: "audit" });
    }
    if (profile?.can_edit_governance) {
      items.push({ id: "governance", label: "Governance & Policy", target: "governance" });
    }
    if (profile?.can_manage_users || profile?.can_manage_roles || profile?.can_edit_governance) {
      items.push({ id: "console", label: "Console", target: "console" });
    }
    items.push({ id: "finops", label: "FinOps", target: "finops" }, values);
    return items;
  }

  return [...base, values];
}

export function capabilitySummary(profile = {}) {
  const role = profile?.role || "user";
  if (profile?.admin_scope === "platform" || role === "platform-admin") {
    return "Platform admin - platform-wide administrative visibility, organization values management, governance configuration, audit/FinOps access, policy administration.";
  }
  if (role === "tenant-admin") {
    return "Tenant admin - tenant-scoped administration, tenant audit visibility, tenant configuration, cross-tenant data access denied unless explicitly granted.";
  }
  if (role === "lead") {
    return "Lead - own-tenant access, full PII where authorized, team-level governance context, governed retrieval, cross-tenant access denied.";
  }
  if (role === "analyst") {
    return "Analyst - own-tenant access, masked PII, governed retrieval, values read, limited write scope, cross-tenant access denied.";
  }
  if (role === "auditor") {
    return "Auditor - tenant evidence visibility, trace and policy review, no production mutation, cross-tenant data access denied unless explicitly granted.";
  }
  if (role === "approval-reviewer") {
    return "Approval reviewer - tenant approval review, scoped evidence access, proportional approvals, cross-tenant data access denied.";
  }
  return `${titleCase(role)} - governed access under tenant, team, role, and values policy; cross-tenant access denied unless explicitly granted.`;
}
