import { t, useLocale } from '../../i18n';
import { Tag } from 'antd';

export function MockTag() {
  useLocale();
  return <Tag color="gold" className="mock-tag">{t("模拟运行")}</Tag>;
}
