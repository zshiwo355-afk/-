const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000';

export async function uploadJob(file, options) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('target_language', options.targetLanguage);
  formData.append('translation_mode', options.translationMode);
  formData.append('stream', String(options.stream));
  formData.append('chunk_size_chars', String(options.chunkSizeChars));

  const response = await fetch(`${API_BASE}/api/jobs/upload`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export async function postJobAction(jobId, action) {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}/${action}`, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error(await response.text());
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

