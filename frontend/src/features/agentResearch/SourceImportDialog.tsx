import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Modal, Spin } from 'antd';
import { Link } from 'react-router-dom';
import { api, ApiError, asApiError, isCanceled } from '../../api/client';
import type { AgentSource } from '../../api/agentResearch';
import type { PaperImport } from '../../api/types';
import { t, useLocale } from '../../i18n';
import { ErrorNotice } from '../../shared/components/ErrorNotice';
import { importedPaperProblem, isPaperId, resolveResearchSource } from './lib/researchSource';

type Phase = 'idle' | 'submitting' | 'queued' | 'running' | 'parsing' | 'download-failed' | 'parse-failed' | 'error';
const progressLabels = { submitting: '正在提交导入', queued: '等待导入', running: '正在下载', parsing: '正在解析论文' } as const;
const problemMessages = {
  'version-mismatch': '导入论文的版本与引用来源不一致，无法打开对应页。',
  'content-mismatch': '导入 PDF 的内容与引用来源不一致，无法打开对应页。',
  'page-out-of-range': '引用页码超出了导入 PDF 的范围，无法打开对应页。',
};

export default function SourceImportDialog({ source, page, onRead, onClose }: {
  source: AgentSource; page?: number; onRead: (paperId: string) => void; onClose: () => void;
}) {
  useLocale();
  const resolved = resolveResearchSource(source);
  const [phase, setPhase] = useState<Phase>('idle');
  const [record, setRecord] = useState<PaperImport>();
  const [error, setError] = useState<ApiError>();
  const [retryAt, setRetryAt] = useState(0);
  const request = useRef<AbortController | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const busy = phase === 'submitting' || phase === 'queued' || phase === 'running' || phase === 'parsing';

  useEffect(() => () => { request.current?.abort(); window.clearTimeout(timer.current); }, []);
  useEffect(() => {
    if (!retryAt) return;
    const timeout = window.setTimeout(() => setRetryAt(0), Math.max(0, retryAt - Date.now()));
    return () => window.clearTimeout(timeout);
  }, [retryAt]);

  function fail(failure: unknown, controller: AbortController, nextPhase: Phase = 'error') {
    if (controller.signal.aborted || isCanceled(failure)) return;
    const problem = asApiError(failure);
    setError(problem);
    setPhase(nextPhase);
    if (problem.retryAfterSeconds) setRetryAt(Date.now() + problem.retryAfterSeconds * 1000);
    request.current = null;
  }

  async function observe(item: PaperImport, controller: AbortController): Promise<void> {
    if (controller.signal.aborted || resolved.kind !== 'arxiv') return;
    if (item.provider !== 'arxiv' || item.external_id !== resolved.externalId || !isPaperId(item.id)) {
      throw new ApiError('导入论文的版本与引用来源不一致，无法打开对应页。', 'ARXIV_VERSION_MISMATCH');
    }
    setRecord(item);
    if (item.status === 'failed') {
      fail(new ApiError(item.error?.message || '导入失败', item.error?.code || 'IMPORT_FAILED'), controller, 'download-failed');
      return;
    }
    if (item.status === 'succeeded') {
      if (!item.paper_id || !isPaperId(item.paper_id)) throw new ApiError('导入结果缺少有效的论文记录，请重试。', 'INVALID_IMPORT_RESULT');
      setPhase('parsing');
      const paper = await api.paper(item.paper_id, controller.signal);
      if (controller.signal.aborted) return;
      if (paper.id !== item.paper_id) throw new ApiError('导入结果缺少有效的论文记录，请重试。', 'INVALID_IMPORT_RESULT');
      if (paper.status === 'failed') {
        fail(new ApiError('论文解析失败，请前往论文库检查。', 'PDF_PARSE_FAILED'), controller, 'parse-failed');
        return;
      }
      if (paper.status === 'ready') {
        const problem = importedPaperProblem(resolved, paper, page);
        if (problem) throw new ApiError(problemMessages[problem], 'IMPORT_SOURCE_MISMATCH');
        onRead(paper.id);
        return;
      }
    } else setPhase(item.status);
    timer.current = window.setTimeout(() => void refresh(item.id, controller), 2000);
  }

  async function refresh(id: string, controller: AbortController) {
    try { await observe(await api.paperImport(id, controller.signal), controller); }
    catch (failure) { fail(failure, controller); }
  }

  async function start(mode: 'import' | 'retry' | 'check' = 'import') {
    if (resolved.kind !== 'arxiv' || request.current || retryAt > Date.now()) return;
    const controller = new AbortController();
    request.current = controller;
    setError(undefined);
    setPhase('submitting');
    try {
      const item = mode === 'retry' && record
        ? await api.retryImport(record.id, record.attempt, controller.signal)
        : mode === 'check' && record
          ? await api.paperImport(record.id, controller.signal)
          : await api.importPaper(resolved.externalId, controller.signal);
      await observe(item, controller);
    } catch (failure) { fail(failure, controller); }
  }

  const retryMode = phase === 'download-failed' ? 'retry' : record ? 'check' : 'import';
  const actionLabel = phase === 'idle' ? '导入并阅读' : phase === 'download-failed' ? '重试导入' : record ? '重新检查' : '重试导入';
  return <Modal open title={t('导入论文后阅读')} onCancel={onClose} mask={{ closable: !busy }} footer={<>
    <Button onClick={onClose}>{t(busy ? '停止等待' : '取消')}</Button>
    {resolved.kind === 'arxiv' && <Button type="primary" loading={busy} disabled={busy || retryAt > Date.now()} onClick={() => void start(retryMode)}>{t(actionLabel)}</Button>}
  </>}>
    <p className="source-import-title">{source.title}</p>
    {resolved.kind === 'arxiv' ? <>
      <p>{t('将导入 arXiv 指定版本 {0}，下载并解析完成后打开论文。已导入的同版本论文会直接复用。', [resolved.externalId])}</p>
      {busy && <div className="source-import-status" role="status"><Spin size="small" /><span>{t(progressLabels[phase as keyof typeof progressLabels])}</span></div>}
      {(busy || record) && <p>{t('关闭弹窗不会取消后台导入。')}</p>}
      {error && <ErrorNotice error={error} title={t('暂时无法阅读此来源')} />}
      {retryAt > Date.now() && <p role="status">{t('请求过于频繁，请稍后重试。')}</p>}
      {phase === 'parse-failed' && <Link to="/papers">{t('前往论文库')}</Link>}
    </> : <Alert type="warning" showIcon title={t(resolved.kind === 'unavailable' && resolved.reason === 'missing-version'
      ? '来源缺少明确的 arXiv 版本，请先在搜索论文中确认版本。' : '无法识别此论文来源，请先在搜索论文中找到并导入。')} />}
  </Modal>;
}
