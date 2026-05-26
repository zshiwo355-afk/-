import { useEffect, useRef, useState } from 'react';
import { buildDownloadUrl, fetchJob, fetchSegments, openJobEvents, postJobAction, uploadJob } from './api';
import DropZone from './components/DropZone';
import Toolbar from './components/Toolbar';
import ProgressPanel from './components/ProgressPanel';
import TranslationViewer from './components/TranslationViewer';
import CorpusPanel from './components/CorpusPanel';

const AUTH_FAILURE_MESSAGE = 'TokenHub API Key 无效或 base_url/域名不匹配，请检查 backend/config.local.json';
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
  translateMode: 'psychology',
  translationLevel: 3,
  speedMode: 'stable',
};

const DOWNLOAD_TYPES = ['translated.txt', 'translated.md', 'bilingual.txt', 'bilingual.md'];
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
    translateMode: job.config.translate_mode || 'psychology',
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
  const eventSourceRef = useRef(null);
  const currentJobIdRef = useRef('');
  const lastSegmentsFetchAtRef = useRef(0);
  const pendingSegmentsFetchRef = useRef(null);
  const translationViewerRef = useRef(null);

  const canStart = Boolean(file) || Boolean(job && !['completed', 'failed', 'cancelled'].includes(job.status));
  const hasAuthConfigError = job?.last_error?.includes(AUTH_FAILURE_MESSAGE);
  const hasIncompleteSegments = segments.some((segment) => segment.status !== 'success');
  const canResume = ['paused', 'failed'].includes(job?.status || '') && hasIncompleteSegments;
  const canRepair = Boolean(job?.job_id) && ['running', 'pausing', 'paused', 'failed'].includes(job?.status || '') && hasIncompleteSegments;
  const isCompleted = job?.status === 'completed';

  const handleConfigChange = (key, value) => setConfig((current) => ({ ...current, [key]: value }));

  const restoreJob = async (jobId) => {
    try {
      const restoredJob = await fetchJob(jobId);
      const restoredSegments = await fetchSegments(jobId);
      localStorage.setItem(CURRENT_JOB_KEY, jobId);
      currentJobIdRef.current = jobId;
      setJob(restoredJob);
      setSegments(restoredSegments);
      setFile({ name: restoredJob.file_name, size: 0 });
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
    const savedJobId = localStorage.getItem(CURRENT_JOB_KEY) || 'job_b833f6476598';
    if (savedJobId) {
      restoreJob(savedJobId);
    }
  }, []);

  const clearCurrentTask = () => {
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
    setIsBusy(true);
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
    } finally {
      setIsBusy(false);
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
    console.trace('[pause-click] user clicked pause');
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
      <section className="app-top">
        <div className="hero">
          <div>
            <p className="eyebrow">text-book-translator</p>
            <h1>本地英文书籍翻译工具</h1>
            <p className="hero-copy">上传 TXT / MD，按段落对齐翻译，支持语料库、暂停、继续和结果导出。</p>
          </div>
          <div className="download-row">
            {DOWNLOAD_TYPES.map((fileType) => (
              <a key={fileType} className={`download-link ${isCompleted ? '' : 'disabled'}`} href={job?.job_id && isCompleted ? buildDownloadUrl(job.job_id, fileType) : undefined} target="_blank" rel="noreferrer">
                {fileType}
              </a>
            ))}
          </div>
        </div>

        {hasAuthConfigError ? (
          <div className="top-banner error-banner">
            <strong>{AUTH_FAILURE_MESSAGE}</strong>
            <span>修复配置后，直接点击“继续”重试失败段落。</span>
          </div>
        ) : null}

        <DropZone
          file={file}
          onFileSelect={async (nextFile) => {
            setFile(nextFile);
            setJob(null);
            setSegments([]);
            setSelectedId('');
            setActiveId('');
            setFollowCurrent(true);
            await uploadSelectedFile(nextFile);
          }}
        />

        {!isCompleted ? (
          <Toolbar
            config={config}
            canStart={canStart && !isBusy}
            jobStatus={job?.status || 'pending'}
            resumeBlocked={false}
            canResume={canResume}
            onConfigChange={handleConfigChange}
            onStart={handleStart}
            onPause={handlePauseClick}
            onResume={() => handleAction('resume')}
            onCancel={() => handleAction('cancel')}
          />
        ) : null}

        <div className="progress-actions">
          <button className="secondary-button" onClick={clearCurrentTask} type="button">
            娓呴櫎褰撳墠浠诲姟 / 鏂板缓浠诲姟
          </button>
          {!isCompleted ? (
            <button className="secondary-button" onClick={handleRepairAndResume} disabled={!canRepair || isBusy} type="button">
              修复并继续
            </button>
          ) : null}
        </div>

        <CorpusPanel config={config} jobStatus={job?.status || 'pending'} onConfigChange={handleConfigChange} onStatus={setStatusMessage} />

        <ProgressPanel
          job={job}
          activeSegmentId={activeId}
          statusMessage={statusMessage}
          followCurrent={followCurrent}
          onToggleFollowCurrent={() => setFollowCurrent((current) => !current)}
          onLocateCurrent={() => {
            const currentSegmentId = activeId || job?.current_segment_id;
            if (currentSegmentId) translationViewerRef.current?.locateCurrentSegment(currentSegmentId);
          }}
        />
      </section>

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
    </main>
  );
}

