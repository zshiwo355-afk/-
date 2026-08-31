const STATUS_LABELS = {
  pending: '待开始',
  running: '翻译中',
  pausing: '暂停中',
  paused: '已暂停',
  completed: '已完成',
  failed: '需重试',
  cancelled: '已停止',
};

export default function ProgressPanel({
  job,
  activeSegmentId,
  statusMessage,
  followCurrent,
  onToggleFollowCurrent,
  onLocateCurrent,
  failedSegmentsCount,
  firstFailedSegmentId,
  selectedFailedError,
  onLocateFailed,
}) {
  const progress = job?.total_segments
    ? Math.round((job.completed_segments / job.total_segments) * 100)
    : 0;
  const completedMessage = job?.status === 'completed'
    ? `翻译完成：${job.completed_segments || 0} / ${job.total_segments || 0}`
    : statusMessage || '等待任务开始';

  return (
    <section className="progress-card" aria-live="polite">
      <div className="progress-head">
        <div>
          <h2>任务状态</h2>
          <p>{completedMessage}</p>
        </div>
        <div className="progress-pill">{STATUS_LABELS[job?.status || 'pending'] || job?.status}</div>
      </div>

      {job ? (
        <>
          <div className="progress-bar" role="progressbar" aria-label="翻译进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow={progress}>
            <div className="progress-bar-fill" style={{ width: `${progress}%` }} />
          </div>

          <div className="progress-actions">
            <button type="button" className="secondary-button" onClick={onToggleFollowCurrent}>
              自动跟随：{followCurrent ? '开启' : '关闭'}
            </button>
            <button type="button" className="secondary-button" onClick={onLocateCurrent} disabled={!activeSegmentId && !job.current_segment_id}>
              定位当前段落
            </button>
            <button type="button" className="secondary-button" onClick={onLocateFailed} disabled={!firstFailedSegmentId}>
              定位失败段落
            </button>
          </div>

          <div className="progress-grid">
            <div>
              <span>当前章节</span>
              <strong>{job.current_chapter || '-'}</strong>
            </div>
            <div>
              <span>完成进度</span>
              <strong>{job.completed_segments || 0} / {job.total_segments || 0}</strong>
            </div>
            <div>
              <span>失败数</span>
              <strong>{failedSegmentsCount || 0}</strong>
            </div>
            <div>
              <span>当前段落</span>
              <strong>{activeSegmentId || job.current_segment_id || '-'}</strong>
            </div>
            <div className="progress-full">
              <span>最近错误</span>
              <strong>{selectedFailedError || job.last_error || '-'}</strong>
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
}
