import { t, useLocale } from '../../i18n';
import { Button, Pagination } from 'antd';
import { ArrowUpOutlined } from '@ant-design/icons';

export function PaginationBar({ total, page, pageSize = 20, onChange, showBackToTop = false }: { total: number; page: number; pageSize?: number; onChange: (page: number) => void; showBackToTop?: boolean }) {
  useLocale();
  function backToTop() {
    window.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
  }
  return <div className="pagination-bar"><span>{t("共 {0} 项", [total])}</span><div className="pagination-actions"><Pagination current={page} pageSize={pageSize} total={total} onChange={onChange} showSizeChanger={false} responsive />{showBackToTop && <Button aria-label={t('回到顶部')} icon={<ArrowUpOutlined aria-hidden />} onClick={backToTop}>{t('回到顶部')}</Button>}</div></div>;
}
