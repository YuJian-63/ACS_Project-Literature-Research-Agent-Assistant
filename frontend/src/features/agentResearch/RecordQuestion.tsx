import { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { t, useLocale } from '../../i18n';
import MathText from '../../shared/components/MathText';
import RecordWorkflow from './RecordWorkflow';

export default function RecordQuestion({ taskId, question }: { taskId: string; question: string }) {
  const locale = useLocale();
  const textId = useId();
  const text = useRef<HTMLAnchorElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);
  useEffect(() => {
    setExpanded(false);
    const element = text.current;
    if (!element) return;
    const measure = () => {
      const lineHeight = parseFloat(getComputedStyle(element).lineHeight);
      setOverflowing(element.scrollHeight > lineHeight * 3 + 1);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [question, locale]);
  return <div className="task-name record-question">
    <Link ref={text} id={textId} className={`record-question-text${expanded ? ' is-expanded' : ''}`} to={`/tasks/${taskId}`}>
      <MathText inline>{question || t('研究任务')}</MathText>
    </Link>
    {overflowing && <button className="record-question-toggle" type="button" aria-expanded={expanded} aria-controls={textId} onClick={() => setExpanded(value => !value)}>
      {locale === 'en-US' ? expanded ? 'Collapse' : 'Show full text' : expanded ? '收起' : '显示完整文本'}
    </button>}
    <div className="record-question-meta"><RecordWorkflow taskId={taskId} /><span className="task-identifier">{taskId.slice(0, 8)}</span></div>
  </div>;
}
