import { t, useLocale } from '../i18n';
import { useCallback, useEffect, useRef, useState, type Key } from 'react';
import { App, Button, Input, Select, Skeleton } from 'antd';
import { ArrowRightOutlined, ReloadOutlined } from '@ant-design/icons';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { Paper, PaperStatus } from '../api/types';
import { ErrorNotice, PageHeader, PaginationBar } from '../components/Common';
import { canSelectPaper, hasPendingPapers, PaperTable } from '../components/PaperTable';
import { PaperUpload } from '../components/PaperUpload';
import PaperReader from '../components/papers/PaperReader';
import PaperReadingList from '../components/papers/PaperReadingList';
import { useResource } from '../hooks/useResource';
import { paperStatusLabels } from '../lib/format';

export default function PapersPage() {
  useLocale();
  const { message } = App.useApp();
  const [readerParameters, setReaderParameters] = useSearchParams();
  const readingPaperId = readerParameters.get('paper_id')?.toLowerCase() || '';
  const selected = [...new Set(readerParameters.getAll('selected_paper_id').map((id) => id.toLowerCase()).filter(Boolean))].slice(0, 20);
  const [query, setQuery] = useState('');
  const [draft, setDraft] = useState('');
  const [status, setStatus] = useState<PaperStatus>();
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState(false);
  const libraryPanel = useRef<HTMLElement>(null);
  const libraryHeading = useRef<HTMLHeadingElement>(null);
  const closedPaperId = useRef<string | null>(null);
  const load = useCallback((signal: AbortSignal) => api.papers({ q: query || undefined, status, limit: 20, offset: (page - 1) * 20 }, signal), [page, query, status]);
  const resource = useResource(load, 2000, hasPendingPapers);
  const loadReadingPaper = useCallback((signal: AbortSignal) => readingPaperId ? api.paper(readingPaperId, signal) : Promise.resolve(null), [readingPaperId]);
  const readerResource = useResource(loadReadingPaper);
  const readingPaper = readerResource.data?.id === readingPaperId ? readerResource.data : null;
  const parameters = new URLSearchParams();
  selected.forEach((id) => parameters.append('paper_id', id));
  const papers = resource.data?.items || [];
  const emptyMessage = query || status ? t('没有匹配的论文，请调整筛选条件') : t('还没有论文，上传第一篇 PDF 开始研究');
  useEffect(() => {
    if (readingPaperId || closedPaperId.current === null) return;
    const frame = requestAnimationFrame(() => {
      const paperId = closedPaperId.current;
      const trigger = paperId ? libraryPanel.current?.querySelector<HTMLButtonElement>('button[data-paper-id="' + CSS.escape(paperId) + '"]') : null;
      (trigger || libraryHeading.current)?.focus();
      closedPaperId.current = null;
    });
    return () => cancelAnimationFrame(frame);
  }, [readingPaperId]);
  function changeSelection(keys: Key[]) {
    if (keys.length > 20) { void message.warning(t('最多可选择 20 篇论文。')); return; }
    const next = new URLSearchParams(readerParameters);
    next.delete('selected_paper_id');
    [...new Set(keys.map(String))].forEach((id) => next.append('selected_paper_id', id));
    setReaderParameters(next, { replace: true });
  }
  function openReader(paper: Paper) {
    const next = new URLSearchParams(readerParameters);
    next.set('paper_id', paper.id);
    setReaderParameters(next, { replace: Boolean(readingPaperId) });
  }
  function closeReader() {
    closedPaperId.current = readingPaper?.id || '';
    const next = new URLSearchParams(readerParameters);
    next.delete('paper_id');
    setReaderParameters(next, { replace: true });
    setExpanded(false);
  }

  return <>
    <PageHeader title={t("论文库")} description={t("让每一次研究，从可信的原始资料开始。")} action={<Link to={`/tasks/new${selected.length ? `?${parameters}` : ''}`}><Button type="primary" icon={<ArrowRightOutlined />} iconPlacement="end">{t("新建研究")}</Button></Link>} />
    {readingPaperId && !readingPaper && <section className="content-panel">{readerResource.error ? <><ErrorNotice error={readerResource.error} retry={readerResource.reload} /><Button onClick={closeReader}>{t('返回论文库')}</Button></> : <Skeleton active paragraph={{ rows: 3 }} />}</section>}
    <div hidden={Boolean(readingPaperId)}><PaperUpload onUploaded={() => { setQuery(''); setDraft(''); setStatus(undefined); setPage(1); resource.reload(); }} /></div>
    <div className={'library-workspace' + (readingPaper ? ' is-reading' : '') + (expanded ? ' is-expanded' : '')}>
    <section ref={libraryPanel} className="content-panel library-panel">
      <div className="panel-heading"><div><h2 ref={libraryHeading} tabIndex={-1}>{t("我的论文")}</h2><p>{readingPaper ? t('点击标题切换原文，勾选论文可继续创建研究。') : t("选择论文后可创建摘要、问答或跨论文综述任务。")}</p></div><Button icon={<ReloadOutlined />} onClick={resource.reload} loading={resource.loading}>{t("刷新")}</Button></div>
      <div className="filter-toolbar">
        <Input.Search value={draft} placeholder={t("搜索标题或文件名")} aria-label={t("搜索论文")} maxLength={200} allowClear onChange={(event) => { setDraft(event.target.value); if (!event.target.value) { setQuery(''); setPage(1); } }} onSearch={(value) => { setQuery(value); setPage(1); }} />
        <Select<PaperStatus> value={status} onChange={(value) => { setStatus(value); setPage(1); }} allowClear placeholder={t("全部状态")} aria-label={t("筛选论文状态")} options={Object.entries(paperStatusLabels()).map(([value, label]) => ({ value: value as PaperStatus, label }))} />
      </div>
      {selected.length > 0 && <div className="selection-notice"><span>{t("已选择")}<strong>{selected.length}</strong>{t("篇论文，可跨页继续选择")}</span><Button type="link" onClick={() => changeSelection([])}>{t("清空选择")}</Button></div>}
      {resource.error && <ErrorNotice error={resource.error} retry={resource.reload} />}
      {readingPaper ? <PaperReadingList papers={papers} activeId={readingPaper.id} selectedIds={selected} loading={resource.loading} emptyMessage={emptyMessage} onRead={openReader} onSelect={(paper, checked) => {
        changeSelection(checked ? [...selected, paper.id] : selected.filter((id) => id !== paper.id));
      }} /> : <PaperTable papers={papers} loading={resource.loading} emptyMessage={emptyMessage} onOpenPaper={openReader} selection={{
        selectedRowKeys: selected, preserveSelectedRowKeys: true,
        onChange: changeSelection,
        getCheckboxProps: (paper) => ({ disabled: !canSelectPaper(paper) || (selected.length >= 20 && !selected.includes(paper.id)), 'aria-label': t("选择论文 {0}", [paper.title]) }),
      }} />}
      {resource.data && <PaginationBar total={resource.data.total} page={page} onChange={setPage} />}
    </section>
    {readingPaper && <PaperReader key={readingPaper.id} paper={papers.find((paper) => paper.id === readingPaper.id) || readingPaper} papers={papers} expanded={expanded} onRead={openReader} onExpand={() => setExpanded((value) => !value)} onClose={closeReader} />}
    </div>
    {!readingPaper && <div className="page-tip"><strong>{t("关于资料与分析")}</strong><span>{t("启动解析 Worker 后会自动提取文本，扫描件暂不支持。解析就绪不代表已完成研究分析；重复上传会生成独立记录。")}</span></div>}
  </>;
}
