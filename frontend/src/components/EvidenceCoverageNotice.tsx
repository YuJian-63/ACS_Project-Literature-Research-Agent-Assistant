import { Alert } from 'antd';
import type { Paper, Task } from '../api/types';
import { t, useLocale } from '../i18n';

export default function EvidenceCoverageNotice({ task, papers }: { task: Task; papers: Paper[] }) {
  useLocale();
  const retrieval = task.retrieval;
  if (!retrieval || !['partial', 'insufficient_selected_evidence', 'no_parsed_text'].includes(retrieval.status)) return null;
  const missing = retrieval.missing_aspects ?? [];
  const gaps = retrieval.papers ?? [];
  return <Alert className="inline-alert" type="warning" showIcon
    title={t(retrieval.status === 'no_parsed_text' ? '论文没有可用于分析的解析文本，请检查解析结果。' : retrieval.status === 'partial' ? '部分问题或比较维度缺少支持证据，请结合引用阅读。' : '当前检索片段不足以支持回答，不代表论文全文没有相关信息。')}
    description={(missing.length > 0 || gaps.length > 0) && <div>
      <p>{t('以下内容尚缺少充分证据，不代表论文全文没有相关信息。')}</p>
      <ul>
        {missing.map((aspect, index) => <li key={index}>{aspect}</li>)}
        {gaps.map((gap) => <li key={gap.paper_id}>
          <strong>{gap.paper_title || papers.find((paper) => paper.id === gap.paper_id)?.title || t('论文 {0}', [task.paper_ids.indexOf(gap.paper_id) + 1])}</strong>
          <span>：{gap.columns.map((column) => t(column)).join(' / ')}</span>
        </li>)}
      </ul>
    </div>} />;
}
