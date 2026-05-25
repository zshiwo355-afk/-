import { useEffect, useRef, useState } from 'react';
import { buildDownloadUrl, fetchJob, fetchSegments, openJobEvents, postJobAction, uploadJob } from './api';
import DropZone from './components/DropZone';
import Toolbar from './components/Toolbar';
import ProgressPanel from './components/ProgressPanel';
import TranslationViewer from './components/TranslationViewer';

const AUTH_FAILURE_MESSAGE = 'TokenHub API Key 无效或 base_url/地域不匹配，请检查 backend/config.local.json';
const DEFAULT_CONFIG = {
  targetLanguageChoice: '简体中文',
  customTargetLanguage: '',
  translationMode: '忠实翻译',
  stream: true,
  chunkSizeChars: 3500,
};

const DOWNLOAD_TYPES = ['translated.md', 'bilingual.md', 'aligned.jsonl', 'translation_log.json'];

function resolveTargetLanguage(config) {
  if (config.targetLanguageChoice === '自定义') {
    return config.customTargetLanguage.trim() || '简体中文';
  }
  return config.targetLanguageChoice;
}

function isJobConfigCompatible(job, config) {
  if (!job?.config) {
    return false;
  }
  return (
    job.target_language === resolveTargetLanguage(config) &&
    job.config.translation_mode === config.translationMode &&
    job.config.stream === config.stream &&
    job.config.chunk_size_chars === config.chunkSizeChars
  );
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
  const translationViewerRef = useRef(null);

  const canStart = Boolean(file) || Boolean(job && !['completed', 'failed', 'cancelled'].includes(job.status));
  const hasAuthConfigError = job?.last_error?.includes(AUTH_FAILURE_MESSAGE);
  const hasIncompleteSegments = segments.some((segment) => segment.status !== 'success');
  const canResume = ['paused', 'failed'].includes(job?.status || '') && hasIncompleteSegments;

  const uploadSelectedFile = async (nextFile, configOverride = config) => {
    setIsBusy(true);
    setStatusMessage(`正在解析 ${nextFile.name}...`);
    try {
      const nextJob = await uploadJob(nextFile, {
        targetLanguage: resolveTargetLanguage(configOverride),
        translationMode: configOverride.translationMode,
        stream: configOverride.stream,
        chunkSizeChars: configOverride.chunkSizeChars,
      });
      const nextSegments = await fetchSegments(nextJob.job_id);
      setJob(nextJob);
      setSegments(nextSegments);
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
      onError: () => setStatusMessage('事件流重连中…'),
      onEvent: async (eventName, payload) => {
        if (eventName.startsWith('job_')) {
          if (payload.job_id || payload.status) {
            setJob((current) => ({ ...(current || {}), ...payload }));
          }
          if (eventName === 'job_pausing') {
            setStatusMessage('正在暂停，将在当前段落完成后暂停');
          }
          if (eventName === 'job_paused') {
            setStatusMessage('已暂停');
          }
          if (eventName === 'job_completed') {
            setStatusMessage('翻译完成，可以下载结果');
          }
          if (eventName === 'job_failed') {
            setStatusMessage(payload.last_error || '任务失败，可继续重试');
          }
          if (eventName === 'job_cancelled') {
            setStatusMessage('任务已停止');
          }
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
                ? {
                    ...segment,
                    status: 'running',
                    translated_text: `${segment.translated_text || ''}${payload.delta}`,
                  }
                : segment,
            ),
          );
        }

        if (eventName === 'segment_completed') {
          setSegments((current) =>
            current.map((segment) => (segment.segment_id === payload.segment_id ? payload : segment)),
          );
        }

        if (eventName === 'chunk_completed' || eventName === 'chunk_failed') {
          const jobId = currentJobIdRef.current;
          const latestSegments = await fetchSegments(jobId);
          const latestJob = await fetchJob(jobId);
          setSegments(latestSegments);
          setJob(latestJob);
        }
      },
    });

    return () => {
      eventSourceRef.current?.close();
    };
  }, [job?.job_id, eventsVersion]);

  const handleConfigChange = (key, value) => {
    setConfig((current) => ({ ...current, [key]: value }));
  };

  const handleStart = async () => {
    if (!file && !job) {
      return;
    }
    setIsBusy(true);
    try {
      let nextJob = job;
      const shouldCreateNewJob =
        !nextJob ||
        ['completed', 'failed', 'cancelled'].includes(nextJob.status) ||
        !isJobConfigCompatible(nextJob, config);
      if (shouldCreateNewJob) {
        if (!file) {
          setStatusMessage('请重新选择文件后再开始新任务');
          return;
        }
        nextJob = await uploadSelectedFile(file, config);
        if (!nextJob) {
          return;
        }
      }
      const startedJob = await postJobAction(nextJob.job_id, 'start');
      if (startedJob.ok === false) {
        setJob(startedJob);
        setStatusMessage(startedJob.message || '任务启动失败');
        return;
      }
      setJob(startedJob);
      setEventsVersion((current) => current + 1);
      setStatusMessage('任务已启动');
    } catch (error) {
      setStatusMessage(String(error));
    } finally {
      setIsBusy(false);
    }
  };

  const handleAction = async (action) => {
    if (!job?.job_id) {
      return;
    }
    if (action === 'resume' && hasAuthConfigError) {
      setStatusMessage('请先修复 backend/config.local.json 中的 API Key 或 base_url，再重新开始新任务。');
      return;
    }
    setIsBusy(true);
    try {
      const nextJob = await postJobAction(job.job_id, action);
      setJob(nextJob);
      if (nextJob.ok === false) {
        setStatusMessage(nextJob.message || '操作未执行');
        return;
      }
      if (action === 'pause') {
        setStatusMessage('正在暂停，将在当前段落完成后暂停');
      }
      if (action === 'resume') {
        setStatusMessage('任务已继续');
        setEventsVersion((current) => current + 1);
      }
      if (action === 'cancel') {
        setStatusMessage('任务已停止');
      }
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
            <p className="hero-copy">
              上传 TXT / MD，全书段落级对齐翻译，支持暂停、继续、断点续跑和结果导出。
            </p>
          </div>
          <div className="download-row">
            {DOWNLOAD_TYPES.map((fileType) => (
              <a
                key={fileType}
                className={`download-link ${job?.status === 'completed' || job?.status === 'failed' || job?.status === 'paused' ? '' : 'disabled'}`}
                href={job?.job_id ? buildDownloadUrl(job.job_id, fileType) : undefined}
                target="_blank"
                rel="noreferrer"
              >
                {fileType}
              </a>
            ))}
          </div>
        </div>

        {hasAuthConfigError ? (
          <div className="top-banner error-banner">
            <strong>{AUTH_FAILURE_MESSAGE}</strong>
            <span>修复 backend/config.local.json 或环境变量后，重新选择文件并点击“开始翻译”。</span>
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

        <Toolbar
          config={config}
          canStart={canStart && !isBusy}
          jobStatus={job?.status || 'pending'}
          resumeBlocked={hasAuthConfigError}
          canResume={canResume}
          onConfigChange={handleConfigChange}
          onStart={handleStart}
          onPause={() => handleAction('pause')}
          onResume={() => handleAction('resume')}
          onCancel={() => handleAction('cancel')}
        />

        <ProgressPanel
          job={job}
          activeSegmentId={activeId}
          statusMessage={statusMessage}
          followCurrent={followCurrent}
          onToggleFollowCurrent={() => setFollowCurrent((current) => !current)}
          onLocateCurrent={() => {
            const currentSegmentId = activeId || job?.current_segment_id;
            if (!currentSegmentId) {
              return;
            }
            translationViewerRef.current?.locateCurrentSegment(currentSegmentId);
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
