import { useCallback, useState } from 'react';
import { App, Input, Tag } from 'antd';
import { api } from '../api/client';
import type { Paper } from '../api/types';
import { useResource } from '../hooks/useResource';
import { ErrorNotice, PaginationBar } from './Common';
import { canSelectPaper, PaperTable, selectedPaperRows } from './PaperTable';

export function PaperPicker({ value, onChange, disabled }: { value: Paper[]; onChange: (papers: Paper[]) => void; disabled: boolean }) {
  const { message } = App.useApp();
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const load = useCallback((signal: AbortSignal) => api.papers({ limit: 20, offset: (page - 1) * 20, q: query || undefined }, signal), [page, query]);
  const resource = useResource(load);
  const keys = value.map((paper) => paper.id);
  return <div className="paper-picker">
    <div className="picker-toolbar"><Input.Search placeholder="搜索已上传论文" aria-label="搜索待选论文" maxLength={200} allowClear disabled={disabled} onSearch={(text) => { setQuery(text); setPage(1); }} /><span>已选 {value.length} / 20 篇</span></div>
    {value.length > 0 && <div className="selected-papers" aria-label="已选论文">{value.map((paper) => <Tag key={paper.id} closable={!disabled} onClose={() => onChange(value.filter((item) => item.id !== paper.id))}>{paper.title}</Tag>)}</div>}
    {resource.error && <ErrorNotice error={resource.error} retry={resource.reload} />}
    <PaperTable papers={resource.data?.items || []} loading={resource.loading} scrollHeight={400} emptyMessage={query ? '没有匹配的论文' : '请先在论文库上传 PDF'} selection={{
      selectedRowKeys: keys,
      preserveSelectedRowKeys: true,
      onChange: (chosen) => {
        if (chosen.length > 20) { void message.warning('最多可选择 20 篇论文。'); return; }
        onChange(selectedPaperRows(chosen, value, resource.data?.items || []));
      },
      getCheckboxProps: (paper) => ({ disabled: disabled || !canSelectPaper(paper) || (value.length >= 20 && !keys.includes(paper.id)), 'aria-label': `选择论文 ${paper.title}` }),
    }} />
    {resource.data && <PaginationBar total={resource.data.total} page={page} onChange={setPage} />}
  </div>;
}
