import { t, useLocale } from '../../i18n';
import { useEffect, useRef, useState } from 'react';
import { App, Button, Checkbox, Form, Input, Radio, Select, Space, Spin } from 'antd';
import { BookOutlined } from '@ant-design/icons';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, asApiError, isCanceled } from '../../api/client';
import type { Paper } from '../../api/types';
import { agentResearch, defaultResearch, type ResearchOptions, type AgentResearchRequest } from '../../api/agentResearch';
import { PaperPicker } from '../papers/components/PaperPicker';
import { canSelectPaper } from '../papers/lib/selection';
import { errorText } from '../../i18n/diagnostics';
import { ErrorNotice } from '../../shared/components/ErrorNotice';
import { useAuth } from '../auth/AuthProvider';
import { clearResearchDraft, readResearchDraft, researchSubmission, saveResearchDraft, type ResearchSubmission } from '../../shared/lib/researchDraft';
import './research.css';

import { changeService, courseAvailable, loadModels, pollModels } from '../../api/models';
import { useResource } from '../../shared/hooks/useResource';
import MathText from '../../shared/components/MathText';

export default function NewResearchPage() {
  useLocale();
  const models = useResource(loadModels, 10000, pollModels);
  const { user } = useAuth();
  const userId = user!.id;
  const [params] = useSearchParams();
  const key = params.toString();
  const [question, setQuestion] = useState('');
  const [research, setResearch] = useState<ResearchOptions>(defaultResearch);
  const [startingModel, setStartingModel] = useState(false);
  const extensionFlags = useRef({ planner: true, reflection: true });
  const [allowSearch, setAllowSearch] = useState(true);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ReturnType<typeof asApiError>>();
  const [revision, setRevision] = useState(0);
  const { notification } = App.useApp();
  const [submitting, setSubmitting] = useState(false);
  const submission = useRef<AbortController | null>(null);
  const attempt = useRef<ResearchSubmission | undefined>(undefined);
  const restoredKey = useRef<string | undefined>(undefined);
  useEffect(() => () => submission.current?.abort(), []);
  const navigate = useNavigate();
  useEffect(() => {
    const pending = new AbortController();
    const draft = readResearchDraft(userId);
    restoredKey.current = undefined;
    attempt.current = draft?.submission;
    // Pre-options drafts with a pending submission must retry the original full-context request.
    const restored = draft?.research ?? (draft?.submission ? { ...defaultResearch, context_policy: 'full' as const } : defaultResearch);
    setResearch(restored);
    extensionFlags.current = restored.workflow === 'extension'
      ? { planner: restored.planner, reflection: restored.reflection }
      : { planner: true, reflection: true };
    setAllowSearch(draft?.allowSearch ?? true);
    setLoading(true); setError(undefined); setPapers([]); setQuestion(draft?.question ?? '');
    void (async () => {
      try {
        const query = new URLSearchParams(key);
        const restoring = !query.has('paper_id') || draft?.sourceKey === key;
        const ids = [...new Set(restoring ? draft?.paperIds ?? [] : query.getAll('paper_id'))];
        if (ids.length > 20) throw new Error(t("最多可选择 20 篇论文。"));
        const selected = await Promise.all(ids.map(async id => {
          try { return await api.paper(id, pending.signal); }
          catch (failure) { if (restoring && asApiError(failure).status === 404) return null; throw failure; }
        }));
        if (!pending.signal.aborted) {
          const available = selected.filter((paper): paper is Paper => paper !== null && (!restoring || canSelectPaper(paper)));
          restoredKey.current = key;
          setPapers(available);
          if (available.length < ids.length) notification.info({ title: t('研究草稿已恢复'), description: t('部分参考论文已不可用，已从草稿中移除。'), duration: 5 });
        }
      } catch (failure) { if (!pending.signal.aborted && !isCanceled(failure)) setError(asApiError(failure)); }
      finally { if (!pending.signal.aborted) setLoading(false); }
    })();
    return () => pending.abort();
  }, [key, revision, userId, notification]);
  useEffect(() => {
    if (restoredKey.current === key && !loading && !error) saveResearchDraft(userId, { question, research, allowSearch, paperIds: papers.map(paper => paper.id), sourceKey: key, submission: attempt.current });
  }, [question, papers, research, allowSearch, loading, error, userId, key]);
  async function submit() {
    if (submission.current) return;
    const reason = !question.trim() ? t("请先写下你的研究问题。") : papers.length > 20 ? t("最多可选择 20 篇论文。") : papers.some(paper => !canSelectPaper(paper)) ? t("请选择可用于研究的论文。") : '';
    if (!allowSearch && !papers.length) {
      notification.warning({ title: t('请选择参考论文或开启搜索') }); return;
    }
    if (reason) { notification.warning({ title: t('研究未能开始'), description: reason, duration: 3 }); return; }
    const customUrl = research.endpoint_url ?? models.data?.shared_url ?? '';
    if (research.model_provider === 'custom' && !/^http:\/\/10\.0\.\d{1,3}\.\d{1,3}:8000\/v1\/?$/.test(customUrl.trim())) {
      notification.warning({title: t('请输入有效的 TACC 地址，例如 http://10.0.3.10:8000/v1')}); return;
    }
    const input: AgentResearchRequest = { question: question.trim(), paper_ids: papers.map(paper => paper.id), allow_search: allowSearch, research: research.model_provider === 'custom' ? {...research, endpoint_url: customUrl.trim()} : research };
    attempt.current = researchSubmission(input, attempt.current);
    saveResearchDraft(userId, { question, research, allowSearch, paperIds: input.paper_ids!, sourceKey: key, submission: attempt.current });
    const pending = new AbortController();
    submission.current = pending; setSubmitting(true);
    try {
      const accepted = await agentResearch.create(input, attempt.current.key, pending.signal);
      if (!pending.signal.aborted) {
        clearResearchDraft(userId);
        attempt.current = undefined;
        navigate('/tasks/' + encodeURIComponent(accepted.task_id));
      }
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
  <section className="content-panel research-question-panel"><h2>{t("你想了解什么？")}</h2><p>{t("直接描述你想解决的问题，或希望从论文中了解的内容。")}</p><Form.Item required label={t("研究问题")}><Input.TextArea value={question} onChange={event => setQuestion(event.target.value)} rows={5} maxLength={8000} showCount disabled={loading || submitting || Boolean(error)} placeholder={t("例如：这些论文的方法有什么不同？它们在什么条件下适用？")} /></Form.Item></section>
  <section className="content-panel research-paper-panel"><h2>{t('研究设置')}</h2>
    <Form.Item label={t('模型来源')} extra={<Link to="/models">{t('模型管理')}</Link>}>
      <Select aria-label={t('模型来源')} value={research.model_provider ?? 'bailian'} disabled={loading || submitting}
        options={[{value: 'bailian', label: t('百炼 API')}, {value: 'tacc', label: t('课程模型服务')}, {value: 'custom', label: t('指定服务地址')}]}
        onChange={model_provider => setResearch({...research, model_provider, endpoint_url: undefined})} /></Form.Item>
    {research.model_provider === 'custom' && <Form.Item label={t('服务地址')} required>
      <Input aria-label={t('服务地址')} placeholder="http://10.0.3.10:8000/v1" disabled={submitting}
        value={research.endpoint_url ?? models.data?.shared_url ?? ''} onChange={event => setResearch({...research, endpoint_url: event.target.value})} /></Form.Item>}
    {research.model_provider === 'tacc' && !courseAvailable(models.data) && <Space wrap>
      <span>{t('课程服务就绪后即可提交研究。')}</span>
      {models.data?.enabled && ['stopped', 'failed'].includes(models.data.state) && <Button loading={startingModel} onClick={async () => {
        setStartingModel(true);
        try { await changeService('start'); models.reload(); }
        catch (failure) { notification.error({title: asApiError(failure).message}); }
        finally { setStartingModel(false); }
      }}>{t('启动 TACC 服务')}</Button>}
    </Space>}
    <Form.Item label={t('研究模式')}><Radio.Group aria-label={t('研究模式')} optionType="button" buttonStyle="solid" disabled={loading || submitting}
      value={research.workflow} options={[{ value: 'baseline', label: 'Baseline' }, { value: 'extension', label: 'Extension' }]}
      onChange={e => {
        if (e.target.value === 'extension') {
          setResearch({ ...research, workflow: 'extension', ...extensionFlags.current });
        } else {
          extensionFlags.current = { planner: research.planner, reflection: research.reflection };
          setResearch({ ...research, workflow: 'baseline', planner: false, reflection: false });
        }
      }} /></Form.Item>
    <Form.Item label={t('上下文策略')}><Select aria-label={t('上下文策略')} disabled={loading || submitting} value={research.context_policy}
      options={[{ value: 'full', label: t('完整历史') }, { value: 'compact', label: t('压缩历史') }]}
      onChange={context_policy => setResearch({ ...research, context_policy })} /></Form.Item>
    <Space wrap><Checkbox disabled={loading || submitting} checked={allowSearch} onChange={e => setAllowSearch(e.target.checked)}>{t('允许搜索论文库和 arXiv')}</Checkbox>
    {research.workflow === 'extension' && <><Checkbox disabled={loading || submitting} checked={research.planner} onChange={e => setResearch({ ...research, planner: e.target.checked })}>Planner</Checkbox>
    <Checkbox disabled={loading || submitting} checked={research.reflection} onChange={e => setResearch({ ...research, reflection: e.target.checked })}>Reflection</Checkbox></>}</Space>
  </section>
  <section className="content-panel research-paper-panel"><div className="panel-heading"><div><h2>{t('参考论文（可选）')}</h2><p>{t('可以不选，也可以指定最多 20 篇参考论文。研究将先检索已有资料，信息不足时再搜索补充论文。')}</p></div><Link to="/papers">{t("前往论文库")}</Link></div><PaperPicker value={papers} onChange={setPapers} disabled={loading || submitting || Boolean(error)} /></section>
  </div><aside className="research-submit-panel"><span className="research-section-label">{t("本次研究")}</span><h2>{t("从问题到理解")}</h2><p><MathText inline>{question.trim() || t("你的研究问题会显示在这里。")}</MathText></p>{papers.length > 0 ? <div className="research-submit-count"><BookOutlined /><strong>{papers.length}</strong><span>{t('篇参考论文')}</span></div> : <p className="research-auto-sources">{t('未指定参考论文，将根据研究问题查找相关资料。')}</p>}{papers.length > 0 && <ul>{papers.map(paper => <li key={paper.id}><MathText inline>{paper.title}</MathText></li>)}</ul>}<Button type="primary" htmlType="submit" size="large" block loading={submitting} disabled={(research.model_provider === 'tacc' && !courseAvailable(models.data)) || loading || submitting || Boolean(error)}>{t('开始研究')}</Button><small>{t('研究开始后，可在研究记录中查看进展与结果。')}</small></aside>
  </div></Form></Spin></>;
}
