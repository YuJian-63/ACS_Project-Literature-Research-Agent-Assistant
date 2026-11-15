import { t, useLocale } from '../../i18n';
import { Pagination } from 'antd';

export function PaginationBar({ total, page, onChange }: { total: number; page: number; onChange: (page: number) => void }) {
  useLocale();
  return <div className="pagination-bar"><span>{t("共 {0} 项", [total])}</span><Pagination current={page} pageSize={20} total={total} onChange={onChange} showSizeChanger={false} responsive /></div>;
}
