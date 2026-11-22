import { useEffect, useId, useRef, useState } from 'react';
import { DownOutlined, UpOutlined } from '@ant-design/icons';
import { t, useLocale } from '../../../i18n';
import MathText from '../../../shared/components/MathText';

export default function PaperAbstract({ text }: { text: string }) {
  useLocale();
  const [expanded, setExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);
  const paragraph = useRef<HTMLDivElement>(null);
  const identity = useId();

  useEffect(() => {
    const element = paragraph.current;
    if (!element) return;
    const measure = () => setOverflowing(element.scrollHeight > Number.parseFloat(getComputedStyle(element).lineHeight) * 3 + 1);
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    measure();
    return () => observer.disconnect();
  }, [text]);

  return <div className="paper-abstract-block">
    <div id={identity} ref={paragraph} className={'paper-abstract' + (expanded ? ' is-expanded' : '')}><MathText inline>{text}</MathText></div>
    {overflowing && <button type="button" className="abstract-toggle" aria-expanded={expanded} aria-controls={identity} onClick={() => setExpanded((value) => !value)}>
      {t(expanded ? '收起摘要' : '展开摘要')}{expanded ? <UpOutlined aria-hidden="true" /> : <DownOutlined aria-hidden="true" />}
    </button>}
  </div>;
}
