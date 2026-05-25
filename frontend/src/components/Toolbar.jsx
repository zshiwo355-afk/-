const TARGET_OPTIONS = ['简体中文', '繁体中文', '日语', '韩语', '自定义'];
const MODE_OPTIONS = ['忠实翻译', '阅读优化', '知识库入库'];

export default function Toolbar({
  config,
  canStart,
  jobStatus,
  resumeBlocked,
  canResume,
  onConfigChange,
  onStart,
  onPause,
  onResume,
  onCancel,
}) {
  const showCustomLanguage = config.targetLanguageChoice === '自定义';

  return (
    <section className="toolbar-card">
      <div className="toolbar-grid">
        <label>
          <span>目标语言</span>
          <select
            value={config.targetLanguageChoice}
            onChange={(event) => onConfigChange('targetLanguageChoice', event.target.value)}
          >
            {TARGET_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>翻译模式</span>
          <select
            value={config.translationMode}
            onChange={(event) => onConfigChange('translationMode', event.target.value)}
          >
            {MODE_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>Chunk Size</span>
          <input
            type="number"
            min="500"
            step="100"
            value={config.chunkSizeChars}
            onChange={(event) => onConfigChange('chunkSizeChars', Number(event.target.value))}
          />
        </label>

        <label className="toggle-line">
          <span>Stream</span>
          <input
            type="checkbox"
            checked={config.stream}
            onChange={(event) => onConfigChange('stream', event.target.checked)}
          />
        </label>
      </div>

      {showCustomLanguage ? (
        <label className="custom-language">
          <span>自定义语言</span>
          <input
            type="text"
            placeholder="例如：法语"
            value={config.customTargetLanguage}
            onChange={(event) => onConfigChange('customTargetLanguage', event.target.value)}
          />
        </label>
      ) : null}

      <div className="toolbar-actions">
        <button
          onClick={onStart}
          disabled={!canStart || ['running', 'pausing', 'paused'].includes(jobStatus)}
        >
          开始翻译
        </button>
        <button onClick={onPause} disabled={jobStatus !== 'running'}>
          {jobStatus === 'pausing' ? '正在暂停...' : '暂停'}
        </button>
        <button onClick={onResume} disabled={resumeBlocked || !canResume}>
          继续
        </button>
        <button onClick={onCancel} disabled={!['running', 'pausing', 'paused', 'failed', 'pending'].includes(jobStatus)}>
          停止
        </button>
      </div>
    </section>
  );
}
