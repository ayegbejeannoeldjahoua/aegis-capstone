import React, { useState } from "react";
import { api } from "../api/client.js";

export default function Account() {
  const [cur, setCur] = useState("");
  const [nw, setNw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setErr(""); setMsg("");
    if (nw !== confirm) { setErr("New passwords do not match."); return; }
    if (nw.length < 8) { setErr("New password must be at least 8 characters."); return; }
    if (nw === cur) { setErr("New password must differ from the current one."); return; }
    setBusy(true);
    try {
      await api("/v1/me/password", { method: "POST", body: { current_password: cur, new_password: nw } });
      setMsg("Password updated.");
      setCur(""); setNw(""); setConfirm("");
    } catch (e) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  }

  return (
    <div className="card" style={{ maxWidth: 480 }}>
      <h2>Change password</h2>
      {err && <div className="error">{err}</div>}
      {msg && <div className="ok-msg">{msg}</div>}
      <form onSubmit={submit}>
        <label>Current password
          <input type="password" value={cur} required autoComplete="current-password"
                 onChange={(e) => setCur(e.target.value)} />
        </label>
        <label>New password
          <input type="password" value={nw} required autoComplete="new-password"
                 onChange={(e) => setNw(e.target.value)} />
        </label>
        <label>Confirm new password
          <input type="password" value={confirm} required autoComplete="new-password"
                 onChange={(e) => setConfirm(e.target.value)} />
        </label>
        <button type="submit" disabled={busy}>{busy ? "Updating…" : "Update password"}</button>
      </form>
      <small>You’ll be asked for your current password to confirm it’s you.</small>
    </div>
  );
}
