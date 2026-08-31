import { useEffect, useRef, useState } from 'react';
import { buildDownloadUrl, fetchJob, fetchSegments, openJobEvents, postJobAction, uploadJob } from './api';
import DropZone from './components/DropZone';
import Toolbar from './components/Toolbar';
import ProgressPanel from './components/ProgressPanel';
import TranslationViewer from './components/TranslationViewer';
import CorpusPanel from './components/CorpusPanel';
import ApiSettings from './components/ApiSettings';

const AUTH_FAILURE_CODE = 'API_AUTH_INVALID';
const AUTH_FAILURE_MESSAGE = '模型接口不可用，请检查 URL、API Key 和模型名称';
const DEFAULT_CONFIG = {
  targetLanguageChoice: '简体中文',
  customTargetLanguage: '',
  translationMode: '忠实翻译',
  stream: false,
  chunkSizeChars: 3500,
  corpusId: 'default',
  useCorpus: true,
  useGlossary: true,
  useStyleExamples: true,
  useDomainPrompt: true,
  translateMode: 'faithful',
  translationLevel: 3,
  speedMode: 'stable',
};

const DOWNLOAD_OPTIONS = [
  { fileType: 'translated.txt', label: '下载译文 TXT' },
  { fileType: 'translated.md', label: '下载译文 MD' },
  { fileType: 'bilingual.txt', label: '下载双语 TXT' },
  { fileType: 'bilingual.md', label: '下载双语 MD' },
];
const CURRENT_JOB_KEY = 'current_job_id';

function resolveTargetLanguage(config) {
  return config.targetLanguageChoice === '自定义'
    ? config.customTargetLanguage.trim() || '简体中文'
    : config.targetLanguageChoice;
}

function configFromJob(job, currentConfig) {
  if (!job?.config) return currentConfig;
  return {
    ...currentConfig,
    targetLanguageChoice: job.target_language || currentConfig.targetLanguageChoice,
    translationMode: job.config.translation_mode || currentConfig.translationMode,
    stream: job.config.stream,
    chunkSizeChars: job.config.chunk_size_chars,
    corpusId: job.config.corpus_id || 'default',
    useCorpus: job.config.use_corpus ?? true,
    useGlossary: job.config.use_glossary ?? true,
    useStyleExamples: job.config.use_style_examples ?? true,
    useDomainPrompt: job.config.use_domain_prompt ?? true,
    translateMode: job.config.translate_mode || 'faithful',
    translationLevel: job.config.translation_level || 3,
    speedMode: job.config.speed_mode || 'stable',
  };
}

function isJobConfigCompatible(job, config) {
  if (!job?.config) return false;
  return (
    job.target_language === resolveTargetLanguage(config) &&
    job.config.translation_mode === config.translationMode &&
    job.config.stream === config.stream &&
    job.config.chunk_size_chars === config.chunkSizeChars &&
    job.config.corpus_id === config.corpusId &&
    job.config.use_corpus === config.useCorpus &&
    job.config.use_glossary === config.useGlossary &&
    job.config.use_style_examples === config.useStyleExamples &&
    job.config.use_domain_prompt === config.useDomainPrompt &&
    job.config.translate_mode === config.translateMode &&
    job.config.translation_level === config.translationLevel &&
    (job.config.speed_mode || 'stable') === (config.speedMode || 'stable')
  );
}

function isRunningJobProbablyStuck(job) {
  if (job?.status !== 'running') return false;
  const heartbeatMs = Date.parse(job.last_run_heartbeat_at || job.updated_at || '');
  return Boolean(heartbeatMs) && Date.now() - heartbeatMs > 180000;
}

export default function App() {
  const [file, setFile] = useState(null);
  const [job, setJob] = useState(null);
  const [segments, setSegments] = useState([]);
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  const [selectedId, setSelectedId] = useState('');
  const [activeId, setActiveId] = useState('');
  const [followCurrent, setFollowCurrent] = useState(true);
  const [statusMessage, setStatusMessage] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [eventsVersion, setEventsVersion] = useState(0);
  const [apiConfigured, setApiConfigured] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [isMobileLayout, setIsMobileLayout] = useState(() => window.matchMedia('(max-width: 900px)').matches);
  const eventSourceRef = useRef(null);
  const currentJobIdRef = useRef('');
  const lastSegmentsFetchAtRef = useRef(0);
  const pendingSegmentsFetchRef = useRef(null);
  const translationViewerRef = useRef(null);
  const settingsCloseRef = useRef(null);
  const settingsToggleRef = useRef(null);

  const isTaskLocked = ['running', 'pausing', 'paused'].includes(job?.status || '') || isBusy;
  const canStart = apiConfigured !== false && (Boolean(file) || job?.status === 'pending');
  const hasAuthConfigError = job?.last_error?.includes(AUTH_FAILURE_CODE);
  const hasIncompleteSegments = segments.some((segment) => segment.status !== 'success');
  const failedSegments = segments.filter((segment) => segment.status === 'failed');
  const firstFailedSegment = failedSegments[0] || null;
  const selectedFailedSegment = segments.find((segment) => segment.segment_id === selectedId && segment.status === 'failed') || null;
  const canResume = apiConfigured !== false && ['paused', 'failed'].includes(job?.status || '') && hasIncompleteSegments;
  const canRepair = apiConfigured !== false && Boolean(job?.job_id) && isRunningJobProbablyStuck(job) && hasIncompleteSegments;
  const isCompleted = job?.status === 'completed';
  const canDownload = Boolean(job?.job_id) && ['completed', 'failed', 'paused', 'cancelled'].includes(job?.status || '');

  const handleConfigChange = async (key, value) => {
    setConfig((current) => ({ ...current, [key]: value }));
    if (key === 'speedMode' && job?.job_id) {
      try {
        const updatedJob = await postJobAction(job.job_id, 'speed-mode', { speed_mode: value });
        setJob(updatedJob);
        setConfig((current) => configFromJob(updatedJob, current));
      } catch {
        // ignore silently — job may be pending
      }
    }
  };

  const restoreJob = async (jobId) => {
    try {
      const restoredJob = await fetchJob(jobId);
      const restoredSegments = await fetchSegments(jobId);
      localStorage.setItem(CURRENT_JOB_KEY, jobId);
      currentJobIdRef.current = jobId;
      setJob(restoredJob);
      setSegments(restoredSegments);
      setFile(null);
      setConfig((current) => configFromJob(restoredJob, current));
      setActiveId(restoredJob.current_segment_id || '');
      setStatusMessage(
        restoredJob.status === 'completed'
          ? `翻译完成：${restoredJob.completed_segments} / ${restoredJob.total_segments}`
          : isRunningJobProbablyStuck(restoredJob)
          ? '模型请求可能卡住，可点击“修复并继续”。'
          : restoredJob.status === 'running'
            ? '任务已恢复。如果后端没有继续请求，请点击“修复并继续”。'
            : '任务已恢复',
      );
      setEventsVersion((current) => current + 1);
    } catch (error) {
      localStorage.removeItem(CURRENT_JOB_KEY);
      setJob(null);
      setSegments([]);
      setFile(null);
      setStatusMessage('保存的任务不存在，已清除本地恢复记录。');
    }
  };

  useEffect(() => {
    const savedJobId = localStorage.getItem(CURRENT_JOB_KEY);
    if (savedJobId) {
      restoreJob(savedJobId);
    }
  }, []);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(max-width: 900px)');
    const syncLayout = () => setIsMobileLayout(mediaQuery.matches);
    syncLayout();
    mediaQuery.addEventListener('change', syncLayout);
    return () => mediaQuery.removeEventListener('change', syncLayout);
  }, []);

  useEffect(() => {
    if (!isMobileLayout || !settingsOpen) return undefined;
    window.requestAnimationFrame(() => settingsCloseRef.current?.focus());
    const handleEscape = (event) => {
      if (event.key !== 'Escape') return;
      setSettingsOpen(false);
      window.requestAnimationFrame(() => settingsToggleRef.current?.focus());
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isMobileLayout, settingsOpen]);

  const openSettings = () => setSettingsOpen(true);
  const closeSettings = () => {
    setSettingsOpen(false);
    if (isMobileLayout) window.requestAnimationFrame(() => settingsToggleRef.current?.focus());
  };

  const clearCurrentTask = () => {
    if (isTaskLocked) {
      setStatusMessage('请先停止当前任务，再新建任务。');
      return;
    }
    localStorage.removeItem(CURRENT_JOB_KEY);
    eventSourceRef.current?.close();
    currentJobIdRef.current = '';
    setJob(null);
    setSegments([]);
    setFile(null);
    setSelectedId('');
    setActiveId('');
    setStatusMessage('已清除当前任务，可以新建任务。');
  };

  const refreshSegmentsSnapshot = async (jobId) => {
    if (!jobId) return;
    const now = Date.now();
    const elapsed = now - lastSegmentsFetchAtRef.current;
    if (elapsed < 4000) {
      if (!pendingSegmentsFetchRef.current) {
        pendingSegmentsFetchRef.current = window.setTimeout(() => {
          pendingSegmentsFetchRef.current = null;
          refreshSegmentsSnapshot(currentJobIdRef.current);
        }, 4000 - elapsed);
      }
      return;
    }
    lastSegmentsFetchAtRef.current = now;
    const latestSegments = await fetchSegments(jobId);
    if (currentJobIdRef.current !== jobId) return;
    setSegments(latestSegments);
  };

  const uploadSelectedFile = async (nextFile, configOverride = config) => {
    setStatusMessage(`正在解析 ${nextFile.name}...`);
    try {
      const nextJob = await uploadJob(nextFile, {
        targetLanguage: resolveTargetLanguage(configOverride),
        translationMode: configOverride.translationMode,
        stream: configOverride.stream,
        chunkSizeChars: configOverride.chunkSizeChars,
        corpusId: configOverride.corpusId,
        useCorpus: configOverride.useCorpus,
        useGlossary: configOverride.useGlossary,
        useStyleExamples: configOverride.useStyleExamples,
        useDomainPrompt: configOverride.useDomainPrompt,
        translateMode: configOverride.translateMode,
        translationLevel: configOverride.translationLevel,
        speedMode: configOverride.speedMode,
      });
      setJob(nextJob);
      localStorage.setItem(CURRENT_JOB_KEY, nextJob.job_id);
      setConfig((current) => configFromJob(nextJob, current));
      setSegments(await fetchSegments(nextJob.job_id));
      setSelectedId('');
      setActiveId('');
      setStatusMessage(`已解析 ${nextFile.name}，可以开始翻译`);
      return nextJob;
    } catch (error) {
      setJob(null);
      setSegments([]);
      setStatusMessage(String(error));
      return null;
    }
  };

  useEffect(() => {
    if (!job?.job_id) {
      currentJobIdRef.current = '';
      return undefined;
    }
    currentJobIdRef.current = job.job_id;
    eventSourceRef.current?.close();
    eventSourceRef.current = openJobEvents(job.job_id, {
      onConnected: () => setStatusMessage('已连接任务事件流'),
      onError: () => setStatusMessage('事件流重连中...'),
      onEvent: async (eventName, payload) => {
        if (eventName.startsWith('job_')) {
          if (payload.job_id || payload.status) {
            setJob((current) => ({ ...(current || {}), ...payload }));
            if (payload.config) setConfig((current) => configFromJob(payload, current));
          }
          if (eventName === 'job_pausing') setStatusMessage('正在暂停，将在当前段落完成后暂停');
          if (eventName === 'job_paused') setStatusMessage('已暂停');
          if (eventName === 'job_completed') setStatusMessage('翻译完成，可以下载结果');
          if (eventName === 'job_failed') setStatusMessage(payload.last_error || '任务失败，可继续重试');
          if (eventName === 'job_cancelled') setStatusMessage('任务已停止');
        }
        if (eventName === 'chunk_started') {
          setActiveId(payload.current_segment_id);
          setStatusMessage(`正在翻译 ${payload.current_segment_id}`);
        }
        if (eventName === 'segment_delta') {
          setActiveId(payload.segment_id);
          setSegments((current) =>
            current.map((segment) =>
              segment.segment_id === payload.segment_id
                ? { ...segment, status: 'running', translated_text: `${segment.translated_text || ''}${payload.delta}` }
                : segment,
            ),
          );
        }
        if (eventName === 'segment_completed') {
          setSegments((current) => current.map((segment) => (segment.segment_id === payload.segment_id ? payload : segment)));
        }
        if (eventName === 'chunk_completed' || eventName === 'chunk_failed') {
          await refreshSegmentsSnapshot(currentJobIdRef.current);
        }
      },
    });
    return () => {
      eventSourceRef.current?.close();
      if (pendingSegmentsFetchRef.current) window.clearTimeout(pendingSegmentsFetchRef.current);
    };
  }, [job?.job_id, eventsVersion]);

  const handleStart = async () => {
    if (!file && !job) return;
    if (apiConfigured === false) {
      openSettings();
      setStatusMessage('请先完成模型接口配置。');
      return;
    }
    setIsBusy(true);
    try {
      let nextJob = job;
      const shouldCreateNewJob =
        !nextJob || ['completed', 'failed', 'cancelled'].includes(nextJob.status) || !isJobConfigCompatible(nextJob, config);
      if (shouldCreateNewJob) {
        if (!file) {
          setStatusMessage('请重新选择文件后再开始新任务');
          return;
        }
        nextJob = await uploadSelectedFile(file, config);
        if (!nextJob) return;
      }
      const startedJob = await postJobAction(nextJob.job_id, 'start');
      setJob(startedJob);
      localStorage.setItem(CURRENT_JOB_KEY, startedJob.job_id);
      setConfig((current) => configFromJob(startedJob, current));
      setEventsVersion((current) => current + 1);
      setStatusMessage('任务已启动');
    } catch (error) {
      setStatusMessage(String(error));
    } finally {
      setIsBusy(false);
    }
  };

  const handleAction = async (action) => {
    if (!job?.job_id) return;
    if (action === 'resume' && apiConfigured === false) {
      openSettings();
      setStatusMessage('请先完成模型接口配置。');
      return;
    }
    setIsBusy(true);
    try {
      const nextJob = await postJobAction(job.job_id, action);
      localStorage.setItem(CURRENT_JOB_KEY, job.job_id);
      let latestJob = nextJob;
      if (action === 'resume') {
        latestJob = await fetchJob(job.job_id);
        setSegments(await fetchSegments(job.job_id));
      }
      setJob(latestJob);
      setConfig((current) => configFromJob(latestJob, current));
      if (action === 'resume') {
        setStatusMessage('任务已继续');
        setEventsVersion((current) => current + 1);
      }
      if (action === 'cancel') setStatusMessage('任务已停止');
    } catch (error) {
      setStatusMessage(String(error));
    } finally {
      setIsBusy(false);
    }
  };

  const handlePauseClick = async (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (!job?.job_id) return;
    setIsBusy(true);
    try {
      const nextJob = await postJobAction(
        job.job_id,
        'pause',
        { reason: 'user_click_pause' },
        { headers: { 'X-Manual-User-Action': 'true' } },
      );
      localStorage.setItem(CURRENT_JOB_KEY, job.job_id);
      setJob(nextJob);
      setConfig((current) => configFromJob(nextJob, current));
      setStatusMessage('正在暂停，将在当前段落完成后暂停');
    } catch (error) {
      setStatusMessage(String(error));
    } finally {
      setIsBusy(false);
    }
  };

  const handleRepairAndResume = async () => {
    if (!job?.job_id) return;
    if (apiConfigured === false) {
      openSettings();
      setStatusMessage('请先完成模型接口配置。');
      return;
    }
    setIsBusy(true);
    try {
      await postJobAction(job.job_id, 'repair-stuck');
      const nextJob = await postJobAction(job.job_id, 'resume');
      localStorage.setItem(CURRENT_JOB_KEY, job.job_id);
      setJob(nextJob);
      setSegments(await fetchSegments(job.job_id));
      setConfig((current) => configFromJob(nextJob, current));
      setEventsVersion((current) => current + 1);
      setStatusMessage('已修复并继续。');
    } catch (error) {
      setStatusMessage(String(error));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <main className="app-shell">
      <aside
        id="settings-panel"
        className={`settings-sidebar ${settingsOpen ? 'open' : ''}`}
        role={isMobileLayout ? 'dialog' : undefined}
        aria-label="配置"
        aria-modal={isMobileLayout && settingsOpen ? 'true' : undefined}
        aria-hidden={isMobileLayout && !settingsOpen ? 'true' : undefined}
      >
        <div className="sidebar-brand">
          <div className="brand-mark" aria-hidden="true">译</div>
          <div>
            <strong>长文翻译器</strong>
            <span>本地长文翻译工作台</span>
          </div>
          <button ref={settingsCloseRef} className="mobile-settings-close" type="button" aria-label="关闭配置" onClick={closeSettings}>×</button>
        </div>

        <ApiSettings
          onStatus={setStatusMessage}
          onAvailabilityChange={(configured) => {
            setApiConfigured(configured);
            if (!configured) openSettings();
          }}
        />

        {!isCompleted ? (
          <Toolbar config={config} onConfigChange={handleConfigChange} />
        ) : null}

        <p className="sidebar-note">配置与密钥只保存在这台电脑。开始翻译前不会向外部服务发送内容。</p>
      </aside>

      {settingsOpen ? <button className="settings-scrim" type="button" tabIndex={-1} aria-label="关闭配置" onClick={closeSettings} /> : null}

      <section className="workspace" inert={isMobileLayout && settingsOpen ? '' : undefined} aria-hidden={isMobileLayout && settingsOpen ? 'true' : undefined}>
        <header className="workspace-header">
          <div>
            <span className="section-kicker">翻译工作台</span>
            <h1>长文翻译</h1>
            <p>上传多语言文本，模型会自动识别原文语言，并按段落翻译成你选择的目标语言。</p>
          </div>
          <button
            ref={settingsToggleRef}
            className="mobile-settings-toggle"
            type="button"
            aria-controls="settings-panel"
            aria-expanded={settingsOpen}
            onClick={openSettings}
          >
            配置{apiConfigured === false ? ' · 待完善' : ''}
          </button>
          <div className="download-panel">
            <div className="download-heading">
              <span>导出结果</span>
              <small>{canDownload ? '当前结果可下载' : '完成、暂停或失败后可用'}</small>
            </div>
            <div className="download-row">
              {DOWNLOAD_OPTIONS.map(({ fileType, label }) => (
                <a
                  key={fileType}
                  className={`download-link ${canDownload ? '' : 'disabled'}`}
                  href={job?.job_id && canDownload ? buildDownloadUrl(job.job_id, fileType) : undefined}
                  target="_blank"
                  rel="noreferrer"
                >
                  {label.replace('下载', '')}
                </a>
              ))}
            </div>
          </div>
        </header>

        {hasAuthConfigError || apiConfigured === false ? (
          <div className="top-banner error-banner">
            <strong>{AUTH_FAILURE_MESSAGE}</strong>
            <span>填写模型接口的 URL、API Key 和模型名称，保存后即可开始或继续任务。</span>
            <button type="button" className="banner-action" onClick={openSettings}>打开配置</button>
          </div>
        ) : null}

        <DropZone
          file={file || (job?.file_name ? { name: job.file_name, size: 0 } : null)}
          disabled={isTaskLocked}
          onFileSelect={(nextFile) => {
            if (isTaskLocked) return;
            localStorage.removeItem(CURRENT_JOB_KEY);
            setFile(nextFile);
            setJob(null);
            setSegments([]);
            setSelectedId('');
            setActiveId('');
            setFollowCurrent(true);
            setStatusMessage(`已选择 ${nextFile.name}。原文语言将自动识别，确认目标语言后点击“开始翻译”。`);
          }}
        />

        {file || job ? (
          <div className="workspace-actions">
            {!canResume && !['running', 'pausing', 'paused'].includes(job?.status || 'pending') ? (
              <button className="primary-workspace-action" onClick={handleStart} disabled={!canStart || isBusy} type="button">
                {isBusy ? '准备中…' : '开始翻译'}
              </button>
            ) : null}
            {job?.status === 'running' ? (
              <button className="primary-workspace-action" onClick={handlePauseClick} disabled={isBusy} type="button">暂停</button>
            ) : null}
            {canResume ? (
              <button className="primary-workspace-action" onClick={() => handleAction('resume')} disabled={isBusy} type="button">继续</button>
            ) : null}
            {['running', 'pausing', 'paused', 'failed'].includes(job?.status || '') ? (
              <button className="secondary-button" onClick={() => handleAction('cancel')} disabled={isBusy} type="button">停止</button>
            ) : null}
            {!isTaskLocked ? (
              <button className="secondary-button" onClick={clearCurrentTask} type="button">
                新建任务
              </button>
            ) : null}
            {!isCompleted && canRepair ? (
              <button className="secondary-button" onClick={handleRepairAndResume} disabled={isBusy} type="button">
                修复并继续
              </button>
            ) : null}
          </div>
        ) : null}

        <CorpusPanel config={config} jobStatus={job?.status || 'pending'} onConfigChange={handleConfigChange} onStatus={setStatusMessage} />

        <ProgressPanel
          job={job}
          activeSegmentId={activeId}
          statusMessage={statusMessage}
          followCurrent={followCurrent}
          failedSegmentsCount={failedSegments.length}
          firstFailedSegmentId={firstFailedSegment?.segment_id || ''}
          selectedFailedError={selectedFailedSegment?.error || firstFailedSegment?.error || ''}
          onToggleFollowCurrent={() => setFollowCurrent((current) => !current)}
          onLocateCurrent={() => {
            const currentSegmentId = activeId || job?.current_segment_id;
            if (currentSegmentId) translationViewerRef.current?.locateCurrentSegment(currentSegmentId);
          }}
          onLocateFailed={() => {
            if (!firstFailedSegment?.segment_id) return;
            setSelectedId(firstFailedSegment.segment_id);
            translationViewerRef.current?.locateCurrentSegment(firstFailedSegment.segment_id);
            setStatusMessage(firstFailedSegment.error || `已定位失败段落 ${firstFailedSegment.segment_id}`);
          }}
        />

        <TranslationViewer
          ref={translationViewerRef}
          segments={segments}
          fileSelected={Boolean(job) || Boolean(file)}
          selectedId={selectedId}
          currentSegmentId={activeId || job?.current_segment_id || ''}
          followCurrent={followCurrent}
          status={job?.status || 'pending'}
          onSelect={(segmentId) => setSelectedId(segmentId)}
        />
      </section>
    </main>
  );
}
