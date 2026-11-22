import { errorText } from '../../../i18n/diagnostics';
import { t, useLocale } from '../../../i18n';
import { Empty, Table } from 'antd';
import type { TableColumnsType, TableProps } from 'antd';
import type { Key } from 'react';
import { Link } from 'react-router-dom';
import type { Paper } from '../../../api/types';
import { dateTime, fileSize } from '../../../shared/lib/format';
import { paperReaderUrl } from '../../../shared/lib/paperReader';
import PaperDeleteButton from './PaperDeleteButton';
import MathText from '../../../shared/components/MathText';
import { StatusBadge } from '../../../shared/components/StatusBadge';

const columns = (onOpenPaper?: (paper: Paper) => void, selectedKeys: Key[] = [], onDelete?: (paper: Paper) => Promise<void>, deletingId?: string | null): TableColumnsType<Paper> => [
  { title: t("论文"), dataIndex: 'title', key: 'title', render: (_value, paper) => <div className="paper-name">{onOpenPaper ? <button type="button" className="paper-title-button" data-paper-id={paper.id} onClick={() => onOpenPaper(paper)}><MathText inline>{paper.title}</MathText></button> : <Link to={paperReaderUrl(paper.id, { selectedIds: selectedKeys.map(String) })} title={paper.source?.title}><MathText inline>{paper.title}</MathText></Link>}{paper.source && <a className="paper-source" href={`https://arxiv.org/abs/${paper.source.external_id.split('/').map(encodeURIComponent).join('/')}`} target="_blank" rel="noopener noreferrer">arXiv · {paper.source.external_id}</a>}</div> },
  { title: t("状态 / 解析"), key: 'status', width: 180, render: (_value, paper) => <div className="paper-parse-state"><StatusBadge status={paper.status} kind="paper" />{paper.status === 'ready' && <small>{t("{0} 页 · 已提取文本", [paper.page_count])}</small>}{paper.status === 'failed' && paper.error && <details><summary>{t("查看原因")}</summary><p>{errorText(paper.error)}</p><small>{t("{0} · 重新上传以重试", [paper.error.code])}</small></details>}</div> },
  { title: t("文件大小"), dataIndex: 'size_bytes', width: 110, render: (value: number) => fileSize(value) },
  { title: t("上传时间"), dataIndex: 'created_at', width: 144, render: (value: string) => dateTime(value) },
  ...(onDelete ? [{ title: t('操作'), key: 'actions', width: 100, render: (_value: unknown, paper: Paper) => <PaperDeleteButton paper={paper} deletingId={deletingId} onDelete={onDelete} /> }] : []),
];

export function PaperTable({ papers, loading, selection, scrollHeight, onOpenPaper, onDelete, deletingId, emptyMessage = t("还没有论文") }: {
  papers: Paper[];
  loading: boolean;
  selection?: TableProps<Paper>['rowSelection'];
  scrollHeight?: number;
  onOpenPaper?: (paper: Paper) => void;
  onDelete?: (paper: Paper) => Promise<void>;
  deletingId?: string | null;
  emptyMessage?: string;
}) {
  useLocale();
  return <Table<Paper> rowKey="id" columns={columns(onOpenPaper, selection?.selectedRowKeys, onDelete, deletingId)} dataSource={papers} loading={loading} rowSelection={selection}
    pagination={false} scroll={{ x: 680, y: scrollHeight }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyMessage} /> }} />;
}
