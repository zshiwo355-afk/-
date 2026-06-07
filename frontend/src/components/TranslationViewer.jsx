import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';

function buildTargetContent(segment) {
  if (segment.status === 'failed') {
    return segment.translated_text || '该段翻译失败';
  }
  if (segment.status === 'success') {
    return segment.translated_text;
  }
  if (segment.status === 'running' || segment.status === 'partial') {
    return segment.translated_text || '正在翻译...';
  }
  return '等待翻译';
}

function scrollSegmentInContainer(container, target) {
  if (!container || !target) {
    return;
  }

  const containerRect = container.getBoundingClientRect();
  const targetRect = target.getBoundingClientRect();
  const top =
    targetRect.top -
    containerRect.top +
    container.scrollTop -
    container.clientHeight / 2 +
    target.clientHeight / 2;

  container.scrollTo({
    top,
    behavior: 'smooth',
  });
}

function EmptyPaneCard({ text }) {
  return (
    <div className="segment-card empty-card">
      <pre>{text}</pre>
    </div>
  );
}

const TranslationViewer = forwardRef(function TranslationViewer({
  segments,
  fileSelected,
  selectedId,
  currentSegmentId,
  followCurrent,
  status,
  onSelect,
}, ref) {
  const sourceScrollRef = useRef(null);
  const targetScrollRef = useRef(null);
  const sourceSegmentRefs = useRef({});
  const targetSegmentRefs = useRef({});

  const locateSegment = (segmentId) => {
    if (!segmentId) {
      return false;
    }
    const sourceNode = sourceSegmentRefs.current[segmentId];
    const targetNode = targetSegmentRefs.current[segmentId];
    if (!sourceNode && !targetNode) {
      return false;
    }
    scrollSegmentInContainer(sourceScrollRef.current, sourceNode);
    scrollSegmentInContainer(targetScrollRef.current, targetNode);
    return true;
  };

  useImperativeHandle(ref, () => ({
    locateCurrentSegment(segmentId) {
      return locateSegment(segmentId);
    },
  }));

  useEffect(() => {
    if (!followCurrent || !currentSegmentId) {
      return;
    }
    locateSegment(currentSegmentId);
  }, [currentSegmentId, followCurrent]);

  const handleSourceSelect = (segmentId) => {
    onSelect(segmentId);
    scrollSegmentInContainer(targetScrollRef.current, targetSegmentRefs.current[segmentId]);
  };

  const handleTargetSelect = (segmentId) => {
    onSelect(segmentId);
    scrollSegmentInContainer(sourceScrollRef.current, sourceSegmentRefs.current[segmentId]);
  };

  return (
    <section className="translation-shell">
      <div className="translation-pane source-pane">
        <div className="translation-pane-header">原文</div>
        <div ref={sourceScrollRef} className="translation-pane-body source-body">
          {segments.length === 0 && !fileSelected ? (
            <EmptyPaneCard text="请先拖拽或选择 TXT / MD 文件" />
          ) : null}

          {segments.length === 0 && fileSelected ? (
            <EmptyPaneCard text="正在解析文件..." />
          ) : null}

          {segments.map((segment) => {
            const cardClasses = [
              'segment-card',
              segment.segment_id === selectedId ? 'selected' : '',
              segment.segment_id === currentSegmentId ? 'current' : '',
              segment.status === 'failed' ? 'failed' : '',
            ]
              .filter(Boolean)
              .join(' ');

            return (
              <button
                key={`source-${segment.segment_id}`}
                type="button"
                ref={(node) => {
                  if (node) {
                    sourceSegmentRefs.current[segment.segment_id] = node;
                  } else {
                    delete sourceSegmentRefs.current[segment.segment_id];
                  }
                }}
                data-segment-id={segment.segment_id}
                className={cardClasses}
                onClick={() => handleSourceSelect(segment.segment_id)}
              >
                <div className="segment-meta">
                  <span>{segment.segment_id}</span>
                  <span>{segment.chapter_title || '正文'}</span>
                </div>
                <pre>{segment.source_text}</pre>
              </button>
            );
          })}
        </div>
      </div>

      <div className="translation-pane target-pane">
        <div className="translation-pane-header">译文</div>
        <div ref={targetScrollRef} className="translation-pane-body target-body">
          {segments.length === 0 && !fileSelected ? (
            <EmptyPaneCard text="翻译开始后将在这里显示译文" />
          ) : null}

          {segments.length === 0 && fileSelected ? (
            <EmptyPaneCard text={status === 'running' ? '正在准备翻译...' : '等待开始翻译...'} />
          ) : null}

          {segments.map((segment) => {
            const cardClasses = [
              'segment-card',
              segment.segment_id === selectedId ? 'selected' : '',
              segment.segment_id === currentSegmentId ? 'current' : '',
              segment.status === 'failed' ? 'failed' : '',
            ]
              .filter(Boolean)
              .join(' ');

            return (
              <button
                key={`target-${segment.segment_id}`}
                type="button"
                ref={(node) => {
                  if (node) {
                    targetSegmentRefs.current[segment.segment_id] = node;
                  } else {
                    delete targetSegmentRefs.current[segment.segment_id];
                  }
                }}
                data-segment-id={segment.segment_id}
                className={cardClasses}
                onClick={() => handleTargetSelect(segment.segment_id)}
              >
                <div className="segment-meta">
                  <span>{segment.segment_id}</span>
                  <span>{segment.status}</span>
                </div>
                <pre>{buildTargetContent(segment)}</pre>
                {segment.status === 'failed' ? (
                  <div className="segment-error">
                    <strong>失败原因：</strong>
                    <span>{segment.error || '未记录具体错误，可尝试继续重试。'}</span>
                  </div>
                ) : null}
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
});

export default TranslationViewer;
