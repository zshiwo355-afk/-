import { useRef, useState } from 'react';

export default function DropZone({ file, onFileSelect, disabled = false }) {
  const inputRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);

  const handleFiles = (files) => {
    if (disabled) {
      return;
    }
    const nextFile = files?.[0];
    if (!nextFile) {
      return;
    }
    const ext = nextFile.name.toLowerCase();
    if (!ext.endsWith('.txt') && !ext.endsWith('.md')) {
      window.alert('只支持 .txt 和 .md 文件');
      return;
    }
    onFileSelect(nextFile);
  };

  return (
    <>
      <input
        ref={inputRef}
        className="hidden-input"
        type="file"
        accept=".txt,.md"
        disabled={disabled}
        onChange={(event) => {
          handleFiles(event.target.files);
          event.target.value = '';
        }}
      />
      <button
        type="button"
        className={`drop-zone ${isDragging ? 'dragging' : ''}`}
        aria-label={disabled ? '任务进行中，停止后才能选择新文件' : '选择 TXT 或 MD 文件'}
        disabled={disabled}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          handleFiles(event.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
      >
        <div className="drop-zone-title">拖拽 TXT / MD 书籍到这里</div>
        <div className="drop-zone-subtitle">
          {disabled ? '当前任务结束或停止后，可以选择新文件' : '支持多语言，翻译时自动识别原文语言'}
        </div>
        {file ? (
          <div className="drop-zone-file">
            <strong>{file.name}</strong>
            <span>{file.size ? `${(file.size / 1024).toFixed(1)} KB` : '已恢复任务'}</span>
          </div>
        ) : null}
      </button>
    </>
  );
}
