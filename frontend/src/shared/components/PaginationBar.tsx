import { t, useLocale } from '../../i18n';
import { Pagination } from 'antd';

export function PaginationBar({ total, page, pageSize = 20, onChange }: { total: number; page: number; pageSize?: number; onChange: (page: number) => void }) {
  useLocale();
  return <div className="pagination-bar"><span>{t("共 {0} 项", [total])}</span><Pagination current={page} pageSize={pageSize} total={total} onChange={onChange} showSizeChanger={false} responsive /></div>;
}
