import { useEffect, useState } from 'react';
import { settingsApi } from '../api';

export default function ApiSettings({ onStatus, onAvailabilityChange }) {
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('');
  const [hasApiKey, setHasApiKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState(null);

  useEffect(() => {
    settingsApi.get()
      .then((settings) => {
        setBaseUrl(settings.base_url || '');
        setModel(settings.model || '');
        setHasApiKey(Boolean(settings.has_api_key));
        onAvailabilityChange?.(Boolean(settings.has_api_key && settings.base_url && settings.model));
      })
      .catch((error) => {
        const message = String(error);
        setFeedback({ type: 'error', message });
        onStatus(message);
      });
  }, []);

  const saveSettings = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      const settings = await settingsApi.save({
        base_url: baseUrl.trim(),
        api_key: apiKey,
        model: model.trim(),
      });
      setBaseUrl(settings.base_url);
      setModel(settings.model);
      setHasApiKey(settings.has_api_key);
      setApiKey('');
      setFeedback({ type: 'success', message: '配置已保存；首次翻译时会验证连接。' });
      onAvailabilityChange?.(Boolean(settings.has_api_key && settings.base_url && settings.model));
      onStatus('模型接口配置已保存到本机。');
    } catch (error) {
      const message = String(error);
      setFeedback({ type: 'error', message });
      onStatus(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="settings-card api-settings">
      <div className="settings-heading">
        <div>
          <span className="section-kicker">模型连接</span>
          <h2>模型接口</h2>
        </div>
        <span className={`connection-state ${hasApiKey ? 'ready' : ''}`}>
          {hasApiKey ? '已保存' : '待配置'}
        </span>
      </div>

      <form onSubmit={saveSettings}>
        <label>
          <span>接口地址（URL）</span>
          <input
            type="url"
            required
            value={baseUrl}
            placeholder="https://api.example.com/v1"
            onChange={(event) => {
              setBaseUrl(event.target.value);
              setFeedback(null);
            }}
          />
        </label>
        <label>
          <span>访问密钥（API Key）</span>
          <input
            type="password"
            required={!hasApiKey}
            value={apiKey}
            autoComplete="new-password"
            placeholder={hasApiKey ? '已配置；留空不会修改' : '请输入你的访问密钥'}
            onChange={(event) => {
              setApiKey(event.target.value);
              setFeedback(null);
            }}
          />
        </label>
        <label>
          <span>模型名称</span>
          <input
            type="text"
            required
            value={model}
            spellCheck="false"
            autoComplete="off"
            placeholder="请输入服务商提供的模型名称"
            onChange={(event) => {
              setModel(event.target.value);
              setFeedback(null);
            }}
          />
        </label>
        <p className="settings-help">URL、API Key 和模型名称需要来自同一个服务；当前支持兼容 OpenAI Chat Completions 的文本模型。并非所有模型都适合，翻译质量和格式稳定性取决于模型。</p>
        <p className="settings-help">保存只代表写入本机；配置会成套用于之后开始或继续的翻译，已经完成的内容不会自动重翻。密钥不会在页面回显。</p>
        {feedback ? (
          <p className={`settings-feedback ${feedback.type}`} role={feedback.type === 'error' ? 'alert' : 'status'}>
            {feedback.message}
          </p>
        ) : null}
        <button className="save-settings-button" type="submit" disabled={saving}>
          {saving ? '保存中…' : '保存连接'}
        </button>
      </form>
    </section>
  );
}
