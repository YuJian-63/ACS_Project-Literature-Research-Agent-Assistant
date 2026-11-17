import { errorText } from '../../i18n/diagnostics';
import { t, useLocale } from '../../i18n';
import { Alert, Button } from 'antd';
import type { ApiError } from '../../api/client';

export function ErrorNotice({ error, retry, title = t("查询失败") }: { error: ApiError; retry?: () => void; title?: string }) {
  useLocale();
  return <Alert className="error-notice" type="error" showIcon title={title}
    description={<><p>{errorText(error)}</p>{error.requestId && <small>{t("请求编号：")}<span className="identifier">{error.requestId}</span></small>}</>}
    action={retry && <Button onClick={retry}>{t("重试查询")}</Button>} />;
}
