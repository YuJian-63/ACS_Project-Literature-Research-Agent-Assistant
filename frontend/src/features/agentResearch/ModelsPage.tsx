import { useState } from 'react';
import { App, Button, Descriptions, Input, Popconfirm, Radio, Space, Tag } from 'antd';
import { changeService, loadModels, pollModels, setModelUrl, type ModelState } from '../../api/models';
import { agentResearch } from '../../api/agentResearch';
import { asApiError } from '../../api/client';
import { t, useLocale } from '../../i18n';
import { errorText } from '../../i18n/diagnostics';
import { ErrorNotice } from '../../shared/components/ErrorNotice';
import { useResource } from '../../shared/hooks/useResource';

const labels: Record<ModelState, string> = {
  unreachable: '无法确认服务状态', requested: '等待 Worker 提交', submitting: '正在提交', unconfirmed: '等待提交确认', queued: '排队中',
  loading: '加载中', ready: '可用', stopping: '正在停止', stopped: '未运行', failed: '启动失败',
};
const pollQueue = () => true;

export default function ModelsPage() {
  const locale = useLocale();
  const { data, error, reload } = useResource(loadModels, 10000, pollModels);
  const queue = useResource(agentResearch.getConcurrency, 5000, pollQueue);
  const [draft, setDraft] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [savingLimit, setSavingLimit] = useState(false);
  const { notification, message } = App.useApp();
  async function changeLimit(limit: number) {
    setSavingLimit(true);
    try {
      await agentResearch.setConcurrency(limit);
      void message.success(t('全站并发已设为 {0}', [limit]));
    } catch (err) {
      void message.error(errorText(asApiError(err)));
    } finally {
      setSavingLimit(false);
      queue.reload();
    }
  }
  async function change(action: 'start' | 'stop') {
    setBusy(true);
    try { await changeService(action, data?.generation); reload(); }
    catch (err) { notification.error({ title: asApiError(err).message }); }
    finally { setBusy(false); }
  }
  async function saveUrl() {
    if (draft === undefined) return;
    const url = draft.trim().replace(/\/+$/, '');
    if (url && !/^http:\/\/10\.0\.(?:0|[1-9]\d{0,2})\.(?:0|[1-9]\d{0,2}):8000\/v1$/.test(url)) {
      notification.error({ title: t('请输入有效的 TACC 地址，例如 http://10.0.3.10:8000/v1') });
      return;
    }
    setBusy(true);
    try { await setModelUrl(url); setDraft(undefined); reload(); }
    catch (err) { notification.error({ title: asApiError(err).message }); }
    finally { setBusy(false); }
  }
  const inactive = data?.state === 'stopped' || data?.state === 'failed';
  return <div className="models-page">
    <div className="page-heading"><div><h1>{t('模型管理')}</h1><p>{t('配置研究模型与全站任务容量')}</p></div><Button onClick={reload}>{t('刷新')}</Button></div>
    {error && <ErrorNotice error={error} retry={reload} />}
    <div className="models-dashboard">
      {data && <>
        <section className="content-panel models-service">
          <div className="models-panel-heading"><div><h2>{t('课程模型服务')}</h2><p>{t('在 TACC GPU 节点运行的模型')}</p></div><Tag color={data.state === 'ready' ? 'green' : undefined}>{t(labels[data.state])}</Tag></div>
          {!data.enabled && <p className="models-detail">{t('课程 TCloud Worker 尚未启用')}</p>}
          {data.detail && <p className="models-detail" role="status">{t(data.detail)}</p>}
          <Descriptions column={1} size="small" className="models-descriptions">
            <Descriptions.Item label={t('模型')}>qwen3.8-27b</Descriptions.Item>
            {data.job_id && <Descriptions.Item label={t('GPU 作业号')}>{data.job_id}</Descriptions.Item>}
            {data.base_url && <Descriptions.Item label="URL">{data.base_url}</Descriptions.Item>}
            {data.state === 'queued' && data.requested_at && <Descriptions.Item label={t('已等待')}>
              {t('{0} 分钟', [Math.max(0, Math.floor((Date.now() - Date.parse(data.requested_at)) / 60000))])}</Descriptions.Item>}
            {data.requested_at && <Descriptions.Item label={t('启动请求时间')}>{new Date(data.requested_at).toLocaleString(locale)}</Descriptions.Item>}
            {data.checked_at && <Descriptions.Item label={t('最近检查')}>{new Date(data.checked_at).toLocaleTimeString(locale)}</Descriptions.Item>}
          </Descriptions>
          <div className="models-service-action">{inactive ? <Button type="primary" loading={busy} disabled={!data.enabled} onClick={() => change('start')}>{t('启动 TACC 服务')}</Button>
            : <Popconfirm title={t('停止后，使用此模型的研究可能中断。')} onConfirm={() => change('stop')}>
                <Button loading={busy} disabled={!data.owner || data.state === 'stopping'}>{t('停止服务')}</Button></Popconfirm>}</div>
        </section>
        <div className="models-connections">
          <section className="content-panel models-bailian">
            <div className="models-panel-heading"><div><h2>{t('百炼 API')}</h2><p>{t('标准研究模型与嵌入服务')}</p></div></div>
            <div className="models-bailian-model"><strong>{data.bailian_name || '—'}</strong><Tag color={data.bailian_config === 'missing' ? undefined : 'green'}>{t({local: '已配置', remote: '使用远端配置', missing: '缺少配置文件'}[data.bailian_config])}</Tag></div>
          </section>
          <section className="content-panel models-endpoint">
            <div><h2>{t('指定服务地址')}</h2><p>{t('连接已在 TACC 上运行的模型服务')}</p></div>
            <label htmlFor="course-url">{t('默认服务地址')}</label>
            <Space.Compact className="models-url-field">
              <Input id="course-url" autoComplete="off" placeholder="http://10.0.3.10:8000/v1" allowClear
                value={draft ?? ''} onChange={event => setDraft(event.target.value)} />
              <Button disabled={draft === undefined} loading={busy} onClick={saveUrl}>{t('保存')}</Button>
            </Space.Compact>
          </section>
        </div>
      </>}
    </div>
    <div className="page-heading concurrency-heading"><div><h1>{t('并发管理')}</h1><p>{t('配置研究任务并发上限')}</p></div></div>
    <div className="models-dashboard">
      <section className="content-panel models-concurrency">
        <div><h2 id="research-concurrency-label">{t('研究并发数')}</h2><p>{t('同时运行的研究任务上限，所有账号共享')}</p></div>
        <Radio.Group aria-labelledby="research-concurrency-label" optionType="button"
          options={[1, 2, 3, 4]} value={queue.data?.concurrency} disabled={!queue.data || savingLimit}
          onChange={event => void changeLimit(event.target.value)} />
        {queue.error && <ErrorNotice error={queue.error} retry={queue.reload} />}
      </section>
    </div>
  </div>;
}
