import { useState } from "react";
import { Database, LockKeyhole } from "lucide-react";

export default function LoginPage({ busy, error, onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  return (
    <main className="auth-page">
      <section className="auth-brand-panel">
        <div className="brand-orbit"><span /><span /><span /></div>
        <p className="kicker">STAR-CENTERED DATA WORKSPACE</p>
        <h1>Target Info Search</h1>
        <p>统一管理恒星信息、文献、大模型总结与时域光变数据。</p>
        <div className="auth-feature"><Database size={18} /> SQLite + warehouse 科学数据底座</div>
      </section>
      <section className="auth-card">
        <LockKeyhole size={30} />
        <div>
          <span className="kicker">SECURE WORKSPACE</span>
          <h2>登录工作台</h2>
          <p>模型 API Key 与 AI 历史仅对当前账号可见。</p>
        </div>
        {error ? <div className="auth-error" role="alert">{error}</div> : null}
        <form onSubmit={(event) => { event.preventDefault(); onLogin({ username, password }); }}>
          <label>用户名<input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></label>
          <label>密码<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
          <button type="submit" disabled={busy}>{busy ? "正在登录…" : "进入工作台"}</button>
        </form>
        <small>首次使用请先运行管理员创建命令。</small>
      </section>
    </main>
  );
}
export function ChangePasswordPage({ busy, error, onChange, onLogout }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  return (
    <main className="auth-page compact-auth-page">
      <section className="auth-card">
        <LockKeyhole size={30} />
        <div><span className="kicker">ACCOUNT SETUP</span><h2>修改临时密码</h2><p>完成后即可进入共享科学工作台。</p></div>
        {error ? <div className="auth-error" role="alert">{error}</div> : null}
        <form onSubmit={(event) => { event.preventDefault(); onChange({ current_password: currentPassword, new_password: newPassword }); }}>
          <label>当前临时密码<input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required /></label>
          <label>新密码（至少 10 个字符）<input type="password" minLength={10} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required /></label>
          <button type="submit" disabled={busy}>{busy ? "正在保存…" : "保存新密码"}</button>
        </form>
        <button type="button" className="ghost-button" onClick={onLogout}>退出登录</button>
      </section>
    </main>
  );
}
