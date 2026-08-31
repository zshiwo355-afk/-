const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000';

export async function uploadJob(file, options) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('target_language', options.targetLanguage);
  formData.append('translation_mode', options.translationMode);
  formData.append('stream', String(options.stream));
  formData.append('chunk_size_chars', String(options.chunkSizeChars));
  formData.append('corpus_id', options.corpusId);
  formData.append('use_corpus', String(options.useCorpus));
  formData.append('use_glossary', String(options.useGlossary));
  formData.append('use_style_examples', String(options.useStyleExamples));
  formData.append('use_domain_prompt', String(options.useDomainPrompt));
  formData.append('translate_mode', options.translateMode);
  formData.append('translation_level', String(options.translationLevel));
  formData.append('speed_mode', options.speedMode || 'stable');

  const response = await fetch(`${API_BASE}/api/jobs/upload`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export async function postJobAction(jobId, action, payload = null, options = {}) {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}/${action}`, {
    method: 'POST',
    headers: payload ? { 'Content-Type': 'application/json', ...(options.headers || {}) } : options.headers,
    body: payload ? JSON.stringify(payload) : undefined,
  });
  if (!response.ok) {
    const responseText = await response.text();
    let message = responseText;
    try {
      const detail = JSON.parse(responseText).detail;
      message = typeof detail === 'object' ? detail.message || responseText : detail || responseText;
    } catch {
      // Keep plain-text errors unchanged.
    }
    throw new Error(message);
  }
  return response.json();
}

export async function fetchJob(jobId) {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export async function fetchSegments(jobId) {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}/segments`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export function openJobEvents(jobId, handlers) {
  const source = new EventSource(`${API_BASE}/api/jobs/${jobId}/events`);

  source.onmessage = () => {};
  source.addEventListener('connected', () => {
    handlers.onConnected?.();
  });

  [
    'job_started',
    'job_updated',
    'job_pausing',
    'job_paused',
    'job_completed',
    'job_failed',
    'job_cancelled',
    'chunk_started',
    'chunk_completed',
    'chunk_failed',
    'segment_delta',
    'segment_completed',
  ].forEach((eventName) => {
    source.addEventListener(eventName, (event) => {
      handlers.onEvent?.(eventName, JSON.parse(event.data));
    });
  });

  source.onerror = () => {
    handlers.onError?.();
  };
  return source;
}

export function buildDownloadUrl(jobId, fileType) {
  return `${API_BASE}/api/jobs/${jobId}/download/${fileType}`;
}

async function requestJson(url, options = {}) {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: options.body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!response.ok) {
    const responseText = await response.text();
    let message = responseText;
    try {
      message = JSON.parse(responseText).detail || responseText;
    } catch {
      // Keep plain-text errors unchanged.
    }
    throw new Error(message);
  }
  return response.json();
}

export const settingsApi = {
  get: () => requestJson('/api/settings'),
  save: (payload) => requestJson('/api/settings', { method: 'PUT', body: JSON.stringify(payload) }),
};

export const corpusApi = {
  list: () => requestJson('/api/corpus'),
  get: (id) => requestJson(`/api/corpus/${id}`),
  create: (payload) => requestJson('/api/corpus', { method: 'POST', body: JSON.stringify(payload) }),
  save: (id, payload) => requestJson(`/api/corpus/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  deleteCorpus: (id) => requestJson(`/api/corpus/${id}`, { method: 'DELETE' }),
  updateDomainPrompt: (id, domainPrompt) =>
    requestJson(`/api/corpus/${id}/domain-prompt`, {
      method: 'PUT',
      body: JSON.stringify({ domain_prompt: domainPrompt }),
    }),
  addTerm: (id, payload) => requestJson(`/api/corpus/${id}/glossary`, { method: 'POST', body: JSON.stringify(payload) }),
  updateTerm: (id, termId, payload) =>
    requestJson(`/api/corpus/${id}/glossary/${termId}`, { method: 'PUT', body: JSON.stringify(payload) }),
  deleteTerm: (id, termId) => requestJson(`/api/corpus/${id}/glossary/${termId}`, { method: 'DELETE' }),
  addExample: (id, payload) => requestJson(`/api/corpus/${id}/examples`, { method: 'POST', body: JSON.stringify(payload) }),
  updateExample: (id, exampleId, payload) =>
    requestJson(`/api/corpus/${id}/examples/${exampleId}`, { method: 'PUT', body: JSON.stringify(payload) }),
  deleteExample: (id, exampleId) => requestJson(`/api/corpus/${id}/examples/${exampleId}`, { method: 'DELETE' }),
  exportUrl: (id) => `${API_BASE}/api/corpus/${id}/export`,
  import: (id, file) => {
    const formData = new FormData();
    formData.append('file', file);
    return requestJson(`/api/corpus/${id}/import`, { method: 'POST', body: formData });
  },
  importJson: (payload) => requestJson('/api/corpus/import-json', { method: 'POST', body: JSON.stringify(payload) }),
};
