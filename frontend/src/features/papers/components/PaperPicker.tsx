import { t, useLocale } from '../../../i18n';
import { useCallback, useState } from 'react';
import { App, Input, Tag } from 'antd';
import { api } from '../../../api/client';
import type { Paper } from '../../../api/types';
import { useResource } from '../../../shared/hooks/useResource';
import { ErrorNotice } from '../../../shared/components/ErrorNotice';
import { PaginationBar } from '../../../shared/components/PaginationBar';
import { PaperTable } from './PaperTable';
import { canSelectPaper, hasPendingPapers, selectedPaperRows } from '../lib/selection';

export function PaperPicker({ value, onChange, disabled }: { value: Paper[]; onChange: (papers: Paper[]) => void; disabled: boolean }) {
  useLocale();
  const { message } = App.useApp();
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const load = useCallback((signal: AbortSignal) => api.papers({ limit: 20, offset: (page - 1) * 20, q: query || undefined }, signal), [page, query]);
  const resource = useResource(load, 2000, hasPendingPapers);
  const keys = value.map((paper) => paper.id);
  return <div className="paper-picker">
    <div className="picker-toolbar"><Input.Search placeholder={t("搜索已上传论文")} aria-label={t("搜索待选论文")} maxLength={200} allowClear disabled={disabled} onSearch={(text) => { setQuery(text); setPage(1); }} /><span>{t("已选 {0} / 20 篇", [value.length])}</span></div>
    {value.length > 0 && <div className="selected-papers" aria-label={t("已选论文")}>{value.map((paper) => <Tag key={paper.id} closable={!disabled} onClose={() => onChange(value.filter((item) => item.id !== paper.id))}>{paper.title}</Tag>)}</div>}
    {resource.error && <ErrorNotice error={resource.error} retry={resource.reload} />}
    <PaperTable papers={resource.data?.items || []} loading={resource.loading} scrollHeight={400} emptyMessage={query ? t("没有匹配的论文") : t("请先在论文库上传 PDF")} selection={{
      selectedRowKeys: keys,
      preserveSelectedRowKeys: true,
      onChange: (chosen) => {
        if (chosen.length > 20) { void message.warning(t("最多可选择 20 篇论文。")); return; }
        onChange(selectedPaperRows(chosen, value, resource.data?.items || []));
      },
      getCheckboxProps: (paper) => ({ disabled: disabled || !canSelectPaper(paper) || (value.length >= 20 && !keys.includes(paper.id)), 'aria-label': t("选择论文 {0}", [paper.title]) }),
    }} />
    {resource.data && <PaginationBar total={resource.data.total} page={page} onChange={setPage} />}
  </div>;
}
