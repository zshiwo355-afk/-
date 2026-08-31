const TARGET_OPTIONS = ['简体中文', '繁体中文', '日语', '韩语', '自定义'];
const MODE_OPTIONS = ['忠实翻译', '阅读优化', '知识库入库'];
const TRANSLATE_MODES = [
  ['faithful', '忠实直译'],
  ['natural', '自然阅读'],
  ['psychology', '心理学专业'],
  ['wiki', '知识库入库'],
  ['bilingual_learning', '双语学习'],
];

export default function Toolbar({ config, onConfigChange }) {
  const showCustomLanguage = config.targetLanguageChoice === '自定义';

  return (
    <section className="settings-card toolbar-card">
      <div className="settings-heading">
        <div>
          <span className="section-kicker">工作参数</span>
          <h2>翻译设置</h2>
        </div>
      </div>

      <div className="toolbar-grid primary-settings">
        <div className="language-detection-line">
          <span>原文语言</span>
          <strong>自动识别</strong>
        </div>

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
          <span>表达方式</span>
          <select value={config.translateMode} onChange={(event) => onConfigChange('translateMode', event.target.value)}>
            {TRANSLATE_MODES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>翻译速度</span>
          <select value={config.speedMode || 'stable'} onChange={(event) => onConfigChange('speedMode', event.target.value)}>
            <option value="stable">稳定</option>
            <option value="balanced">平衡</option>
            <option value="fast">快速</option>
          </select>
        </label>
      </div>

      {showCustomLanguage ? (
        <label className="custom-language">
          <span>自定义语言</span>
          <input type="text" placeholder="例如：法语" value={config.customTargetLanguage} onChange={(event) => onConfigChange('customTargetLanguage', event.target.value)} />
        </label>
      ) : null}

      <details className="advanced-settings">
        <summary>高级设置</summary>
        <div className="toolbar-grid advanced-grid">
          <label>
            <span>兼容模式</span>
            <select value={config.translationMode} onChange={(event) => onConfigChange('translationMode', event.target.value)}>
              {MODE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>润色程度</span>
            <select value={config.translationLevel} onChange={(event) => onConfigChange('translationLevel', Number(event.target.value))}>
              <option value={1}>1 贴近原文</option>
              <option value={2}>2 忠实通顺</option>
              <option value={3}>3 自然表达</option>
              <option value={4}>4 专业书籍</option>
              <option value={5}>5 深度润色</option>
            </select>
          </label>

          <label>
            <span>分块字符数</span>
            <input type="number" min="500" step="100" value={config.chunkSizeChars} onChange={(event) => onConfigChange('chunkSizeChars', Number(event.target.value))} />
          </label>

          <label className="toggle-line">
            <span>流式输出</span>
            <input type="checkbox" checked={config.stream} onChange={(event) => onConfigChange('stream', event.target.checked)} />
          </label>
          <label className="toggle-line">
            <span>启用语料库</span>
            <input type="checkbox" checked={config.useCorpus} onChange={(event) => onConfigChange('useCorpus', event.target.checked)} />
          </label>
          <label className="toggle-line">
            <span>使用术语</span>
            <input type="checkbox" checked={config.useGlossary} onChange={(event) => onConfigChange('useGlossary', event.target.checked)} />
          </label>
          <label className="toggle-line">
            <span>使用风格参考</span>
            <input type="checkbox" checked={config.useStyleExamples} onChange={(event) => onConfigChange('useStyleExamples', event.target.checked)} />
          </label>
          <label className="toggle-line">
            <span>使用整体要求</span>
            <input type="checkbox" checked={config.useDomainPrompt} onChange={(event) => onConfigChange('useDomainPrompt', event.target.checked)} />
          </label>
        </div>
      </details>

    </section>
  );
}
