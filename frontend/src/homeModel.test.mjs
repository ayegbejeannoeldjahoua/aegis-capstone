import assert from "node:assert/strict";

import {
  USER_MENU_ITEMS,
  capabilitySummary,
  contextualGreeting,
  firstNameFromIdentity,
  greetingForHour,
  landingSections,
} from "./homeModel.js";

const jane = { email: "jane@acmecp.example", tenant_id: "tenant-acmecp", team_id: "research", role: "analyst", admin_scope: "none" };
const kim = { email: "kim@acmecp.example", tenant_id: "tenant-acmecp", team_id: "research", role: "lead", admin_scope: "none" };
const priya = { email: "priya@it.example", tenant_id: "tenant-it", team_id: "platform", role: "platform-admin", admin_scope: "platform" };

assert.equal(greetingForHour(5), "Good morning");
assert.equal(greetingForHour(11), "Good morning");
assert.equal(greetingForHour(12), "Good afternoon");
assert.equal(greetingForHour(16), "Good afternoon");
assert.equal(greetingForHour(17), "Good evening");
assert.equal(greetingForHour(21), "Good evening");
assert.equal(greetingForHour(22), "Welcome back");
assert.equal(greetingForHour(3), "Welcome back");
assert.equal(greetingForHour(13, "fr"), "Bon après-midi");

assert.equal(firstNameFromIdentity(jane), "Jane");
assert.equal(firstNameFromIdentity(kim), "Kim");
assert.equal(firstNameFromIdentity(priya), "Priya");
assert.equal(firstNameFromIdentity({ email: "alex@example.com" }), "Alex");
assert.equal(firstNameFromIdentity({}), "there");

assert.equal(contextualGreeting(jane, "en", new Date("2026-07-10T09:00:00")), "Good morning, Jane");
assert.equal(contextualGreeting(kim, "en", new Date("2026-07-10T14:00:00")), "Good afternoon, Kim");
assert.equal(contextualGreeting(priya, "en", new Date("2026-07-10T19:00:00")), "Good evening, Priya");
assert.notEqual(contextualGreeting(kim, "en", new Date("2026-07-10T14:00:00")), "Good afternoon, Jane");

assert.deepEqual(USER_MENU_ITEMS, ["Profile", "Customize", "Log out"]);
assert.equal(USER_MENU_ITEMS.includes("Admin settings"), false);

assert.deepEqual(
  landingSections(priya).quickAccess.map((card) => card.title),
  ["AI Assistant (Chat)", "Dashboard", "Audit"],
);
assert.deepEqual(
  landingSections(priya).administration.map((card) => card.title),
  ["Governance & Policy", "Console", "FinOps"],
);
assert.deepEqual(
  landingSections(jane).quickAccess.map((card) => card.title),
  ["AI Assistant (Chat)", "Values"],
);
assert.deepEqual(landingSections(jane).administration, []);

assert.match(capabilitySummary(jane), /masked PII/);
assert.match(capabilitySummary(kim), /full PII where authorized/);
assert.match(capabilitySummary({ role: "tenant-admin", admin_scope: "tenant" }), /tenant-scoped administration/);
assert.match(capabilitySummary(priya), /platform-wide administrative visibility/);
