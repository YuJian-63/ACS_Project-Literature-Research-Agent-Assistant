import { t, useLocale } from '../i18n';
import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Collapse, Form, Input, InputNumber, Radio, Spin } from 'antd';
import { ArrowLeftOutlined, ArrowRightOutlined } from '@ant-design/icons';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, asApiError, isCanceled, type ApiError } from '../api/client';
import type { Budget, Paper, TaskType } from '../api/types';
import { ErrorNotice, PageHeader } from '../components/Common';
import { canSelectPaper } from '../components/PaperTable';
import { PaperPicker } from '../components/PaperPicker';
import { defaultBudget, normalizeSubmission, selectionError, submissionSignature } from '../lib/submission';

interface TaskForm {
  task_type: TaskType;
  question?: string;
  budget: Budget;
}

export default function NewTaskPage() {
  const locale = useLocale();
  const [parameters] = useSearchParams();
  const queryString = parameters.toString();
  const navigate = useNavigate();
  const [form] = Form.useForm<TaskForm>();
  const taskType = Form.useWatch('task_type', form) || 'summary';
  const [papers, setPapers] = useState<Paper[]>([]);
  const [initialLoading, setInitialLoading] = useState(true);
  const [initialError, setInitialError] = useState<ApiError>();
  const [initialRevision, setInitialRevision] = useState(0);
  const [submitError, setSubmitError] = useState<ApiError>();
  const [submitting, setSubmitting] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [paperQueryError, setPaperQueryError] = useState<ApiError>();
  const [paperRevision, setPaperRevision] = useState(0);
  const lastAttempt = useRef<{ signature: string; key: string } | null>(null);
  const controller = useRef<AbortController | null>(null);
  const inFlight = useRef(false);

  useEffect(() => {
    const invalidFields = form.getFieldsError().filter((field) => field.errors.length).map((field) => field.name);
    if (invalidFields.length) void form.validateFields(invalidFields).catch(() => undefined);
  }, [form, locale]);

  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    const pending = new AbortController();
    controller.current?.abort();
    controller.current = null;
    inFlight.current = false;
    lastAttempt.current = null;
    setInitialLoading(true);
    setInitialError(undefined);
    setSubmitError(undefined);
    setSubmitting(false);
    setAttempted(false);
    setPapers([]);
    form.resetFields();
    const query = new URLSearchParams(queryString);
    void (async () => {
      try {
        const sourceId = query.get('from_task');
        const source = sourceId ? await api.task(sourceId, pending.signal) : null;
        const ids = [...new Set(source ? source.paper_ids : query.getAll('paper_id'))];
        if (ids.length > 20) throw new Error(t("最多选择 20 篇论文，请返回论文库重新选择。"));
        const selected = await Promise.all(ids.map((id) => api.paper(id, pending.signal)));
        if (pending.signal.aborted) return;
        setPapers(selected);
        form.setFieldsValue({
          task_type: source?.task_type || (selected.length > 1 ? 'review' : 'summary'),
          question: source?.question || '',
          budget: source?.budget || { ...defaultBudget },
        });
      } catch (error) {
        if (!pending.signal.aborted && !isCanceled(error)) setInitialError(asApiError(error));
      } finally {
        if (!pending.signal.aborted) setInitialLoading(false);
      }
    })();
    return () => pending.abort();
  }, [form, queryString, initialRevision]);

  const selectedIds = papers.map((paper) => paper.id).join(',');
  useEffect(() => {
    if (initialLoading || !selectedIds || papers.every((paper) => paper.status === 'ready' || paper.status === 'failed')) return;
    const pending = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let keepPolling = true;
    setPaperQueryError(undefined);
    async function updateSelected() {
      try {
        const updated = await Promise.all(selectedIds.split(',').map((id) => api.paper(id, pending.signal)));
        if (pending.signal.aborted) return;
        setPapers(updated);
        setPaperQueryError(undefined);
        keepPolling = updated.some((paper) => paper.status === 'uploaded' || paper.status === 'processing');
      } catch (error) {
        if (!pending.signal.aborted && !isCanceled(error)) setPaperQueryError(asApiError(error));
      } finally {
        if (!pending.signal.aborted && keepPolling) timer = setTimeout(() => { void updateSelected(); }, 2000);
      }
    }
    void updateSelected();
    return () => { pending.abort(); if (timer) clearTimeout(timer); };
  }, [selectedIds, initialLoading, paperRevision]);

  const countError = selectionError(taskType, papers.length);
  const unavailable = papers.some((paper) => !canSelectPaper(paper));

  async function submit(values: TaskForm) {
    if (inFlight.current) return;
    setAttempted(true);
    if (countError || unavailable) return;
    const body = normalizeSubmission(values.task_type, values.question, papers.map((paper) => paper.id), values.budget);
    const signature = submissionSignature(body);
    if (lastAttempt.current?.signature !== signature) lastAttempt.current = { signature, key: crypto.randomUUID() };
    const pending = new AbortController();
    controller.current = pending;
    inFlight.current = true;
    setSubmitting(true);
    setSubmitError(undefined);
    try {
      const task = await api.createTask(body, lastAttempt.current.key, pending.signal);
      if (!pending.signal.aborted) navigate(`/tasks/${task.id}`);
    } catch (error) {
      if (!pending.signal.aborted && !isCanceled(error)) setSubmitError(asApiError(error));
    } finally {
      if (controller.current === pending) {
        inFlight.current = false;
        if (!pending.signal.aborted) setSubmitting(false);
      }
    }
  }

  return <>
    <Link to="/papers" className="back-link"><ArrowLeftOutlined />{t("返回论文库")}</Link>
    <PageHeader title={parameters.has('from_task') ? t("重新创建任务") : t("新建研究任务")} description={t("选择资料，明确问题，把执行过程与结果留在同一处。")} />
    {initialError ? <><ErrorNotice error={initialError} title={t("无法加载任务输入")} retry={() => setInitialRevision((value) => value + 1)} /><Link to="/tasks/new">{t("清空来源，创建新任务")}</Link></> : <Spin spinning={initialLoading} description={t("加载论文与任务输入")}><Form<TaskForm> form={form} layout="vertical" onFinish={(values) => { void submit(values); }} onFinishFailed={() => setAttempted(true)} disabled={submitting || initialLoading} initialValues={{ task_type: 'summary', question: '', budget: defaultBudget }}>
      <div className="creation-layout"><div className="creation-main">
        <section className="content-panel form-section"><h2>{t("你想研究什么？")}</h2>
          <Form.Item name="task_type" label={t("任务类型")} rules={[{ required: true }]}><Radio.Group className="task-type-options" optionType="button" buttonStyle="solid" options={[{ value: 'summary', label: t("论文摘要") }, { value: 'qa', label: t("论文问答") }, { value: 'review', label: t("跨论文综述") }]} /></Form.Item>
          <Form.Item name="question" label={taskType === 'summary' ? t("关注方向（可选）") : t("研究问题")} dependencies={['task_type']} rules={[{ validator: async (_rule, value: string | undefined) => {
            if (form.getFieldValue('task_type') !== 'summary' && !value?.trim()) throw new Error(t("请输入研究问题，不能仅包含空白。"));
            if ((value?.trim().length || 0) > 8000 || value?.includes('\u0000')) throw new Error(t("问题最多 8000 字符，且不能含空字节。"));
          } }]}><Input.TextArea rows={4} maxLength={8000} showCount placeholder={taskType === 'summary' ? t("例如：重点关注方法设计和研究局限") : t("例如：这些论文采用的方法有哪些差异，实验结论是否可比较？")} /></Form.Item>
        </section>
        <section className="content-panel form-section"><div className="panel-heading"><div><h2>{t("选择研究资料")}</h2><p>{t("{0}仅支持已上传或已就绪的论文。", [taskType === 'review' ? t("综述需选择 2—20 篇论文。") : t("摘要和问答需选择 1 篇论文。")])}</p></div><Link to="/papers">{t("上传论文")}</Link></div>
          {attempted && countError && <Alert title={countError} type="error" showIcon className="inline-alert" />}
          {unavailable && <Alert title={t("部分论文正在解析或已解析失败，请移除后重新选择。")} type="warning" showIcon className="inline-alert" />}
          {paperQueryError && <ErrorNotice error={paperQueryError} title={t("选定论文状态查询失败")} retry={() => setPaperRevision((value) => value + 1)} />}
          <PaperPicker value={papers} onChange={setPapers} disabled={submitting || initialLoading} />
        </section>
      </div><aside className="creation-aside">
        <section className="content-panel execution-card"><h2>{t("执行方式")}</h2><span className="workflow-name">Baseline <span>{t("基础工作流")}</span></span><p>{t("由服务器配置选择模拟或真实研究执行。真实任务要求论文解析就绪；综述将生成带来源引用的跨论文比较表。")}</p><div className="execution-note">{t("扩展工作流尚未开放；任务详情标明是否为模拟运行")}</div></section>
        {taskType === 'review' ? <section className="content-panel"><h2>{t("自动安排执行")}</h2><p>{t("系统会根据论文数量和证据规模分阶段分析，并自动分配执行资源。无需设置预算。")}</p></section> : <Collapse className="budget-panel" items={[{ key: 'budget', label: t("执行预算"), forceRender: true, children: <><Form.Item name={['budget', 'max_steps']} label={t("最大步骤数")} rules={[{ required: true, type: 'integer', min: 1, max: 100 }]}><InputNumber min={1} max={100} precision={0} /></Form.Item><Form.Item name={['budget', 'max_tokens']} label={t("累计 Token 上限")} rules={[{ required: true, type: 'integer', min: 1, max: 100000 }]}><InputNumber min={1} max={100000} precision={0} /></Form.Item><Form.Item name={['budget', 'timeout_seconds']} label={t("执行超时（秒）")} rules={[{ required: true, type: 'integer', min: 1, max: 1800 }]}><InputNumber min={1} max={1800} precision={0} /></Form.Item><p className="section-footnote">{t("排队时间不计入超时。真实综述共享总 Token 和上下文预算；模拟流程至少需要两步，不产生模型用量。")}</p></> }]} />}
        <div className="submission-summary"><strong>{t("{0} 篇论文已选", [papers.length])}</strong><span>{t("提交后进入任务详情，可查看状态与执行事件。")}</span><Button type="primary" htmlType="submit" size="large" block loading={submitting} disabled={initialLoading} icon={<ArrowRightOutlined />} iconPlacement="end">{submitting ? t("正在提交") : t("创建研究任务")}</Button><p>{t("相同输入的失败请求可直接重试，不会重复创建任务。")}</p></div>
      </aside></div>
      {submitError && <div className="submission-error"><ErrorNotice error={submitError} title={t("提交未完成")} /><p>{t("保持输入不变，点击“创建研究任务”将复用原幂等键；修改输入则视为新任务。")}</p></div>}
    </Form></Spin>}
  </>;
}
