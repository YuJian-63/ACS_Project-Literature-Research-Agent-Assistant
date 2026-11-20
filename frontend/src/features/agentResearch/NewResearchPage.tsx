import { t, useLocale } from '../../i18n';
import { useEffect, useRef, useState } from 'react';
import { App, Button, Form, Input, Spin } from 'antd';
import { BookOutlined } from '@ant-design/icons';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, asApiError, isCanceled } from '../../api/client';
import type { Paper } from '../../api/types';
import { agentResearch, type AgentResearchRequest } from '../../api/agentResearch';
import { PaperPicker } from '../papers/components/PaperPicker';
import { canSelectPaper } from '../papers/lib/selection';
import { errorText } from '../../i18n/diagnostics';
import { ErrorNotice } from '../../shared/components/ErrorNotice';
import './research.css';

export default function NewResearchPage() {
  useLocale();
  const [params] = useSearchParams();
  const key = params.toString();
  const [question, setQuestion] = useState('');
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ReturnType<typeof asApiError>>();
  const [revision, setRevision] = useState(0);
  const { notification } = App.useApp();
  const [submitting, setSubmitting] = useState(false);
  const submission = useRef<AbortController | null>(null);
  useEffect(() => () => submission.current?.abort(), []);
  const navigate = useNavigate();
  useEffect(() => {
    const pending = new AbortController();
    setLoading(true); setError(undefined); setPapers([]); setQuestion('');
    void (async () => {
      try {
        const query = new URLSearchParams(key);
        const ids = [...new Set(query.getAll('paper_id'))];
        if (ids.length > 20) throw new Error(t("最多可选择 20 篇论文。"));
        const selected = await Promise.all(ids.map(id => api.paper(id, pending.signal)));
        if (!pending.signal.aborted) { setPapers(selected); setQuestion(''); }
      } catch (failure) { if (!pending.signal.aborted && !isCanceled(failure)) setError(asApiError(failure)); }
      finally { if (!pending.signal.aborted) setLoading(false); }
    })();
    return () => pending.abort();
  }, [key, revision]);
  async function submit() {
    if (submission.current) return;
    const reason = !question.trim() ? t("请先写下你的研究问题。") : papers.length > 20 ? t("最多可选择 20 篇论文。") : papers.some(paper => !canSelectPaper(paper)) ? t("请选择可用于研究的论文。") : '';
    if (reason) { notification.warning({ title: t('研究未能开始'), description: reason, duration: 3 }); return; }
    const input: AgentResearchRequest = { question: question.trim(), paper_ids: papers.map(paper => paper.id), allow_search: true };
    const pending = new AbortController();
    submission.current = pending; setSubmitting(true);
    try {
      const accepted = await agentResearch.create(input, pending.signal);
      if (!pending.signal.aborted) navigate('/tasks/' + encodeURIComponent(accepted.task_id));
    } catch (failure) {
      if (!pending.signal.aborted && !isCanceled(failure)) {
        const issue = asApiError(failure);
        notification.error({ title: t('研究未能开始'), description: issue.code === 'AGENT_NOT_CONNECTED' ? t('研究服务暂未连接，请稍后再试。') : errorText(issue), duration: 3 });
      }
    } finally { if (submission.current === pending) submission.current = null; if (!pending.signal.aborted) setSubmitting(false); }
  }

  return <><div className="page-heading"><div><h1>{t("新建研究")}</h1><p>{t('写下研究问题，也可以指定希望参考的论文。')}</p></div></div>
  {error && <ErrorNotice error={error} retry={() => setRevision(value => value + 1)} />}
  <Spin spinning={loading}><Form layout="vertical" onFinish={submit}><div className="research-creation-layout"><div>
  <section className="content-panel research-question-panel"><h2>{t("你想了解什么？")}</h2><p>{t("直接描述你想解决的问题，或希望从论文中了解的内容。")}</p><Form.Item required label={t("研究问题")}><Input.TextArea value={question} onChange={event => setQuestion(event.target.value)} rows={5} maxLength={8000} showCount disabled={submitting} placeholder={t("例如：这些论文的方法有什么不同？它们在什么条件下适用？")} /></Form.Item></section>
  <section className="content-panel research-paper-panel"><div className="panel-heading"><div><h2>{t('参考论文（可选）')}</h2><p>{t('可以不选，也可以指定最多 20 篇参考论文。研究将先检索已有资料，信息不足时再搜索补充论文。')}</p></div><Link to="/papers">{t("前往论文库")}</Link></div><PaperPicker value={papers} onChange={setPapers} disabled={loading || submitting || Boolean(error)} /></section>
  </div><aside className="research-submit-panel"><span className="research-section-label">{t("本次研究")}</span><h2>{t("从问题到理解")}</h2><p>{question.trim() || t("你的研究问题会显示在这里。")}</p>{papers.length > 0 ? <div className="research-submit-count"><BookOutlined /><strong>{papers.length}</strong><span>{t('篇参考论文')}</span></div> : <p className="research-auto-sources">{t('未指定参考论文，将根据研究问题查找相关资料。')}</p>}{papers.length > 0 && <ul>{papers.map(paper => <li key={paper.id}>{paper.title}</li>)}</ul>}<Button type="primary" htmlType="submit" size="large" block loading={submitting} disabled={loading || submitting || Boolean(error)}>{t('开始研究')}</Button><small>{t('研究开始后，可在研究记录中查看进展与结果。')}</small></aside>
  </div></Form></Spin></>;
}
