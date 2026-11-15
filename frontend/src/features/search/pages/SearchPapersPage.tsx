import { errorText } from '../../../i18n/diagnostics';
import { t, useLocale, getLocale } from '../../../i18n';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Alert, Button, Empty, Input, Pagination, Spin, Tag } from 'antd';
import { ArrowRightOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { api, asApiError, isCanceled, type ApiError } from '../../../api/client';
import type { Page, PaperImport, SearchPaper } from '../../../api/types';
import { ErrorNotice } from '../../../shared/components/ErrorNotice';
import { PageHeader } from '../../../shared/components/PageHeader';
import { PaginationBar } from '../../../shared/components/PaginationBar';
import PaperAbstract from '../components/PaperAbstract';

const sortOptions = {
  relevance: { label: '相关度优先', sort_by: 'relevance', sort_order: 'descending' },
  'published-desc': { label: '发布时间：从新到旧', sort_by: 'submittedDate', sort_order: 'descending' },
  'published-asc': { label: '发布时间：从旧到新', sort_by: 'submittedDate', sort_order: 'ascending' },
  'updated-desc': { label: '更新时间：从新到旧', sort_by: 'lastUpdatedDate', sort_order: 'descending' },
  'updated-asc': { label: '更新时间：从旧到新', sort_by: 'lastUpdatedDate', sort_order: 'ascending' },
} as const;
type SearchSort = keyof typeof sortOptions;
type SearchSnapshot = { page: Page<SearchPaper>; query: string; sort: SearchSort; receivedAt: string; reveal: boolean };
const pageSizeOptions = [10, 25, 50];
const maximumOffset = 1000;

function pending(item: PaperImport): boolean {
  return item.status === 'queued' || item.status === 'running' || (item.status === 'succeeded' && (item.paper_status === 'uploaded' || item.paper_status === 'processing'));
}

function importLabel(status: PaperImport['status'], paperStatus: PaperImport['paper_status']): string {
  if (status === 'queued') return t("等待导入");
  if (status === 'running') return t("正在下载");
  if (status === 'failed') return t("导入失败");
  if (paperStatus === 'ready') return t("已导入 · 可用于研究");
  if (paperStatus === 'failed') return t("已导入 · 解析失败");
  return t("已导入 · 正在解析");
}

function arxivUrl(identity: string, kind: 'abs' | 'pdf'): string | undefined {
  return /^(?:\d{4}\.\d{4,5}|[a-z][a-z-]*(?:\.[A-Z]{2})?\/\d{7})v[1-9]\d*$/.test(identity) ? `https://arxiv.org/${kind}/${identity}` : undefined;
}

export default function SearchPapersPage() {
  useLocale();
  const [draft, setDraft] = useState('');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<SearchSort>('relevance');
  const [pageSize, setPageSize] = useState(10);
  const [requestedOffset, setRequestedOffset] = useState(0);
  const [snapshot, setSnapshot] = useState<SearchSnapshot | null>(null);
  const result = snapshot?.page ?? null;
  const resultPageSize = result?.limit ?? pageSize;
  const maximumPages = Math.floor(maximumOffset / resultPageSize) + 1;
  const maximumResults = maximumPages * resultPageSize;
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<ApiError | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [cooldownUntil, setCooldownUntil] = useState(0);
  const [searchRetryUntil, setSearchRetryUntil] = useState(0);
  const [seconds, setSeconds] = useState(0);
  const [searchSeconds, setSearchSeconds] = useState(0);
  const [history, setHistory] = useState<Page<PaperImport> | null>(null);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyError, setHistoryError] = useState<ApiError | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [records, setRecords] = useState<Record<string, PaperImport>>({});
  const [busy, setBusy] = useState<string[]>([]);
  const known = useRef<Record<string, PaperImport>>({});
  const searchRequest = useRef<AbortController | null>(null);
  const actions = useRef(new Map<string, AbortController>());
  const retryAttempts = useRef(new Map<string, number>());
  const sequence = useRef(0);
  const resultsHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (!snapshot?.reveal) return;
    const frame = requestAnimationFrame(() => {
      resultsHeading.current?.scrollIntoView({ behavior: 'instant', block: 'start' });
      resultsHeading.current?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [snapshot]);

  function remember(items: PaperImport[]) {
    const next = { ...known.current };
    items.forEach((item) => {
      const previous = next[item.external_id];
      if (!previous || item.attempt > previous.attempt || (item.attempt === previous.attempt && item.updated_at >= previous.updated_at)) next[item.external_id] = item;
    });
    known.current = next;
    setRecords(next);
  }

  function rateLimit(error: ApiError) {
    if (error.status === 429) setCooldownUntil(Date.now() + (error.retryAfterSeconds ?? 60) * 1000);
  }

  useEffect(() => {
    const tick = () => {
      const now = Date.now();
      setSeconds(Math.max(0, Math.ceil((cooldownUntil - now) / 1000)));
      setSearchSeconds(Math.max(0, Math.ceil((Math.max(cooldownUntil, searchRetryUntil) - now) / 1000)));
    };
    tick();
    if (!cooldownUntil && !searchRetryUntil) return;
    const timer = window.setInterval(tick, 250);
    return () => window.clearInterval(timer);
  }, [cooldownUntil, searchRetryUntil]);

  useEffect(() => () => {
    sequence.current += 1;
    searchRequest.current?.abort();
    actions.current.forEach((controller) => controller.abort());
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    async function load() {
      setHistoryLoading(true);
      try {
        const page = await api.imports({ limit: 20, offset: (historyPage - 1) * 20 }, controller.signal);
        const visible = new Set(page.items.map((item) => item.id));
        const tracked = Object.values(known.current).filter((item) => pending(item) && !visible.has(item.id));
        const extra = await Promise.all(tracked.map((item) => api.paperImport(item.id, controller.signal)));
        if (controller.signal.aborted) return;
        remember([...extra, ...page.items]);
        setHistory(page);
        setHistoryError(null);
        if (Object.values(known.current).some(pending)) timer = window.setTimeout(() => void load(), 2000);
      } catch (error) {
        if (!isCanceled(error) && !controller.signal.aborted) {
          setHistoryError(asApiError(error));
          if (Object.values(known.current).some(pending)) timer = window.setTimeout(() => void load(), 2000);
        }
      } finally {
        if (!controller.signal.aborted) setHistoryLoading(false);
      }
    }
    void load();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [historyPage, refresh]);

  async function search(term: string, offset = 0, ordering: SearchSort = sort, reveal = false, limit = pageSize) {
    if (Date.now() < Math.max(cooldownUntil, searchRetryUntil) || !term.trim()) return;
    searchRequest.current?.abort();
    const controller = new AbortController();
    searchRequest.current = controller;
    const current = ++sequence.current;
    setSearching(true);
    setQuery(term.trim());
    setSort(ordering);
    setPageSize(limit);
    setRequestedOffset(offset);
    setSearchError(null);
    try {
      const { sort_by, sort_order } = sortOptions[ordering];
      const page = await api.searchPapers({ q: term.trim(), limit, offset, sort_by, sort_order }, controller.signal);
      if (current === sequence.current && !controller.signal.aborted) {
        setSearching(false);
        setSnapshot({ page, query: term.trim(), sort: ordering, receivedAt: new Date().toISOString(), reveal });
        const imported = page.items.filter((paper) => paper.import_id);
        try {
          const locals = await Promise.all(imported.map((paper) => api.paperImport(paper.import_id!, controller.signal)));
          if (current === sequence.current && !controller.signal.aborted && locals.length) {
            remember(locals);
            setRefresh((value) => value + 1);
          }
        } catch (error) {
          if (current === sequence.current && !isCanceled(error) && !controller.signal.aborted) {
            const failure = asApiError(error);
            setHistoryError(failure);
            rateLimit(failure);
          }
        }
      }
    } catch (error) {
      if (current === sequence.current && !isCanceled(error) && !controller.signal.aborted) {
        const failure = asApiError(error);
        setSearchError(failure);
        if (failure.code === 'ARXIV_TIMEOUT') setSearchRetryUntil(Date.now() + 5000);
        rateLimit(failure);
      }
    } finally {
      if (current === sequence.current && !controller.signal.aborted) setSearching(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void search(draft);
  }

  async function importPaper(identity: string, retry?: PaperImport) {
    if (actions.current.has(identity) || Date.now() < cooldownUntil) return;
    const controller = new AbortController();
    actions.current.set(identity, controller);
    setBusy([...actions.current.keys()]);
    setActionError(null);
    try {
      if (retry && !retryAttempts.current.has(retry.id)) retryAttempts.current.set(retry.id, retry.attempt);
      const item = retry
        ? await api.retryImport(retry.id, retryAttempts.current.get(retry.id)!, controller.signal)
        : await api.importPaper(identity, controller.signal);
      if (controller.signal.aborted) return;
      if (retry) retryAttempts.current.delete(retry.id);
      remember([item]);
      setRefresh((value) => value + 1);
    } catch (error) {
      if (!isCanceled(error) && !controller.signal.aborted) {
        const failure = asApiError(error);
        setActionError(failure);
        rateLimit(failure);
      }
    } finally {
      actions.current.delete(identity);
      if (!controller.signal.aborted) setBusy([...actions.current.keys()]);
    }
  }

  function importActions(item: PaperImport) {
    return <div className="import-actions">
      <Tag color={item.status === 'failed' || item.paper_status === 'failed' ? 'error' : item.paper_status === 'ready' ? 'success' : 'processing'}>{importLabel(item.status, item.paper_status)}</Tag>
      {item.status === 'failed' && item.error?.details.retryable === true && <Button size="small" disabled={seconds > 0} loading={busy.includes(item.external_id)} onClick={() => void importPaper(item.external_id, item)}>{t("重新下载")}</Button>}
      {item.paper_id && <Link to="/papers">{t("查看论文库")}</Link>}
      {item.paper_id && item.paper_status === 'ready' && <Link to={`/tasks/new?paper_id=${encodeURIComponent(item.paper_id)}`}>{t("用于研究")}<ArrowRightOutlined /></Link>}
    </div>;
  }

  return <>
    <PageHeader title={t("搜索论文")} description={t("从 arXiv 发现文献，将指定版本保存为可追溯的研究资料。")} action={<Link to="/papers"><Button>{t("返回论文库")}</Button></Link>} />
    <div className="search-layout"><section className="content-panel search-panel">
      <form className="arxiv-search-form" onSubmit={submit}>
        <label htmlFor="arxiv-keywords">{t("arXiv 关键词")}</label>
        <div className="search-input-row"><Input id="arxiv-keywords" value={draft} maxLength={200} placeholder={t("例如：attention transformer")} onChange={(event) => setDraft(event.target.value)} /><Button type="primary" htmlType="submit" aria-label={t("搜索")} icon={<SearchOutlined />} loading={searching} disabled={!draft.trim() || searchSeconds > 0}>{t("搜索")}</Button></div>
        <p>{t('多个词按 AND 匹配；输入关键词后提交搜索。不支持输入网址或高级检索语法。')}</p>
        <div className="search-options"><div className="search-option-field"><label htmlFor="search-sort">{t('结果排序')}</label><select id="search-sort" value={sort} disabled={searching || searchSeconds > 0} onChange={(event) => {
          const ordering = event.target.value as SearchSort;
          if (query) void search(query, 0, ordering, true);
          else setSort(ordering);
        }}>{Object.entries(sortOptions).map(([value, option]) => <option key={value} value={value}>{t(option.label)}</option>)}</select></div>
          <div className="search-option-field"><label htmlFor="search-page-size">{t('每页显示')}</label><select id="search-page-size" value={pageSize} disabled={searching || searchSeconds > 0} onChange={(event) => {
            const size = Number(event.target.value);
            if (query) void search(query, 0, sort, true, size);
            else setPageSize(size);
          }}>{pageSizeOptions.map((size) => <option key={size} value={size}>{t('{0} 篇', [size])}</option>)}</select></div>
        </div>
      </form>
      {seconds > 0 && <Alert type="warning" showIcon title={t("{0} 秒后可重试", [seconds])} description={t("共享来源访问额度正在冷却。不会自动重新搜索或下载。")} />}
      {seconds === 0 && searchSeconds > 0 && <Alert type="warning" showIcon title={t("{0} 秒后可重试搜索", [searchSeconds])} description={t("本次搜索超时。不会自动重试；已有论文和导入记录不受影响。")} />}
      {searchError && (searchError.code === 'ARXIV_NOT_CONFIGURED'
        ? <Alert type="info" showIcon title={t("arXiv 尚未配置")} description={<>{t("请在后端配置联系邮箱并启用 arXiv；现有导入记录仍可查看，也可以")}<Link to="/papers">{t("手动上传 PDF")}</Link>。</>} />
        : <ErrorNotice error={searchError} retry={searchSeconds || searching ? undefined : () => void search(query, requestedOffset, sort, true)} />)}
      {actionError && <ErrorNotice error={actionError} title={t("导入请求未完成")} />}
      {searching && <div className="search-loading" role="status"><Spin size="small" />{t("正在查询 arXiv…")}</div>}
      {snapshot && result && <div aria-busy={searching}>
        {(searching || searchError) && <Alert type="info" showIcon title={t("仍显示上次成功结果")} description={searching ? t("新请求正在进行，以下结果尚未更新。关键词、页码和接收时间以结果区标注为准。") : t("本次请求未完成，以下不是本次请求的新结果。关键词、页码和接收时间以结果区标注为准。")} />}
        <div className="search-result-heading"><h2 id="search-results-heading" ref={resultsHeading} tabIndex={-1}>{t("检索结果")}</h2><span role="status">{t("共 {0} 篇 · 第 {1} 页", [result.total, Math.floor(result.offset / resultPageSize) + 1])}</span></div>
        <p className="search-result-context">{t("关键词：")}<strong>{snapshot.query}</strong>{t("· 接收时间：")}<time dateTime={snapshot.receivedAt}>{new Date(snapshot.receivedAt).toLocaleString(getLocale(), { hour12: false })}</time></p>
        {result.items.length === 0 && <Empty description={t("没有找到匹配论文")} />}
        <p className="search-sort-context">{t('排序：{0}', [t(sortOptions[snapshot.sort].label)])}</p>
        <div className="search-results" key={snapshot.query + ':' + result.offset + ':' + result.limit + ':' + snapshot.sort}>{result.items.map((paper) => {
          const item = records[paper.external_id];
          return <article key={paper.external_id} className="search-paper">
            <div className="source-identity"><span>arXiv · {paper.external_id}</span><span>{t('发布于 {0}', [new Date(paper.published_at).toLocaleDateString(getLocale())])}</span>{snapshot.sort.startsWith('updated') && <span>{t('更新于 {0}', [new Date(paper.source_updated_at).toLocaleDateString(getLocale())])}</span>}</div>
            <h3>{paper.title}</h3><p className="paper-authors">{paper.authors.join(' · ')}</p>
            <PaperAbstract text={paper.abstract} />
            <div className="source-categories">{paper.categories.map((category) => <Tag key={category}>{category}</Tag>)}</div>
            <div className="search-paper-footer"><div className="source-links">{arxivUrl(paper.external_id, 'abs') && <a href={arxivUrl(paper.external_id, 'abs')} target="_blank" rel="noopener noreferrer">{t("arXiv 原文")}</a>}{arxivUrl(paper.external_id, 'pdf') && <a href={arxivUrl(paper.external_id, 'pdf')} target="_blank" rel="noopener noreferrer">{t("来源 PDF")}</a>}</div>
              {item ? importActions(item) : paper.import_status ? <Tag>{importLabel(paper.import_status, paper.paper_status)}</Tag> : <Button disabled={seconds > 0} loading={busy.includes(paper.external_id)} onClick={() => void importPaper(paper.external_id)}>{t("导入 PDF")}</Button>}
            </div>
          </article>;
        })}</div>
        {result.total > 0 && <nav className="search-pagination" aria-label={t('搜索结果分页')}>
          <p>{t('每页 {0} 篇 · 可浏览 {1} 页', [resultPageSize, Math.ceil(Math.min(result.total, maximumResults) / resultPageSize)])}{result.total > maximumResults && <span>{t('仅展示前 {0} 页，可缩小关键词范围以查找更多论文。', [maximumPages])}</span>}</p>
          <Pagination current={Math.floor(result.offset / resultPageSize) + 1} pageSize={resultPageSize} total={Math.min(result.total, maximumResults)} disabled={searching || searchSeconds > 0} showSizeChanger={false} showQuickJumper showLessItems onChange={(page) => void search(snapshot.query, (page - 1) * resultPageSize, snapshot.sort, true, resultPageSize)} />
        </nav>}
      </div>}
      {!query && <div className="search-intro"><SearchOutlined /><h2>{t("发现文献，再开始研究")}</h2><p>{t("搜索只读取来源元数据。点击「导入 PDF」后，由独立 Worker 下载并交给解析器，不会调用模型。")}</p></div>}
    </section>
    <section className="content-panel import-history">
      <div className="panel-heading"><div><h2>{t("导入记录")}</h2><p>{t("记录保存在服务器；下载完成不等于解析就绪。待处理记录每 2 秒刷新。")}</p></div><Button icon={<ReloadOutlined />} loading={historyLoading} onClick={() => setRefresh((value) => value + 1)}>{t("刷新记录")}</Button></div>
      {historyError && <ErrorNotice error={historyError} retry={() => setRefresh((value) => value + 1)} />}
      {history?.items.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("还没有导入记录")} />}
      <ul className="import-records">{history?.items.map((original) => {
        const item = records[original.external_id] ?? original;
        return <li key={item.id}><div><strong>{item.external_id}</strong><span>{t("第 {0} 次尝试", [item.attempt])}</span>{item.error && <p role="status">{errorText(item.error)}</p>}{item.paper_status === 'failed' && <p>{t("文件已保存，但未能解析文本。请在论文库查看原因；重新下载不会重试解析。")}</p>}</div>{importActions(item)}</li>;
      })}</ul>
      {history && history.total > 20 && <PaginationBar total={history.total} page={historyPage} onChange={setHistoryPage} />}
    </section></div>
  </>;
}
