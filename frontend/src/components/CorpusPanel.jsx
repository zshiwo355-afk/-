import { useEffect, useMemo, useState } from 'react';
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
    onConfigChange('corpusId', id);
    applyCorpus(await corpusApi.get(id));
  };

  const validatePastedCorpus = (data) => {
    if (typeof data?.domain_prompt !== 'string') {
      throw new Error('domain_prompt 必须是字符串。');
    }
    if (!Array.isArray(data?.glossary)) {
      throw new Error('glossary 必须是数组。');
    }
    if (!Array.isArray(data?.style_examples)) {
      throw new Error('style_examples 必须是数组。');
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
    const trimmed = domainPrompt.trim();
    if (trimmed.startsWith('{')) {
      try {
        const parsed = JSON.parse(trimmed);
        if (parsed && (parsed.domain_prompt || parsed.glossary || parsed.style_examples)) {
          const shouldImport = window.confirm('检测到你粘贴的是完整语料库 JSON，不是普通领域提示。是否导入为语料库？');
          if (shouldImport) {
            const result = await importParsedCorpus(parsed, 'replace_current');
            onStatus(`已导入：${result.glossary_count} 条术语，${result.style_example_count} 条示例。`);
          }
          return;
        }
      } catch {
        // Not a corpus JSON, keep normal save behavior.
      }
    }
    const next = await corpusApi.updateDomainPrompt(corpusMeta.id, domainPrompt);
    applyCorpus(next);
    onStatus('领域提示已保存。语料库修改会影响后续未翻译段落，已完成段落不会自动重翻。');
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
    const normalized = pastePreview || parsePastePreview();
    if (!normalized) return;
    const result = await importParsedCorpus(normalized, mode);
    setPasteText('');
    setPastePreview(null);
    setPasteError('');
    onStatus(`已导入：${result.glossary_count} 条术语，${result.style_example_count} 条示例。`);
  };

  const createCorpus = async () => {
    const name = window.prompt('语料库名称');
    if (!name) return;
    const next = await corpusApi.create({ name, description: '' });
    await loadCorpora(next.id);
  };

  const deleteCorpus = async () => {
    if (!corpusMeta || corpusMeta.id === 'default') return;
    await corpusApi.deleteCorpus(corpusMeta.id);
    await loadCorpora('default');
  };

  const addTerm = async () => {
    if (!termDraft.source || !termDraft.target) return;
    await corpusApi.addTerm(corpusMeta.id, termDraft);
    setTermDraft(EMPTY_TERM);
    applyCorpus(await corpusApi.get(corpusMeta.id));
    onStatus('术语已保存。语料库修改会影响后续未翻译段落，已完成段落不会自动重翻。');
  };

  const updateTerm = async (term) => {
    await corpusApi.updateTerm(corpusMeta.id, term.id, term);
    applyCorpus(await corpusApi.get(corpusMeta.id));
  };

  const deleteTerm = async (termId) => {
    await corpusApi.deleteTerm(corpusMeta.id, termId);
    applyCorpus(await corpusApi.get(corpusMeta.id));
  };

  const addExample = async () => {
    if (!exampleDraft.source || !exampleDraft.target) return;
    await corpusApi.addExample(corpusMeta.id, exampleDraft);
    setExampleDraft(EMPTY_EXAMPLE);
    applyCorpus(await corpusApi.get(corpusMeta.id));
    onStatus('译例已保存。语料库修改会影响后续未翻译段落，已完成段落不会自动重翻。');
  };

  const updateExample = async (example) => {
    await corpusApi.updateExample(corpusMeta.id, example.id, example);
    applyCorpus(await corpusApi.get(corpusMeta.id));
  };

  const deleteExample = async (exampleId) => {
    await corpusApi.deleteExample(corpusMeta.id, exampleId);
    applyCorpus(await corpusApi.get(corpusMeta.id));
  };

  const importCorpus = async (file) => {
    const next = normalizeCorpus(await corpusApi.import(corpusMeta.id, file));
    applyCorpus(next);
    await loadCorpora(next.id);
  };

  const filteredTerms = useMemo(
    () => glossary.filter((item) => `${item.source} ${item.target} ${item.note}`.toLowerCase().includes(termSearch.toLowerCase())),
    [glossary, termSearch],
  );
  const filteredExamples = useMemo(
    () => styleExamples.filter((item) => `${item.source} ${item.target} ${item.note}`.toLowerCase().includes(exampleSearch.toLowerCase())),
    [styleExamples, exampleSearch],
  );

  return (
    <section className="corpus-panel">
      <button className="secondary-button" type="button" onClick={() => setOpen((current) => !current)}>
        语料库配置
      </button>
      {open && corpusMeta ? (
        <div className="corpus-body">
          {['running', 'pausing'].includes(jobStatus) ? (
            <p className="corpus-note">语料库修改会影响后续未翻译段落，已完成段落不会自动重翻。</p>
          ) : null}

          <div className="corpus-row">
            <select value={config.corpusId} onChange={(event) => selectCorpus(event.target.value)}>
              {corpora.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <button type="button" onClick={createCorpus}>新建语料库</button>
            <a className="secondary-button" href={corpusApi.exportUrl(corpusMeta.id)} target="_blank" rel="noreferrer">
              导出语料库
            </a>
            <label className="secondary-button">
              导入语料库
              <input
                className="hidden-input"
                type="file"
                accept="application/json"
                onChange={async (event) => {
                  const file = event.target.files?.[0];
                  if (file) await importCorpus(file);
                  event.target.value = '';
                }}
              />
            </label>
            <button type="button" onClick={() => setPasteOpen((current) => !current)}>
              粘贴导入语料库
            </button>
            <button type="button" disabled={corpusMeta.id === 'default'} onClick={deleteCorpus}>
              删除语料库
            </button>
          </div>

          {pasteOpen ? (
            <div className="paste-import">
              <h3>粘贴完整语料库 JSON</h3>
              <textarea
                value={pasteText}
                placeholder="请粘贴完整 corpus.json，格式包含 id、name、description、domain_prompt、glossary、style_examples"
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
                  <span>示例数量：{pastePreview.style_examples.length}</span>
                </div>
              ) : null}
              <div className="toolbar-actions compact-actions">
                <button type="button" onClick={parsePastePreview}>解析预览</button>
                <button type="button" onClick={() => importPaste('replace_current')}>导入到当前语料库</button>
                <button type="button" onClick={() => importPaste('create_new')}>作为新语料库导入</button>
                <button
                  type="button"
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
            <span>领域提示</span>
            <textarea value={domainPrompt} maxLength={1500} onChange={(event) => setDomainPrompt(event.target.value)} />
          </label>
          <button type="button" onClick={saveDomainPrompt}>保存领域提示</button>

          <h3>术语库（共 {glossary.length} 条）</h3>
          <input placeholder="搜索术语" value={termSearch} onChange={(event) => setTermSearch(event.target.value)} />
          <div className="corpus-editor-line">
            <input placeholder="source" value={termDraft.source} onChange={(event) => setTermDraft({ ...termDraft, source: event.target.value })} />
            <input placeholder="target" value={termDraft.target} onChange={(event) => setTermDraft({ ...termDraft, target: event.target.value })} />
            <input placeholder="note" value={termDraft.note} onChange={(event) => setTermDraft({ ...termDraft, note: event.target.value })} />
            <button type="button" onClick={addTerm}>新增术语</button>
          </div>
          <div className="corpus-list">
            {filteredTerms.map((term) => (
              <div className="corpus-editor-line" key={term.id}>
                <input type="checkbox" checked={term.enabled} onChange={(event) => updateTerm({ ...term, enabled: event.target.checked })} />
                <input value={term.source} onChange={(event) => setGlossary((items) => items.map((item) => (item.id === term.id ? { ...item, source: event.target.value } : item)))} onBlur={(event) => updateTerm({ ...term, source: event.target.value })} />
                <input value={term.target} onChange={(event) => setGlossary((items) => items.map((item) => (item.id === term.id ? { ...item, target: event.target.value } : item)))} onBlur={(event) => updateTerm({ ...term, target: event.target.value })} />
                <input value={term.note} onChange={(event) => setGlossary((items) => items.map((item) => (item.id === term.id ? { ...item, note: event.target.value } : item)))} onBlur={(event) => updateTerm({ ...term, note: event.target.value })} />
                <button type="button" onClick={() => deleteTerm(term.id)}>删除</button>
              </div>
            ))}
          </div>

          <h3>风格示例（共 {styleExamples.length} 条）</h3>
          <input placeholder="搜索示例" value={exampleSearch} onChange={(event) => setExampleSearch(event.target.value)} />
          <div className="corpus-editor-line">
            <input placeholder="source" value={exampleDraft.source} onChange={(event) => setExampleDraft({ ...exampleDraft, source: event.target.value })} />
            <input placeholder="target" value={exampleDraft.target} onChange={(event) => setExampleDraft({ ...exampleDraft, target: event.target.value })} />
            <input placeholder="note" value={exampleDraft.note} onChange={(event) => setExampleDraft({ ...exampleDraft, note: event.target.value })} />
            <button type="button" onClick={addExample}>新增示例</button>
          </div>
          <div className="corpus-list">
            {filteredExamples.map((example) => (
              <div className="corpus-editor-line example-line" key={example.id}>
                <input type="checkbox" checked={example.enabled} onChange={(event) => updateExample({ ...example, enabled: event.target.checked })} />
                <textarea value={example.source} onChange={(event) => setStyleExamples((items) => items.map((item) => (item.id === example.id ? { ...item, source: event.target.value } : item)))} onBlur={(event) => updateExample({ ...example, source: event.target.value })} />
                <textarea value={example.target} onChange={(event) => setStyleExamples((items) => items.map((item) => (item.id === example.id ? { ...item, target: event.target.value } : item)))} onBlur={(event) => updateExample({ ...example, target: event.target.value })} />
                <input value={example.note} onChange={(event) => setStyleExamples((items) => items.map((item) => (item.id === example.id ? { ...item, note: event.target.value } : item)))} onBlur={(event) => updateExample({ ...example, note: event.target.value })} />
                <button type="button" onClick={() => deleteExample(example.id)}>删除</button>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
