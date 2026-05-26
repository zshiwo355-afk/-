const TARGET_OPTIONS = ['简体中文', '繁体中文', '日语', '韩语', '自定义'];
const MODE_OPTIONS = ['忠实翻译', '阅读优化', '知识库入库'];
const TRANSLATE_MODES = [
  ['faithful', '忠实直译'],
  ['natural', '自然阅读'],
  ['psychology', '心理学专业'],
  ['wiki', '知识库入库'],
  ['bilingual_learning', '双语学习'],
];

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
          <select value={config.targetLanguageChoice} onChange={(event) => onConfigChange('targetLanguageChoice', event.target.value)}>
            {TARGET_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>旧版翻译模式</span>
          <select value={config.translationMode} onChange={(event) => onConfigChange('translationMode', event.target.value)}>
            {MODE_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>翻译模式</span>
          <select value={config.translateMode} onChange={(event) => onConfigChange('translateMode', event.target.value)}>
            {TRANSLATE_MODES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>翻译程度</span>
          <select value={config.translationLevel} onChange={(event) => onConfigChange('translationLevel', Number(event.target.value))}>
            <option value={1}>1 贴近原文</option>
            <option value={2}>2 忠实通顺</option>
            <option value={3}>3 自然中文</option>
            <option value={4}>4 专业书籍</option>
            <option value={5}>5 深度润色</option>
          </select>
        </label>

        <label>
          <span>翻译速度</span>
          <select value={config.speedMode || 'stable'} onChange={(event) => onConfigChange('speedMode', event.target.value)}>
            <option value="stable">稳定模式（推荐，最稳）</option>
            <option value="balanced">平衡模式（更快，轻度并发）</option>
            <option value="fast">快速模式（最快，可能触发限流）</option>
          </select>
        </label>

        <label>
          <span>Chunk Size</span>
          <input type="number" min="500" step="100" value={config.chunkSizeChars} onChange={(event) => onConfigChange('chunkSizeChars', Number(event.target.value))} />
        </label>

        <label className="toggle-line">
          <span>Stream</span>
          <input type="checkbox" checked={config.stream} onChange={(event) => onConfigChange('stream', event.target.checked)} />
        </label>

        <label className="toggle-line">
          <span>启用语料库</span>
          <input type="checkbox" checked={config.useCorpus} onChange={(event) => onConfigChange('useCorpus', event.target.checked)} />
        </label>

        <label className="toggle-line">
          <span>术语库</span>
          <input type="checkbox" checked={config.useGlossary} onChange={(event) => onConfigChange('useGlossary', event.target.checked)} />
        </label>

        <label className="toggle-line">
          <span>风格示例</span>
          <input type="checkbox" checked={config.useStyleExamples} onChange={(event) => onConfigChange('useStyleExamples', event.target.checked)} />
        </label>

        <label className="toggle-line">
          <span>领域提示</span>
          <input type="checkbox" checked={config.useDomainPrompt} onChange={(event) => onConfigChange('useDomainPrompt', event.target.checked)} />
        </label>
      </div>

      {showCustomLanguage ? (
        <label className="custom-language">
          <span>自定义语言</span>
          <input type="text" placeholder="例如：法语" value={config.customTargetLanguage} onChange={(event) => onConfigChange('customTargetLanguage', event.target.value)} />
        </label>
      ) : null}

      <div className="toolbar-actions">
        <button type="button" onClick={onStart} disabled={!canStart || ['running', 'pausing', 'paused'].includes(jobStatus)}>
          开始翻译
        </button>
        <button type="button" onClick={onPause} disabled={jobStatus !== 'running'}>
          {jobStatus === 'pausing' ? '正在暂停...' : '暂停'}
        </button>
        <button type="button" onClick={onResume} disabled={resumeBlocked || !canResume}>
          继续
        </button>
        <button type="button" onClick={onCancel} disabled={!['running', 'pausing', 'paused', 'failed', 'pending'].includes(jobStatus)}>
          停止
        </button>
      </div>
    </section>
  );
}
