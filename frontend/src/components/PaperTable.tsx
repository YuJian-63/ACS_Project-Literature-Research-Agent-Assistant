import { errorText } from '../i18n/diagnostics';
import { t, useLocale } from '../i18n';
import { Empty, Table } from 'antd';
import type { TableColumnsType, TableProps } from 'antd';
import type { Key } from 'react';
import { Link } from 'react-router-dom';
import type { Page, Paper } from '../api/types';
import { dateTime, fileSize } from '../lib/format';
import { paperReaderUrl } from '../lib/paperReader';
import { StatusBadge } from './Common';

export function canSelectPaper(paper: Paper): boolean {
  return paper.status === 'uploaded' || paper.status === 'ready';
}

export function hasPendingPapers(page: Page<Paper>): boolean {
  return page.items.some((paper) => paper.status === 'uploaded' || paper.status === 'processing');
}

export function selectedPaperRows(keys: Key[], previous: Paper[], current: Paper[]): Paper[] {
  const known = new Map([...previous, ...current].map((paper) => [paper.id, paper]));
  return keys.map((key) => known.get(String(key))).filter((paper): paper is Paper => Boolean(paper));
}

const columns = (onOpenPaper?: (paper: Paper) => void, selectedKeys: Key[] = []): TableColumnsType<Paper> => [
  { title: t("论文"), dataIndex: 'title', key: 'title', render: (_value, paper) => <div className="paper-name">{onOpenPaper ? <button type="button" className="paper-title-button" data-paper-id={paper.id} onClick={() => onOpenPaper(paper)}>{paper.title}</button> : <Link to={paperReaderUrl(paper.id, { selectedIds: selectedKeys.map(String) })} title={paper.source?.title}>{paper.title}</Link>}<span>{paper.original_filename}</span>{paper.source && <a className="paper-source" href={`https://arxiv.org/abs/${paper.source.external_id.split('/').map(encodeURIComponent).join('/')}`} target="_blank" rel="noopener noreferrer">arXiv · {paper.source.external_id}</a>}</div> },
  { title: t("状态 / 解析"), key: 'status', width: 180, render: (_value, paper) => <div className="paper-parse-state"><StatusBadge status={paper.status} kind="paper" />{paper.status === 'ready' && <small>{t("{0} 页 · 已提取文本", [paper.page_count])}<abbr title={paper.parser_version || undefined}>{t("解析版本")}</abbr></small>}{paper.status === 'failed' && paper.error && <details><summary>{t("查看原因")}</summary><p>{errorText(paper.error)}</p><small>{t("{0} · 重新上传以重试", [paper.error.code])}</small></details>}</div> },
  { title: t("文件大小"), dataIndex: 'size_bytes', width: 110, render: (value: number) => fileSize(value) },
  { title: t("上传时间"), dataIndex: 'created_at', width: 144, render: (value: string) => dateTime(value) },
];

export function PaperTable({ papers, loading, selection, scrollHeight, onOpenPaper, emptyMessage = t("还没有论文") }: {
  papers: Paper[];
  loading: boolean;
  selection?: TableProps<Paper>['rowSelection'];
  scrollHeight?: number;
  onOpenPaper?: (paper: Paper) => void;
  emptyMessage?: string;
}) {
  useLocale();
  return <Table<Paper> rowKey="id" columns={columns(onOpenPaper, selection?.selectedRowKeys)} dataSource={papers} loading={loading} rowSelection={selection}
    pagination={false} scroll={{ x: 680, y: scrollHeight }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyMessage} /> }} />;
}
