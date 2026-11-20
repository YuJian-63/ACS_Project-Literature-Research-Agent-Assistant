import { useEffect, useRef, useState } from 'react';
import { Button, Spin } from 'antd';
import { ArrowLeftOutlined, CloseOutlined, FilePdfOutlined, FullscreenExitOutlined, FullscreenOutlined, SelectOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { api, ApiError, asApiError, isCanceled, paperFileUrl } from '../../../api/client';
import type { Paper } from '../../../api/types';
import { t, useLocale } from '../../../i18n';
import { ErrorNotice } from '../../../shared/components/ErrorNotice';
import './paper-reader.css';
import PaperDeleteButton from './PaperDeleteButton';

type DocumentState = { kind: 'loading' } | { kind: 'ready'; url: string } | { kind: 'error'; error: ApiError };

export default function PaperReader({ paper, papers, page = 1, returnToResearch, expanded, onRead, onExpand, onClose, onDelete, deletingId }: {
  paper: Paper;
  papers: Paper[];
  page?: number;
  returnToResearch?: string;
  expanded: boolean;
  onRead: (paper: Paper) => void;
  onExpand: () => void;
  onClose: () => void;
  onDelete?: (paper: Paper) => Promise<void>;
  deletingId?: string | null;
}) {
  useLocale();
  const navigate = useNavigate();
  const heading = useRef<HTMLHeadingElement>(null);
  const panel = useRef<HTMLElement>(null);
  const [documentState, setDocumentState] = useState<DocumentState>({ kind: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const options = papers.some((item) => item.id === paper.id) ? papers : [paper, ...papers];

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      heading.current?.focus({ preventScroll: true });
      panel.current?.scrollIntoView({ block: 'start' });
    });
    return () => cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | undefined;
    setDocumentState({ kind: 'loading' });
    async function load() {
      try {
        const file = await api.paperFile(paper.id, controller.signal);
        const signature = await file.slice(0, 5).text();
        if (controller.signal.aborted) return;
        if (signature !== '%PDF-') throw new ApiError('返回的文件不是有效的 PDF，请重试或在新标签页打开。', 'INVALID_PDF_FILE');
        objectUrl = URL.createObjectURL(new Blob([file], { type: 'application/pdf' }));
        setDocumentState({ kind: 'ready', url: objectUrl });
      } catch (error) {
        if (!controller.signal.aborted && !isCanceled(error)) setDocumentState({ kind: 'error', error: asApiError(error) });
      }
    }
    void load();
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [paper.id, attempt]);

  return <section ref={panel} className="paper-reader" aria-labelledby="paper-reader-title">
    <header className="paper-reader-header">
      <div className="paper-reader-heading"><FilePdfOutlined aria-hidden="true" /><div>
        <h2 id="paper-reader-title" ref={heading} tabIndex={-1} title={paper.title}>{paper.title}</h2>
        <p><span>{paper.original_filename}</span>{paper.page_count !== null && <span>{t('{0} 页', [paper.page_count])}</span>}</p>
      </div></div>
      <div className="paper-reader-actions">
        {onDelete && <PaperDeleteButton paper={paper} onDelete={onDelete} deletingId={deletingId} />}
        {returnToResearch && <Button type="primary" className="reader-task-return" icon={<ArrowLeftOutlined aria-hidden="true" />} onClick={() => navigate(returnToResearch)}>{t('返回研究')}</Button>}
        <Button className="reader-expand" icon={expanded ? <FullscreenExitOutlined aria-hidden="true" /> : <FullscreenOutlined aria-hidden="true" />} onClick={onExpand}>{expanded ? t('显示论文列表') : t('专注阅读')}</Button>
        <Button href={paperFileUrl(paper.id, page)} target="_blank" rel="noopener noreferrer" icon={<SelectOutlined aria-hidden="true" />}>{t('在新标签页打开')}</Button>
        <Button icon={<CloseOutlined aria-hidden="true" />} aria-label={t('关闭阅读')} title={t('返回论文库')} onClick={onClose} />
      </div>
    </header>
    <div className="paper-reader-switch">
      <label htmlFor="reader-paper-select">{t('切换论文')}</label>
      <select id="reader-paper-select" value={paper.id} onChange={(event) => {
        const next = options.find((item) => item.id === event.target.value);
        if (next) onRead(next);
      }}>{options.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select>
    </div>
    <div className="paper-reader-document" aria-busy={documentState.kind === 'loading'}>
      {documentState.kind === 'loading' && <div className="paper-reader-state" role="status"><Spin /><p>{t('正在加载 PDF…')}</p></div>}
      {documentState.kind === 'error' && <div className="paper-reader-state"><ErrorNotice title={t('无法加载 PDF')} error={documentState.error} retry={() => setAttempt((value) => value + 1)} /></div>}
      {documentState.kind === 'ready' && <iframe title={t('PDF 原文：{0}', [paper.title])} src={documentState.url + '#page=' + page + '&view=Fit'} referrerPolicy="no-referrer" />}
    </div>
    <footer className="paper-reader-footer"><span>{t('原文未显示？可使用上方的新标签页打开。')}</span><Button type="link" onClick={onClose}>{t('返回论文库')}</Button></footer>
  </section>;
}
