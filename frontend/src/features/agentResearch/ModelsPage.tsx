import { useState } from 'react';
import { App, Button, Descriptions, Input, Popconfirm, Space, Tag } from 'antd';
import { changeService, loadModels, pollModels, setModelUrl, type ModelState } from '../../api/models';
import { asApiError } from '../../api/client';
import { t, useLocale } from '../../i18n';
import { ErrorNotice } from '../../shared/components/ErrorNotice';
import { useResource } from '../../shared/hooks/useResource';

const labels: Record<ModelState, string> = {
  unreachable: '无法确认服务状态', requested: '等待 Worker 提交', submitting: '正在提交', unconfirmed: '等待提交确认', queued: '排队中',
  loading: '加载中', ready: '可用', stopping: '正在停止', stopped: '未运行', failed: '启动失败',
};

export default function ModelsPage() {
  const locale = useLocale();
  const { data, error, reload } = useResource(loadModels, 10000, pollModels);
  const [draft, setDraft] = useState<string>();
  const [busy, setBusy] = useState(false);
  const { notification } = App.useApp();
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
  return <><div className="page-heading"><h1>{t('模型管理')}</h1><Button onClick={reload}>{t('刷新')}</Button></div>
    {error && <ErrorNotice error={error} retry={reload} />}
    {data && <><section className="content-panel"><h2>{t('百炼 API')}</h2>
      <Space><span>{data.bailian_name}</span><Tag>{t({local: '已配置', remote: '使用远端配置', missing: '缺少配置文件'}[data.bailian_config])}</Tag></Space></section>
      <section className="content-panel"><h2>{t('课程模型服务')}</h2>
        <Space wrap><Tag color={data.state === 'ready' ? 'green' : undefined}>{t(labels[data.state])}</Tag>
          {inactive ? <Button type="primary" loading={busy} disabled={!data.enabled} onClick={() => change('start')}>{t('启动 TACC 服务')}</Button>
            : <Popconfirm title={t('停止后，使用此模型的研究可能中断。')} onConfirm={() => change('stop')}>
                <Button loading={busy} disabled={!data.owner || data.state === 'stopping'}>{t('停止服务')}</Button></Popconfirm>}
        </Space>
        {!data.enabled && <p>{t('课程 TCloud Worker 尚未启用')}</p>}
        {data.detail && <p role="status">{t(data.detail)}</p>}
        <Descriptions column={1} size="small" style={{marginTop: 16}}>
          <Descriptions.Item label={t('模型')}>qwen3.8-27b</Descriptions.Item>
          {data.job_id && <Descriptions.Item label={t('GPU 作业号')}>{data.job_id}</Descriptions.Item>}
          {data.base_url && <Descriptions.Item label="URL">{data.base_url}</Descriptions.Item>}
          {data.state === 'queued' && data.requested_at && <Descriptions.Item label={t('已等待')}>
            {t('{0} 分钟', [Math.max(0, Math.floor((Date.now() - Date.parse(data.requested_at)) / 60000))])}</Descriptions.Item>}
          {data.requested_at && <Descriptions.Item label={t('启动请求时间')}>{new Date(data.requested_at).toLocaleString(locale)}</Descriptions.Item>}
          {data.checked_at && <Descriptions.Item label={t('最近检查')}>{new Date(data.checked_at).toLocaleTimeString(locale)}</Descriptions.Item>}
        </Descriptions>
      </section>
      <section className="content-panel"><h2>{t('指定服务地址')}</h2>
        <label htmlFor="course-url">{t('默认服务地址')}</label>
        <Space.Compact style={{width: '100%', maxWidth: 600, display: 'flex'}}>
          <Input id="course-url" placeholder={'http://10.0.3.10:8000/v1'} allowClear
            value={draft ?? data.shared_url ?? ''} onChange={event => setDraft(event.target.value)} />
          <Button disabled={draft === undefined} loading={busy} onClick={saveUrl}>{t('保存')}</Button>
        </Space.Compact>
      </section></>}
  </>;
}
