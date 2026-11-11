import { Empty, Table } from 'antd';
import type { TableColumnsType, TableProps } from 'antd';
import type { Key } from 'react';
import type { Paper } from '../api/types';
import { paperFileUrl } from '../api/client';
import { dateTime, fileSize } from '../lib/format';
import { StatusBadge } from './Common';

export function canSelectPaper(paper: Paper): boolean {
  return paper.status === 'uploaded' || paper.status === 'ready';
}

export function selectedPaperRows(keys: Key[], previous: Paper[], current: Paper[]): Paper[] {
  const known = new Map([...previous, ...current].map((paper) => [paper.id, paper]));
  return keys.map((key) => known.get(String(key))).filter((paper): paper is Paper => Boolean(paper));
}

const columns: TableColumnsType<Paper> = [
  { title: '论文', dataIndex: 'title', key: 'title', render: (_value, paper) => <div className="paper-name"><a href={paperFileUrl(paper.id)} target="_blank" rel="noopener noreferrer">{paper.title}</a><span>{paper.original_filename}</span></div> },
  { title: '状态', dataIndex: 'status', width: 116, render: (status: Paper['status']) => <StatusBadge status={status} kind="paper" /> },
  { title: '文件大小', dataIndex: 'size_bytes', width: 110, render: (value: number) => fileSize(value) },
  { title: '上传时间', dataIndex: 'created_at', width: 144, render: (value: string) => dateTime(value) },
];

export function PaperTable({ papers, loading, selection, scrollHeight, emptyMessage = '还没有论文' }: {
  papers: Paper[];
  loading: boolean;
  selection?: TableProps<Paper>['rowSelection'];
  scrollHeight?: number;
  emptyMessage?: string;
}) {
  return <Table<Paper> rowKey="id" columns={columns} dataSource={papers} loading={loading} rowSelection={selection}
    pagination={false} scroll={{ x: 680, y: scrollHeight }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyMessage} /> }} />;
}
