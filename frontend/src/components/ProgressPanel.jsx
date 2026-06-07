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
    <section className="progress-card">
      <div className="progress-head">
        <div>
          <h2>任务状态</h2>
          <p>{completedMessage}</p>
        </div>
        <div className="progress-pill">{job?.status || 'pending'}</div>
      </div>

      <div className="progress-bar">
        <div className="progress-bar-fill" style={{ width: `${progress}%` }} />
      </div>

      <div className="progress-actions">
        <button type="button" className="secondary-button" onClick={onToggleFollowCurrent}>
          自动跟随当前翻译：{followCurrent ? '开启' : '关闭'}
        </button>
        <button
          type="button"
          className="secondary-button"
          onClick={onLocateCurrent}
          disabled={!activeSegmentId && !job?.current_segment_id}
        >
          定位当前翻译
        </button>
        <button
          type="button"
          className="secondary-button"
          onClick={onLocateFailed}
          disabled={!firstFailedSegmentId}
        >
          定位首个失败
        </button>
      </div>

      <div className="progress-grid">
        <div>
          <span>当前章节</span>
          <strong>{job?.current_chapter || '-'}</strong>
        </div>
        <div>
          <span>完成进度</span>
          <strong>
            {job?.completed_segments || 0} / {job?.total_segments || 0}
          </strong>
        </div>
        <div>
          <span>失败数</span>
          <strong>{failedSegmentsCount || 0}</strong>
        </div>
        <div>
          <span>当前 Segment</span>
          <strong>{activeSegmentId || job?.current_segment_id || '-'}</strong>
        </div>
        <div className="progress-full">
          <span>最近错误</span>
          <strong>{selectedFailedError || job?.last_error || '-'}</strong>
        </div>
      </div>
    </section>
  );
}
