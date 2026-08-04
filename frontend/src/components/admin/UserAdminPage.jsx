import { useCallback, useEffect, useState } from "react";
import { ShieldCheck, UserPlus } from "lucide-react";
import { createUser, listMigrations, listUsers, updateUser } from "../../api";
import ErrorBanner from "../shared/ErrorBanner";

export default function UserAdminPage({ currentUser }) {
  const [users, setUsers] = useState([]);
  const [migrations, setMigrations] = useState([]);
  const [form, setForm] = useState({ username: "", password: "", role: "user", must_change_password: true });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setBusy(true); setError("");
    try {
      const [userResult, migrationResult] = await Promise.all([listUsers(), listMigrations()]);
      setUsers(userResult.users || []); setMigrations(migrationResult.runs || []);
    } catch (caught) { setError(caught.message); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const addUser = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      const result = await createUser({ ...form, password: form.password || null });
      setForm({ username: "", password: "", role: "user", must_change_password: true });
      setMessage(result.temporary_password ? `用户已创建，一次性临时密码：${result.temporary_password}（只显示本次）` : "用户已创建。");
      await load();
    } catch (caught) { setError(caught.message); setBusy(false); }
  };
  const alterUser = async (user, action) => {
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await updateUser(user.id, action);
      if (result.temporary_password) setMessage(`一次性临时密码：${result.temporary_password}（请立即安全交给该用户）`);
      else setMessage(result.user.is_active ? "账号已启用。" : "账号已禁用。");
      await load();
    } catch (caught) { setError(caught.message); setBusy(false); }
  };

  return (
    <section className="workspace-page admin-page">
      <header className="page-intro"><div><span className="kicker">ADMINISTRATION</span><h1>用户与迁移</h1><p>管理本地账号与权限；管理员也无法查看任何用户的模型密钥。</p></div><div className="coverage"><span>LOCAL ACCOUNTS</span><strong>{users.length} 位用户</strong><small>{migrations.length} 条迁移记录</small></div></header>
      <ErrorBanner message={error} />{message ? <div className="dm-message" role="status">{message}</div> : null}
      <div className="admin-grid">
        <form className="panel-card admin-create-form" onSubmit={addUser}>
          <div className="section-heading"><div><span className="kicker">CREATE ACCOUNT</span><h2><UserPlus size={18} />新增用户</h2></div></div>
          <label>用户名<input value={form.username} minLength={3} onChange={(event) => setForm({ ...form, username: event.target.value })} required /></label>
          <label>初始密码（留空自动生成）<input type="password" minLength={10} value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} /></label>
          <label>角色<select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}><option value="user">普通用户</option><option value="admin">管理员</option></select></label>
          <label className="checkbox-row"><input type="checkbox" checked={form.must_change_password} onChange={(event) => setForm({ ...form, must_change_password: event.target.checked })} />首次登录强制改密</label>
          <button type="submit" disabled={busy}>创建账号</button>
        </form>
        <section className="panel-card admin-user-list">
          <div className="section-heading"><div><span className="kicker">ACCESS CONTROL</span><h2><ShieldCheck size={18} />账号列表</h2></div></div>
          {users.map((user) => <article key={user.id} className="admin-user-row"><div className="target-avatar">{user.username.slice(0, 1).toUpperCase()}</div><div><strong>{user.username}</strong><span>{user.role === "admin" ? "管理员" : "普通用户"}{user.must_change_password ? " · 待修改密码" : ""}</span></div><span className={`job-state ${user.is_active ? "complete" : "failed"}`}>{user.is_active ? "启用" : "禁用"}</span><div className="admin-user-actions"><button className="ghost-button" onClick={() => alterUser(user, { reset_password: true })} disabled={busy}>重置密码</button>{user.id !== currentUser.id ? <button className={user.is_active ? "danger-button" : "ghost-button"} onClick={() => alterUser(user, { is_active: !user.is_active })} disabled={busy}>{user.is_active ? "禁用" : "启用"}</button> : null}</div></article>)}
        </section>
      </div>
      <section className="panel-card migration-status"><div className="section-heading"><div><span className="kicker">WAREHOUSE MIGRATION</span><h2>迁移记录</h2></div><small>迁移只能通过 CLI 发起</small></div>{migrations.length ? migrations.map((run) => <div key={run.migration_id} className="migration-row"><span className={`job-state ${run.status}`}>{run.status}</span><strong>{run.mode}</strong><span>{new Date(run.started_at).toLocaleString()}</span><code>{run.report_path || "—"}</code></div>) : <p className="muted-text">尚未执行旧数据迁移。</p>}</section>
    </section>
  );
}
