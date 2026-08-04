import { useCallback, useEffect, useMemo, useState } from "react";
import { Bot, CheckCircle2, KeyRound, Plus, RefreshCw, Trash2 } from "lucide-react";
import {
  createLlmProfile,
  deleteLlmProfile,
  listLlmProfiles,
  listLlmRuns,
  testLlmProfile,
  updateLlmProfile,
} from "../../api";
import ErrorBanner from "../shared/ErrorBanner";
import EmptyState from "../shared/EmptyState";

const EMPTY_FORM = {
  name: "", provider: "deepseek", base_url: "https://api.deepseek.com/v1",
  model: "deepseek-chat", api_key: "", timeout_sec: 45,
  is_default: true, is_enabled: true,
};

export default function LlmPluginPage() {
  const [profiles, setProfiles] = useState([]);
  const [presets, setPresets] = useState([]);
  const [runs, setRuns] = useState([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editingId, setEditingId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setBusy(true); setError("");
    try {
      const [profileResult, runResult] = await Promise.all([listLlmProfiles(), listLlmRuns({ limit: 100 })]);
      setProfiles(profileResult.profiles || []);
      setPresets(profileResult.presets || []);
      setRuns(runResult.runs || []);
    } catch (caught) { setError(caught.message); }
    finally { setBusy(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const selectedPreset = useMemo(
    () => presets.find((item) => item.id === form.provider), [presets, form.provider]
  );

  const reset = () => { setEditingId(null); setForm(EMPTY_FORM); };
  const edit = (profile) => {
    setEditingId(profile.id);
    setForm({ ...profile, api_key: "" });
    setMessage("");
  };

  const save = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      if (editingId) await updateLlmProfile(editingId, form);
      else await createLlmProfile(form);
      setMessage(editingId ? "模型配置已更新。" : "模型配置已创建。");
      reset(); await load();
    } catch (caught) { setError(caught.message); setBusy(false); }
  };

  const test = async (profile) => {
    setBusy(true); setError(""); setMessage("正在执行一次最小模型调用…");
    try {
      const result = await testLlmProfile(profile.id);
      setMessage(`连接成功，延迟 ${result.latency_ms} ms，响应：${result.reply}`);
    } catch (caught) { setError(caught.message); setMessage(""); }
    finally { setBusy(false); }
  };

  const remove = async (profile) => {
    if (!window.confirm(`确认删除模型配置「${profile.name}」？`)) return;
    setBusy(true); setError("");
    try { await deleteLlmProfile(profile.id); await load(); }
    catch (caught) { setError(caught.message); setBusy(false); }
  };

  return (
    <section className="workspace-page llm-plugin-page">
      <header className="page-intro">
        <div><span className="kicker">PRIVATE PLUGIN · OPENAI COMPATIBLE</span><h1>大模型接口</h1><p>配置仅属于当前账号的 DeepSeek、OpenAI 或自定义兼容端点；密钥加密保存在后端。</p></div>
        <div className="coverage"><span>PRIVATE PROFILES</span><strong>{profiles.length} 个配置</strong><small>{runs.length} 次历史运行</small></div>
      </header>
      <ErrorBanner message={error} />
      {message ? <div className="dm-message" role="status">{message}</div> : null}
      <div className="llm-plugin-grid">
        <section className="panel-card llm-profile-list">
          <div className="section-heading"><div><span className="kicker">CONNECTIONS</span><h2>我的模型配置</h2></div><button className="ghost-button" onClick={reset}><Plus size={15} />新增</button></div>
          {profiles.length ? profiles.map((profile) => (
            <article key={profile.id} className={profile.is_default ? "llm-profile active" : "llm-profile"}>
              <div className="llm-profile-icon"><Bot size={18} /></div>
              <div><strong>{profile.name}</strong><span>{profile.provider} · {profile.model}</span><small>{profile.base_url} · Key ••••{profile.api_key_suffix}</small></div>
              <div className="llm-profile-actions">
                {profile.is_default ? <span className="dm-badge"><CheckCircle2 size={12} />默认</span> : null}
                <button className="ghost-button" onClick={() => edit(profile)}>编辑</button>
                <button className="ghost-button" onClick={() => test(profile)} disabled={busy}>测试</button>
                <button className="icon-button danger-button" aria-label="删除配置" onClick={() => remove(profile)}><Trash2 size={14} /></button>
              </div>
            </article>
          )) : <EmptyState icon={<KeyRound size={42} />} title="尚无模型配置" description="创建配置后即可在目标摘要和文献调研中使用。" />}
        </section>

        <form className="panel-card llm-profile-form" onSubmit={save}>
          <div className="section-heading"><div><span className="kicker">{editingId ? "EDIT PROFILE" : "NEW PROFILE"}</span><h2>{editingId ? "编辑配置" : "添加接口"}</h2></div></div>
          <label>配置名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：我的 DeepSeek" required /></label>
          <label>接口预设<select value={form.provider} onChange={(event) => {
            const preset = presets.find((item) => item.id === event.target.value);
            setForm({ ...form, provider: event.target.value, base_url: preset?.base_url || "", model: preset?.suggested_model || "" });
          }}>{presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.label}</option>)}</select></label>
          <label>Base URL<input value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} placeholder={selectedPreset?.base_url} required /></label>
          <label>模型<input value={form.model} onChange={(event) => setForm({ ...form, model: event.target.value })} placeholder="输入接口支持的模型名称" required /></label>
          <label>API Key<input type="password" autoComplete="new-password" value={form.api_key || ""} onChange={(event) => setForm({ ...form, api_key: event.target.value })} placeholder={editingId ? "留空则保持现有密钥" : "sk-…"} required={!editingId} /></label>
          <label>超时（秒）<input type="number" min={5} max={300} value={form.timeout_sec} onChange={(event) => setForm({ ...form, timeout_sec: Number(event.target.value) })} /></label>
          <label className="checkbox-row"><input type="checkbox" checked={form.is_default} onChange={(event) => setForm({ ...form, is_default: event.target.checked })} />设为默认配置</label>
          <label className="checkbox-row"><input type="checkbox" checked={form.is_enabled} onChange={(event) => setForm({ ...form, is_enabled: event.target.checked })} />启用此配置</label>
          <div className="form-actions"><button type="submit" disabled={busy}>{busy ? "保存中…" : "保存配置"}</button>{editingId ? <button type="button" className="ghost-button" onClick={reset}>取消</button> : null}</div>
        </form>
      </div>

      <section className="panel-card llm-run-history">
        <div className="section-heading"><div><span className="kicker">PRIVATE PROVENANCE</span><h2>我的 AI 运行历史</h2></div><button className="ghost-button" onClick={load} disabled={busy}><RefreshCw size={15} />刷新</button></div>
        {runs.length ? <div className="table-scroll"><table><thead><tr><th>时间</th><th>目标</th><th>任务</th><th>模型</th><th>状态</th></tr></thead><tbody>{runs.map((run) => <tr key={run.id}><td>{new Date(run.created_at).toLocaleString()}</td><td><strong>{run.target}</strong></td><td>{run.task_type === "target_summary" ? "目标总结" : "文献调研"}</td><td>{run.profile?.name} · {run.profile?.model}</td><td><span className={`job-state ${run.status}`}>{run.status}</span>{run.error ? <small>{run.error}</small> : null}</td></tr>)}</tbody></table></div> : <EmptyState title="尚无运行历史" description="执行目标总结或文献调研后会记录在这里。" />}
      </section>
    </section>
  );
}
