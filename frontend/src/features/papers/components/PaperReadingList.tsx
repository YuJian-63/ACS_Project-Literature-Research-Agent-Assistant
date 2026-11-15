import { Checkbox, Empty } from 'antd';
import { FilePdfOutlined } from '@ant-design/icons';
import type { Paper } from '../../../api/types';
import { t } from '../../../i18n';
import { canSelectPaper } from '../lib/selection';
import { StatusBadge } from '../../../shared/components/StatusBadge';

export default function PaperReadingList({ papers, activeId, selectedIds, loading, emptyMessage, onRead, onSelect }: {
  papers: Paper[];
  activeId: string;
  selectedIds: string[];
  loading: boolean;
  emptyMessage: string;
  onRead: (paper: Paper) => void;
  onSelect: (paper: Paper, checked: boolean) => void;
}) {
  return <div className="paper-reading-list" aria-label={t('论文列表')} aria-busy={loading}>
    {!papers.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyMessage} />}
    {papers.map((paper) => {
      const checked = selectedIds.includes(paper.id);
      return <div key={paper.id} className={'paper-reading-item' + (paper.id === activeId ? ' is-active' : '')}>
        <Checkbox aria-label={t('选择论文 {0}', [paper.title])} checked={checked}
          disabled={!canSelectPaper(paper) || (!checked && selectedIds.length >= 20)} onChange={(event) => onSelect(paper, event.target.checked)} />
        <button type="button" aria-current={paper.id === activeId ? 'true' : undefined} aria-label={t('阅读论文 {0}', [paper.title])} onClick={() => onRead(paper)}>
          <span className="reading-item-title">{paper.title}</span>
          <span className="reading-item-file"><FilePdfOutlined aria-hidden="true" />{paper.original_filename}</span>
          <span className="reading-item-meta"><StatusBadge status={paper.status} kind="paper" />{paper.page_count !== null && <span>{t('{0} 页', [paper.page_count])}</span>}</span>
        </button>
      </div>;
    })}
  </div>;
}
