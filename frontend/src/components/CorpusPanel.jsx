import { useEffect, useMemo, useRef, useState } from 'react';
import { corpusApi } from '../api';

const EMPTY_TERM = { source: '', target: '', note: '', enabled: true };
const EMPTY_EXAMPLE = { source: '', target: '', note: '', enabled: true };

function normalizeCorpus(data) {
  return {
    ...(data || {}),
    domain_prompt: typeof data?.domain_prompt === 'string' ? data.domain_prompt : '',
    glossary: Array.isArray(data?.glossary) ? data.glossary : [],
    style_examples: Array.isArray(data?.style_examples) ? data.style_examples : [],
  };
}

export default function CorpusPanel({ config, jobStatus, onConfigChange, onStatus }) {
  const [open, setOpen] = useState(false);
  const [corpora, setCorpora] = useState([]);
  const [corpusMeta, setCorpusMeta] = useState(null);
  const [domainPrompt, setDomainPrompt] = useState('');
  const [glossary, setGlossary] = useState([]);
  const [styleExamples, setStyleExamples] = useState([]);
  const [termDraft, setTermDraft] = useState(EMPTY_TERM);
  const [exampleDraft, setExampleDraft] = useState(EMPTY_EXAMPLE);
  const [termSearch, setTermSearch] = useState('');
  const [exampleSearch, setExampleSearch] = useState('');
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState('');
  const [pasteError, setPasteError] = useState('');
  const [pastePreview, setPastePreview] = useState(null);
  const [termError, setTermError] = useState('');
  const [termSaving, setTermSaving] = useState(false);
  const [exampleSaving, setExampleSaving] = useState(false);
  const [domainPromptSaving, setDomainPromptSaving] = useState(false);
  const [corpusActionSaving, setCorpusActionSaving] = useState(false);
  const [savingTermId, setSavingTermId] = useState('');
  const [savingExampleId, setSavingExampleId] = useState('');
  const [dirtyTermIds, setDirtyTermIds] = useState(() => new Set());
  const [dirtyExampleIds, setDirtyExampleIds] = useState(() => new Set());
  const [domainPromptDirty, setDomainPromptDirty] = useState(false);
  const termSourceRef = useRef(null);
  const corpusRequestPending = Boolean(
    termSaving || exampleSaving || domainPromptSaving || corpusActionSaving || savingTermId || savingExampleId,
  );

  const hasUnsavedEdits = Boolean(
    dirtyTermIds.size
    || dirtyExampleIds.size
    || domainPromptDirty
    || termDraft.source.trim()
    || termDraft.target.trim()
    || termDraft.note.trim()
    || exampleDraft.source.trim()
    || exampleDraft.target.trim()
    || exampleDraft.note.trim(),
  );

  const confirmDiscardEdits = () => (
    !hasUnsavedEdits
    || window.confirm('当前还有未保存的输入或修改。继续会丢失这些内容，确定继续吗？')
  );

  const applyCorpus = (data) => {
    const corpus = normalizeCorpus(data);
    setCorpusMeta({
      id: corpus.id,
      name: corpus.name,
      description: corpus.description || '',
      created_at: corpus.created_at,
      updated_at: corpus.updated_at,
    });
    setDomainPrompt(corpus.domain_prompt || '');
    setGlossary(corpus.glossary || []);
    setStyleExamples(corpus.style_examples || []);
    setTermDraft(EMPTY_TERM);
    setExampleDraft(EMPTY_EXAMPLE);
    setDirtyTermIds(new Set());
    setDirtyExampleIds(new Set());
    setDomainPromptDirty(false);
  };

  const loadCorpora = async (selectedId = config.corpusId) => {
    const list = await corpusApi.list();
    setCorpora(list);
    const nextId = selectedId || list[0]?.id || 'default';
    onConfigChange('corpusId', nextId);
    applyCorpus(await corpusApi.get(nextId));
  };

  useEffect(() => {
    loadCorpora().catch((error) => onStatus(String(error)));
  }, []);

  const selectCorpus = async (id) => {
    if (corpusRequestPending || id === config.corpusId || !confirmDiscardEdits()) return;
    setCorpusActionSaving(true);
    try {
      const next = await corpusApi.get(id);
      onConfigChange('corpusId', id);
      applyCorpus(next);
    } catch (error) {
      onStatus(String(error));
    } finally {
      setCorpusActionSaving(false);
    }
  };

  const validatePastedCorpus = (data) => {
    if (!data || Array.isArray(data) || typeof data !== 'object') {
      throw new Error('语料库备份必须是一个 JSON 对象。');
    }
    if (typeof data?.domain_prompt !== 'string') {
      throw new Error('备份中的整体翻译要求格式不正确。');
    }
    if (!Array.isArray(data?.glossary)) {
      throw new Error('备份中的术语列表格式不正确。');
    }
    if (!Array.isArray(data?.style_examples)) {
      throw new Error('备份中的风格参考列表格式不正确。');
    }
    return normalizeCorpus(data);
  };

  const importParsedCorpus = async (data, mode) => {
    const normalized = validatePastedCorpus(data);
    const result = await corpusApi.importJson({
      mode,
      target_corpus_id: corpusMeta.id,
      data: normalized,
    });
    applyCorpus(result.corpus);
    await loadCorpora(result.corpus_id);
    onConfigChange('corpusId', result.corpus_id);
    return result;
  };

  const saveDomainPrompt = async () => {
    if (corpusRequestPending) return;
    setDomainPromptSaving(true);
    try {
      const next = await corpusApi.updateDomainPrompt(corpusMeta.id, domainPrompt);
      setDomainPrompt(next.domain_prompt || '');
      setDomainPromptDirty(false);
      setCorpusMeta((current) => ({ ...current, updated_at: next.updated_at }));
      onStatus('整体翻译要求已保存，只会影响后续未翻译的内容。');
    } catch (error) {
      onStatus(String(error));
    } finally {
      setDomainPromptSaving(false);
    }
  };

  const parsePastePreview = () => {
    try {
      const parsed = JSON.parse(pasteText);
      const normalized = validatePastedCorpus(parsed);
      setPasteError('');
      setPastePreview(normalized);
      return normalized;
    } catch (error) {
      setPastePreview(null);
      setPasteError(error.message?.includes('必须') ? error.message : 'JSON 格式错误，请检查逗号、引号和括号。');
      return null;
    }
  };

  const importPaste = async (mode) => {
    if (corpusRequestPending) return;
    const normalized = pastePreview || parsePastePreview();
    if (!normalized) return;
    if (mode === 'replace_current' && !window.confirm(`这会替换“${corpusMeta.name}”中的整体翻译要求、全部术语和全部风格参考，并丢弃当前未保存的输入。确定继续吗？`)) return;
    if (mode === 'create_new' && !confirmDiscardEdits()) return;
    setCorpusActionSaving(true);
    try {
      const result = await importParsedCorpus(normalized, mode);
      setPasteText('');
      setPastePreview(null);
      setPasteError('');
      onStatus(`已导入：${result.glossary_count} 条术语，${result.style_example_count} 条示例。`);
    } catch (error) {
      onStatus(String(error));
    } finally {
      setCorpusActionSaving(false);
    }
  };

  const createCorpus = async () => {
    if (corpusRequestPending || !confirmDiscardEdits()) return;
    const name = window.prompt('语料库名称');
    const trimmedName = name?.trim();
    if (!trimmedName) return;
    setCorpusActionSaving(true);
    try {
      const next = await corpusApi.create({ name: trimmedName, description: '' });
      await loadCorpora(next.id);
    } catch (error) {
      onStatus(String(error));
    } finally {
      setCorpusActionSaving(false);
    }
  };

  const deleteCorpus = async () => {
    if (!corpusMeta || corpusMeta.id === 'default') return;
    if (!window.confirm(`确定永久删除语料库“${corpusMeta.name}”吗？此操作无法撤销。`)) return;
    setCorpusActionSaving(true);
    try {
      await corpusApi.deleteCorpus(corpusMeta.id);
      await loadCorpora('default');
    } catch (error) {
      onStatus(String(error));
    } finally {
      setCorpusActionSaving(false);
    }
  };

  const addTerm = async (event) => {
    event.preventDefault();
    if (corpusRequestPending) return;
    const source = termDraft.source.trim();
    const target = termDraft.target.trim();
    if (!source || !target) {
      setTermError('请填写原文词语和固定译法。');
      return;
    }
    setTermSaving(true);
    try {
      const saved = await corpusApi.addTerm(corpusMeta.id, { ...termDraft, source, target, note: termDraft.note.trim() });
      setGlossary((items) => [...items, saved]);
      setTermDraft(EMPTY_TERM);
      setTermError('');
      onStatus('术语已保存。语料库修改会影响后续未翻译段落，已完成段落不会自动重翻。');
      window.requestAnimationFrame(() => termSourceRef.current?.focus());
    } catch (error) {
      setTermError(String(error));
    } finally {
      setTermSaving(false);
    }
  };

  const updateTerm = async (term) => {
    if (corpusRequestPending) return;
    const source = term.source.trim();
    const target = term.target.trim();
    if (!source || !target) {
      onStatus('原文词语和固定译法不能为空。');
      return;
    }
    setSavingTermId(term.id);
    try {
      const saved = await corpusApi.updateTerm(corpusMeta.id, term.id, { ...term, source, target, note: term.note.trim() });
      setGlossary((items) => items.map((item) => (item.id === saved.id ? saved : item)));
      setDirtyTermIds((ids) => {
        const next = new Set(ids);
        next.delete(saved.id);
        return next;
      });
      onStatus('术语修改已保存。');
    } catch (error) {
      onStatus(String(error));
    } finally {
      setSavingTermId('');
    }
  };

  const deleteTerm = async (term) => {
    if (corpusRequestPending) return;
    if (!window.confirm(`确定删除术语“${term.source}”吗？`)) return;
    setSavingTermId(term.id);
    try {
      await corpusApi.deleteTerm(corpusMeta.id, term.id);
      setGlossary((items) => items.filter((item) => item.id !== term.id));
      setDirtyTermIds((ids) => {
        const next = new Set(ids);
        next.delete(term.id);
        return next;
      });
    } catch (error) {
      onStatus(String(error));
    } finally {
      setSavingTermId('');
    }
  };

  const addExample = async () => {
    if (corpusRequestPending) return;
    const source = exampleDraft.source.trim();
    const target = exampleDraft.target.trim();
    if (!source || !target) {
      onStatus('原文示例和期望译文不能为空。');
      return;
    }
    setExampleSaving(true);
    try {
      const saved = await corpusApi.addExample(corpusMeta.id, { ...exampleDraft, source, target, note: exampleDraft.note.trim() });
      setStyleExamples((items) => [...items, saved]);
      setExampleDraft(EMPTY_EXAMPLE);
      onStatus('译例已保存。语料库修改会影响后续未翻译段落，已完成段落不会自动重翻。');
    } catch (error) {
      onStatus(String(error));
    } finally {
      setExampleSaving(false);
    }
  };

  const updateExample = async (example) => {
    if (corpusRequestPending) return;
    const source = example.source.trim();
    const target = example.target.trim();
    if (!source || !target) {
      onStatus('原文示例和期望译文不能为空。');
      return;
    }
    setSavingExampleId(example.id);
    try {
      const saved = await corpusApi.updateExample(corpusMeta.id, example.id, { ...example, source, target, note: example.note.trim() });
      setStyleExamples((items) => items.map((item) => (item.id === saved.id ? saved : item)));
      setDirtyExampleIds((ids) => {
        const next = new Set(ids);
        next.delete(saved.id);
        return next;
      });
      onStatus('风格示例修改已保存。');
    } catch (error) {
      onStatus(String(error));
    } finally {
      setSavingExampleId('');
    }
  };

  const deleteExample = async (example) => {
    if (corpusRequestPending) return;
    if (!window.confirm('确定删除这个风格示例吗？')) return;
    setSavingExampleId(example.id);
    try {
      await corpusApi.deleteExample(corpusMeta.id, example.id);
      setStyleExamples((items) => items.filter((item) => item.id !== example.id));
      setDirtyExampleIds((ids) => {
        const next = new Set(ids);
        next.delete(example.id);
        return next;
      });
    } catch (error) {
      onStatus(String(error));
    } finally {
      setSavingExampleId('');
    }
  };

  const importCorpus = async (file) => {
    if (corpusRequestPending) return;
    if (!window.confirm(`导入“${file.name}”会替换“${corpusMeta.name}”中的整体翻译要求、全部术语和全部风格参考，并丢弃当前未保存的输入。确定继续吗？`)) return;
    setCorpusActionSaving(true);
    try {
      const next = normalizeCorpus(await corpusApi.import(corpusMeta.id, file));
      applyCorpus(next);
      await loadCorpora(next.id);
    } catch (error) {
      onStatus(String(error));
    } finally {
      setCorpusActionSaving(false);
    }
  };

  const filteredTerms = useMemo(
    () => glossary.filter((item) => `${item.source} ${item.target} ${item.note}`.toLowerCase().includes(termSearch.toLowerCase())),
    [glossary, termSearch],
  );
  const filteredExamples = useMemo(
    () => styleExamples.filter((item) => `${item.source} ${item.target} ${item.note}`.toLowerCase().includes(exampleSearch.toLowerCase())),
    [styleExamples, exampleSearch],
  );

  const editTerm = (id, changes) => {
    setGlossary((items) => items.map((item) => (item.id === id ? { ...item, ...changes } : item)));
    setDirtyTermIds((ids) => new Set(ids).add(id));
  };

  const editExample = (id, changes) => {
    setStyleExamples((items) => items.map((item) => (item.id === id ? { ...item, ...changes } : item)));
    setDirtyExampleIds((ids) => new Set(ids).add(id));
  };

  return (
    <section className="corpus-panel">
      <button
        className="secondary-button"
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        术语与语料
      </button>
      {open && corpusMeta ? (
        <div className="corpus-body">
          {['running', 'pausing'].includes(jobStatus) ? (
            <p className="corpus-note">语料库修改会影响后续未翻译段落，已完成段落不会自动重翻。</p>
          ) : null}

          <div className="corpus-simple-head">
            <label className="corpus-select-field">
              <span>当前语料库</span>
              <select disabled={corpusRequestPending} value={config.corpusId} onChange={(event) => selectCorpus(event.target.value)}>
                {corpora.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" disabled={corpusRequestPending} onClick={createCorpus}>新建语料库</button>
          </div>

          <div className="corpus-intro">
            <strong>可以一个词一个词添加，不需要先导入文件。</strong>
            <span>例如原文中出现 attachment，希望固定译为“依恋”，就在下面分别填写并保存。</span>
          </div>

          <section className="term-section" aria-labelledby="term-section-title">
            <div className="term-section-head">
              <div>
                <h3 id="term-section-title">逐个添加词语</h3>
                <p>原文词语和固定译法必填，备注可以不填。</p>
              </div>
              <span>{glossary.length} 条</span>
            </div>

            <form className="term-add-form" onSubmit={addTerm}>
              <label>
                <span>原文词语</span>
                <input
                  ref={termSourceRef}
                  disabled={corpusRequestPending}
                  required
                  placeholder="例如：attachment"
                  value={termDraft.source}
                  onChange={(event) => {
                    setTermDraft({ ...termDraft, source: event.target.value });
                    setTermError('');
                  }}
                />
              </label>
              <label>
                <span>固定译法</span>
                <input
                  disabled={corpusRequestPending}
                  required
                  placeholder="例如：依恋"
                  value={termDraft.target}
                  onChange={(event) => {
                    setTermDraft({ ...termDraft, target: event.target.value });
                    setTermError('');
                  }}
                />
              </label>
              <label>
                <span>备注（可选）</span>
                <input
                  disabled={corpusRequestPending}
                  placeholder="例如：心理学术语"
                  value={termDraft.note}
                  onChange={(event) => setTermDraft({ ...termDraft, note: event.target.value })}
                />
              </label>
              <button type="submit" disabled={corpusRequestPending}>{termSaving ? '保存中…' : '添加这个术语'}</button>
            </form>
            {termError ? <p className="corpus-error" role="alert">{termError}</p> : null}

            <label className="corpus-search">
              <span>查找已添加的词语</span>
              <input placeholder="输入原文、译法或备注" value={termSearch} onChange={(event) => setTermSearch(event.target.value)} />
            </label>

            <div className="corpus-list-header" aria-hidden="true">
              <span>启用</span>
              <span>原文词语</span>
              <span>固定译法</span>
              <span>备注</span>
              <span>操作</span>
            </div>
            <div className="corpus-list term-list">
              {filteredTerms.length ? filteredTerms.map((term) => (
                <div className="corpus-editor-line term-row" key={term.id}>
                  <label className="term-toggle">
                    <input type="checkbox" disabled={corpusRequestPending} checked={term.enabled} onChange={(event) => editTerm(term.id, { enabled: event.target.checked })} />
                    <span>启用</span>
                  </label>
                  <label className="term-row-field">
                    <span>原文词语</span>
                    <input aria-label="原文词语" disabled={corpusRequestPending} value={term.source} onChange={(event) => editTerm(term.id, { source: event.target.value })} />
                  </label>
                  <label className="term-row-field">
                    <span>固定译法</span>
                    <input aria-label="固定译法" disabled={corpusRequestPending} value={term.target} onChange={(event) => editTerm(term.id, { target: event.target.value })} />
                  </label>
                  <label className="term-row-field">
                    <span>备注</span>
                    <input aria-label="备注" disabled={corpusRequestPending} value={term.note} onChange={(event) => editTerm(term.id, { note: event.target.value })} />
                  </label>
                  <div className="corpus-row-actions">
                    <button type="button" disabled={corpusRequestPending} onClick={() => updateTerm(term)}>
                      {savingTermId === term.id ? '保存中…' : '保存修改'}
                    </button>
                    <button className="danger-button" type="button" disabled={corpusRequestPending} onClick={() => deleteTerm(term)}>删除</button>
                  </div>
                </div>
              )) : <p className="corpus-empty">还没有添加术语。填写上面的三项后，点击“添加这个术语”即可。</p>}
            </div>
          </section>

          <details className="corpus-more">
            <summary>更多语料设置</summary>
            <div className="corpus-more-content">
              <p className="settings-help">语料库备份、整体翻译要求和风格参考都在这里；只添加词语时不需要打开。</p>

              <div className="corpus-intro corpus-backup-note">
                <strong>这里导入的是语料库备份，不是待翻译的书籍。</strong>
                <span>请选择本页面导出的 corpus.json。它包含整体翻译要求、术语和风格参考；不支持 TXT、Word、Excel 或普通词表，导入后会替换当前语料库。</span>
              </div>

              <div className="corpus-advanced-actions">
                <a className="secondary-button" href={corpusApi.exportUrl(corpusMeta.id)} target="_blank" rel="noreferrer">
                  下载语料库备份（JSON）
                </a>
                <label className="secondary-button corpus-file-button">
                  导入语料库备份（JSON）
                  <input
                    className="hidden-input"
                    type="file"
                    disabled={corpusRequestPending}
                    accept=".json,application/json"
                    onChange={async (event) => {
                      const file = event.target.files?.[0];
                      if (file) await importCorpus(file);
                      event.target.value = '';
                    }}
                  />
                </label>
                <button type="button" disabled={corpusRequestPending} onClick={() => setPasteOpen((current) => !current)}>
                  粘贴备份内容（高级）
                </button>
                <button type="button" disabled={corpusRequestPending || corpusMeta.id === 'default'} onClick={deleteCorpus}>
                  删除当前语料库
                </button>
              </div>

              {pasteOpen ? (
                <div className="paste-import">
                  <h3>粘贴语料库备份内容（JSON）</h3>
                  <textarea
                    disabled={corpusRequestPending}
                    value={pasteText}
                    placeholder="请粘贴本页面导出的 corpus.json 内容。"
                    onChange={(event) => {
                      setPasteText(event.target.value);
                      setPastePreview(null);
                      setPasteError('');
                    }}
                  />
                  {pasteError ? <p className="corpus-error">{pasteError}</p> : null}
                  {pastePreview ? (
                    <div className="paste-preview">
                      <strong>{pastePreview.name || '未命名语料库'}</strong>
                      <p>{(pastePreview.domain_prompt || '').slice(0, 100)}</p>
                      <span>术语数量：{pastePreview.glossary.length}</span>
                      <span>风格参考数量：{pastePreview.style_examples.length}</span>
                    </div>
                  ) : null}
                  <div className="compact-actions">
                    <button type="button" disabled={corpusRequestPending} onClick={parsePastePreview}>解析预览</button>
                    <button type="button" disabled={corpusRequestPending} onClick={() => importPaste('replace_current')}>导入到当前语料库</button>
                    <button type="button" disabled={corpusRequestPending} onClick={() => importPaste('create_new')}>作为新语料库导入</button>
                    <button
                      type="button"
                      disabled={corpusRequestPending}
                      onClick={() => {
                        setPasteText('');
                        setPastePreview(null);
                        setPasteError('');
                      }}
                    >
                      清空
                    </button>
                  </div>
                </div>
              ) : null}

              <label className="corpus-field">
                <span>整体翻译要求（可选）</span>
                <textarea
                  disabled={corpusRequestPending}
                  value={domainPrompt}
                  maxLength={1500}
                  placeholder="例如：保持小说对白自然；人物姓名保留原文。"
                  onChange={(event) => {
                    setDomainPrompt(event.target.value);
                    setDomainPromptDirty(true);
                  }}
                />
              </label>
              <p className="settings-help">启用“使用整体要求”后，它会随每个翻译批次发送给模型；修改后不会自动重翻已经完成的内容。</p>
              <button type="button" disabled={corpusRequestPending} onClick={saveDomainPrompt}>
                {domainPromptSaving ? '保存中…' : '保存整体要求'}
              </button>

              <div className="advanced-section-heading">
                <h3>风格参考（可选）</h3>
                <span>{styleExamples.length} 条</span>
              </div>
              <p className="settings-help">启用“使用风格参考”后，每个翻译批次都会把最近添加且已启用的最多 3 条发给模型。模型会参考语气、措辞和句式，但这不是训练，也不能保证逐字照搬。期望译文应与当前目标语言一致。</p>
              <label className="corpus-search">
                <span>查找风格参考</span>
                <input placeholder="输入原文、译文或备注" value={exampleSearch} onChange={(event) => setExampleSearch(event.target.value)} />
              </label>
              <div className="example-add-form">
                <input aria-label="示例原文" disabled={corpusRequestPending} placeholder="示例原文" value={exampleDraft.source} onChange={(event) => setExampleDraft({ ...exampleDraft, source: event.target.value })} />
                <input aria-label="你希望的译文" disabled={corpusRequestPending} placeholder="你希望的译文" value={exampleDraft.target} onChange={(event) => setExampleDraft({ ...exampleDraft, target: event.target.value })} />
                <input aria-label="备注（可选）" disabled={corpusRequestPending} placeholder="备注（可选）" value={exampleDraft.note} onChange={(event) => setExampleDraft({ ...exampleDraft, note: event.target.value })} />
                <button type="button" disabled={corpusRequestPending} onClick={addExample}>{exampleSaving ? '保存中…' : '添加风格参考'}</button>
              </div>
              <div className="corpus-list">
                {filteredExamples.length ? filteredExamples.map((example) => (
                  <div className="corpus-editor-line example-line" key={example.id}>
                    <input aria-label="启用示例" type="checkbox" disabled={corpusRequestPending} checked={example.enabled} onChange={(event) => editExample(example.id, { enabled: event.target.checked })} />
                    <textarea aria-label="原文示例" disabled={corpusRequestPending} value={example.source} onChange={(event) => editExample(example.id, { source: event.target.value })} />
                    <textarea aria-label="期望译文" disabled={corpusRequestPending} value={example.target} onChange={(event) => editExample(example.id, { target: event.target.value })} />
                    <input aria-label="备注" disabled={corpusRequestPending} value={example.note} onChange={(event) => editExample(example.id, { note: event.target.value })} />
                    <div className="corpus-row-actions">
                      <button type="button" disabled={corpusRequestPending} onClick={() => updateExample(example)}>
                        {savingExampleId === example.id ? '保存中…' : '保存修改'}
                      </button>
                      <button className="danger-button" type="button" disabled={corpusRequestPending} onClick={() => deleteExample(example)}>删除</button>
                    </div>
                  </div>
                )) : <p className="corpus-empty">还没有添加风格参考。</p>}
              </div>
            </div>
          </details>
        </div>
      ) : null}
    </section>
  );
}
