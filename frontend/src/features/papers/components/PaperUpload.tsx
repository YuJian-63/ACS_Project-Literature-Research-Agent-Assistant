import { errorText } from '../../../i18n/diagnostics';
import { t, useLocale } from '../../../i18n';
import { useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Progress, Upload } from 'antd';
import { FilePdfOutlined, UploadOutlined } from '@ant-design/icons';
import type { UploadProps } from 'antd';
import { api, ApiError, asApiError, isCanceled } from '../../../api/client';
import { validatePdf } from '../lib/validation';

export function PaperUpload({ onUploaded }: { onUploaded: () => void }) {
  useLocale();
  const { message } = App.useApp();
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<ApiError>();
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  const customRequest: UploadProps['customRequest'] = (options) => {
    if (!(options.file instanceof File) || controller.current) return;
    const file = options.file;
    const pending = new AbortController();
    controller.current = pending;
    setBusy(true);
    setError(undefined);
    setProgress(0);
    void (async () => {
      try {
        const failure = await validatePdf(file);
        if (failure) throw new Error(failure);
        if (pending.signal.aborted) return;
        await api.upload(file, pending.signal, setProgress);
        if (pending.signal.aborted) return;
        setProgress(100);
        options.onSuccess?.({});
        void message.success(t("论文已保存，可选择论文并新建任务。"));
        onUploaded();
      } catch (failure) {
        if (pending.signal.aborted || isCanceled(failure)) return;
        const normalized = failure instanceof Error && !(failure instanceof ApiError)
          ? new ApiError(failure.message, 'INVALID_FILE') : asApiError(failure);
        setError(normalized);
        options.onError?.(new Error(normalized.message));
      } finally {
        if (!pending.signal.aborted) setBusy(false);
        controller.current = null;
      }
    })();
    return { abort: () => pending.abort() };
  };

  return <section className="upload-section" aria-label={t("上传论文")}>
    <Upload.Dragger name="file" accept=".pdf,application/pdf" multiple={false} showUploadList={false} disabled={busy} customRequest={customRequest}
      beforeUpload={(_file, files) => {
        if (files.length !== 1) {
          void message.warning(t("一次只能上传一个 PDF 文件。"));
          return Upload.LIST_IGNORE;
        }
        return true;
      }}>
      <div className="upload-content"><div className="upload-file-icon"><FilePdfOutlined /></div><div className="upload-copy"><h2>{busy ? t("正在上传并保存论文") : t("将论文放入你的研究资料库")}</h2><p>{t("拖放 PDF 到这里，或点击选择。单个文件最大 20 MiB。")}</p></div><Button type="primary" icon={<UploadOutlined />} loading={busy}>{busy ? t("正在上传") : t("选择 PDF")}</Button></div>
    </Upload.Dragger>
    {busy && <div className="upload-progress" aria-live="polite"><Progress percent={progress} size="small" />{progress >= 99 && <span>{t("正在确认文件保存结果…")}</span>}</div>}
    {error && <Alert type="error" showIcon title={t("上传未完成")} description={<>{errorText(error)}{error.requestId && <small className="request-id">{t("请求编号：{0}", [error.requestId])}</small>}</>} closable onClose={() => setError(undefined)} />}
    <details className="upload-explanation"><summary>{t("上传与解析说明")}</summary><p className="section-footnote">{t("上传后由独立解析 Worker 提取文本；未启动时保持“已上传”。上传成功或解析就绪均不代表已完成研究分析。")}</p></details>
  </section>;
}
