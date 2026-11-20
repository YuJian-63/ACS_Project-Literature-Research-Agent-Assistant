import { Button, Popconfirm } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import type { Paper } from '../../../api/types';
import { t } from '../../../i18n';

export default function PaperDeleteButton({ paper, deletingId, onDelete }: { paper: Paper; deletingId?: string | null; onDelete: (paper: Paper) => Promise<void> }) {
  return <span className="paper-delete-action"><Popconfirm title={t('删除论文？')} description={t('删除后将移除 PDF 和解析内容；已被研究任务引用的论文无法删除。')} okText={t('删除')} cancelText={t('取消')} okButtonProps={{ danger: true }} onConfirm={() => onDelete(paper)}>
    <Button danger type="text" icon={<DeleteOutlined />} disabled={Boolean(deletingId) || paper.status === 'processing'} loading={deletingId === paper.id} aria-label={t('删除论文 {0}', [paper.title])}>{t('删除')}</Button>
  </Popconfirm></span>;
}
