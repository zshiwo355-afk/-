import { useRef, useState } from 'react';

export default function DropZone({ file, onFileSelect }) {
  const inputRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);

  const handleFiles = (files) => {
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
    <section
      className={`drop-zone ${isDragging ? 'dragging' : ''}`}
      onDragOver={(event) => {
        event.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setIsDragging(false);
        handleFiles(event.dataTransfer.files);
      }}
      onClick={() => inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        className="hidden-input"
        type="file"
        accept=".txt,.md"
        onChange={(event) => handleFiles(event.target.files)}
      />
      <div className="drop-zone-title">拖拽英文 TXT / MD 书籍到这里</div>
      <div className="drop-zone-subtitle">或点击选择文件，然后开始整本翻译</div>
      {file ? (
        <div className="drop-zone-file">
          <strong>{file.name}</strong>
          <span>{(file.size / 1024).toFixed(1)} KB</span>
        </div>
      ) : null}
    </section>
  );
}

