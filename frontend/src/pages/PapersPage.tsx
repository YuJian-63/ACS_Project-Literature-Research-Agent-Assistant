import { useCallback, useState } from 'react';
import { App, Button, Input, Select } from 'antd';
import { ArrowRightOutlined, ReloadOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { Paper, PaperStatus } from '../api/types';
import { ErrorNotice, PageHeader, PaginationBar } from '../components/Common';
import { canSelectPaper, hasPendingPapers, PaperTable, selectedPaperRows } from '../components/PaperTable';
import { PaperUpload } from '../components/PaperUpload';
import { useResource } from '../hooks/useResource';
import { paperStatusLabels } from '../lib/format';

export default function PapersPage() {
  const { message } = App.useApp();
  const [query, setQuery] = useState('');
  const [draft, setDraft] = useState('');
  const [status, setStatus] = useState<PaperStatus>();
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Paper[]>([]);
  const load = useCallback((signal: AbortSignal) => api.papers({ q: query || undefined, status, limit: 20, offset: (page - 1) * 20 }, signal), [page, query, status]);
  const resource = useResource(load, 2000, hasPendingPapers);
  const parameters = new URLSearchParams();
  selected.forEach((paper) => parameters.append('paper_id', paper.id));

  return <>
    <PageHeader title="论文库" description="让每一次研究，从可信的原始资料开始。" action={<Link to={`/tasks/new${selected.length ? `?${parameters}` : ''}`}><Button type="primary" icon={<ArrowRightOutlined />} iconPlacement="end">新建任务</Button></Link>} />
    <PaperUpload onUploaded={() => { setQuery(''); setDraft(''); setStatus(undefined); setPage(1); resource.reload(); }} />
    <section className="content-panel">
      <div className="panel-heading"><div><h2>我的论文</h2><p>选择论文后可创建摘要、问答或跨论文综述任务。</p></div><Button icon={<ReloadOutlined />} onClick={resource.reload} loading={resource.loading}>刷新</Button></div>
      <div className="filter-toolbar">
        <Input.Search value={draft} placeholder="搜索标题或文件名" aria-label="搜索论文" maxLength={200} allowClear onChange={(event) => { setDraft(event.target.value); if (!event.target.value) { setQuery(''); setPage(1); } }} onSearch={(value) => { setQuery(value); setPage(1); }} />
        <Select<PaperStatus> value={status} onChange={(value) => { setStatus(value); setPage(1); }} allowClear placeholder="全部状态" aria-label="筛选论文状态" options={Object.entries(paperStatusLabels).map(([value, label]) => ({ value: value as PaperStatus, label }))} />
      </div>
      {selected.length > 0 && <div className="selection-notice"><span>已选择 <strong>{selected.length}</strong> 篇论文，可跨页继续选择</span><Button type="link" onClick={() => setSelected([])}>清空选择</Button></div>}
      {resource.error && <ErrorNotice error={resource.error} retry={resource.reload} />}
      <PaperTable papers={resource.data?.items || []} loading={resource.loading} emptyMessage={query || status ? '没有匹配的论文，请调整筛选条件' : '还没有论文，上传第一篇 PDF 开始研究'} selection={{
        selectedRowKeys: selected.map((paper) => paper.id), preserveSelectedRowKeys: true,
        onChange: (keys) => {
          if (keys.length > 20) { void message.warning('最多可选择 20 篇论文。'); return; }
          setSelected(selectedPaperRows(keys, selected, resource.data?.items || []));
        },
        getCheckboxProps: (paper) => ({ disabled: !canSelectPaper(paper) || (selected.length >= 20 && !selected.some((item) => item.id === paper.id)), 'aria-label': `选择论文 ${paper.title}` }),
      }} />
      {resource.data && <PaginationBar total={resource.data.total} page={page} onChange={setPage} />}
    </section>
    <div className="page-tip"><strong>关于资料与分析</strong><span>启动解析 Worker 后会自动提取文本，扫描件暂不支持。解析就绪不代表已完成研究分析；重复上传会生成独立记录。</span></div>
  </>;
}
