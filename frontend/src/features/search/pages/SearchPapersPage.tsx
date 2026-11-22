import { errorText } from '../../../i18n/diagnostics';
import { t, useLocale, getLocale } from '../../../i18n';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { notification as notificationApi, Button, Empty, Input, Pagination, Spin, Tag } from 'antd';
import { ArrowRightOutlined, SearchOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { api, asApiError, isCanceled, type ApiError } from '../../../api/client';
import type { Page, PaperImport, SearchPaper } from '../../../api/types';
import { PageHeader } from '../../../shared/components/PageHeader';
import PaperAbstract from '../components/PaperAbstract';
import MathText from '../../../shared/components/MathText';
import { importFeedback } from '../lib/importFeedback';

const sortOptions = {
  relevance: { label: '相关度优先', sort_by: 'relevance', sort_order: 'descending' },
  'published-desc': { label: '发布时间：从新到旧', sort_by: 'submittedDate', sort_order: 'descending' },
  'published-asc': { label: '发布时间：从旧到新', sort_by: 'submittedDate', sort_order: 'ascending' },
  'updated-desc': { label: '更新时间：从新到旧', sort_by: 'lastUpdatedDate', sort_order: 'descending' },
  'updated-asc': { label: '更新时间：从旧到新', sort_by: 'lastUpdatedDate', sort_order: 'ascending' },
} as const;
type SearchSort = keyof typeof sortOptions;
type SearchSnapshot = { page: Page<SearchPaper>; query: string; sort: SearchSort; reveal: boolean };
const pageSizeOptions = [10, 25, 50];
const maximumOffset = 1000;
// Keep the API stable so rerenders do not run the notification cleanup.
const searchNotificationConfig = { placement: 'top', duration: 3, maxCount: 3, stack: false, classNames: { list: 'search-notification-list' } } as const;

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

export default function SearchPapersPage({ active = true }: { active?: boolean }) {
  useLocale();
  const [notification, notificationHolder] = notificationApi.useNotification(searchNotificationConfig);
  const statusFailure = useRef('');
  const [draft, setDraft] = useState('');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<SearchSort>('relevance');
  const [pageSize, setPageSize] = useState(10);
  const [snapshot, setSnapshot] = useState<SearchSnapshot | null>(null);
  const result = snapshot?.page ?? null;
  const visibleIdentities = result?.items.map((paper) => paper.external_id).join(',') ?? '';
  const visibleImportIds = result?.items.map((paper) => paper.import_id || '').filter(Boolean).join(',') ?? '';
  const resultPageSize = result?.limit ?? pageSize;
  const maximumPages = Math.floor(maximumOffset / resultPageSize) + 1;
  const maximumResults = maximumPages * resultPageSize;
  const [searching, setSearching] = useState(false);
  const [cooldownUntil, setCooldownUntil] = useState(0);
  const [searchRetryUntil, setSearchRetryUntil] = useState(0);
  const [seconds, setSeconds] = useState(0);
  const [searchSeconds, setSearchSeconds] = useState(0);
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
    if (!active || !snapshot?.reveal) return;
    const frame = requestAnimationFrame(() => {
      resultsHeading.current?.scrollIntoView({ behavior: 'instant', block: 'start' });
      resultsHeading.current?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [snapshot, active]);

  function remember(items: PaperImport[], initiated = false) {
    const next = { ...known.current };
    items.forEach((item) => {
      const previous = next[item.external_id];
      if (previous && (item.attempt < previous.attempt || (item.attempt === previous.attempt && item.updated_at < previous.updated_at))) return;
      const feedback = importFeedback(previous, item, initiated);
      if (feedback) notification.open({
        key: 'paper-search-import-' + item.external_id,
        className: 'search-notification',
        type: feedback === 'failed' ? 'error' : feedback === 'parse-failed' ? 'warning' : 'success',
        title: t(feedback === 'failed' ? '导入失败' : feedback === 'parse-failed' ? '已导入 · 解析失败' : '导入成功'),
        description: <div className="search-notification-content"><p>arXiv · {item.external_id}</p>
          <p>{feedback === 'failed' ? (item.error ? errorText(item.error) : t('论文下载失败，请重试。')) : feedback === 'parse-failed' ? t('文件已保存，但未能解析文本。请在论文库查看原因；重新下载不会重试解析。') : t('PDF 已保存到论文库，解析状态请在论文库查看。')}</p>
          <Link to="/papers">{t('查看论文库')}</Link>
        </div>,
      });
      next[item.external_id] = item;
    });
    known.current = next;
    setRecords(next);
  }

  function forgetImport(id: string) {
    const next = { ...known.current };
    for (const [identity, item] of Object.entries(next)) if (item.id === id) delete next[identity];
    known.current = next;
    setRecords(next);
    setSnapshot((previous) => previous ? { ...previous, reveal: false, page: { ...previous.page, items: previous.page.items.map((paper) => paper.import_id === id ? { ...paper, import_id: null, import_status: null, paper_id: null, paper_status: null } : paper) } } : previous);
  }

  function notifyFailure(error: ApiError, kind: 'search' | 'import' | 'status', identity?: string) {
    const cooldown = error.status === 429 ? error.retryAfterSeconds ?? 60 : error.code === 'ARXIV_TIMEOUT' ? 5 : 0;
    const title = kind === 'import' ? t('导入请求未完成') : t('查询失败');
    notification.open({
      key: 'paper-search-' + kind + (identity ? '-' + identity : ''),
      className: 'search-notification',
      type: error.status === 429 ? 'warning' : 'error',
      title,
      placement: 'top',
      duration: 3,
      description: <div className="search-notification-content">
        <p>{identity && <>arXiv · {identity}<br /></>}{errorText(error)}</p>
        {cooldown > 0 && <p>{t('{0} 秒后可重试', [cooldown])} · {error.code === 'ARXIV_TIMEOUT' ? t('本次搜索超时。不会自动重试；已有论文和导入记录不受影响。') : t('共享来源访问额度正在冷却。不会自动重新搜索或下载。')}</p>}
        {error.code === 'ARXIV_NOT_CONFIGURED' && <Link to="/papers">{t('手动上传 PDF')}</Link>}
        {error.requestId && <small>{t('请求编号：')}<span className="identifier">{error.requestId}</span></small>}
      </div>,
    });
  }

  function notifyStatusFailure(error: ApiError) {
    const signature = error.code + ':' + error.message;
    if (statusFailure.current !== signature) notifyFailure(error, 'status');
    statusFailure.current = signature;
  }

  useEffect(() => () => {
    notification.destroy();
  }, [notification]);

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
    function shouldPoll() {
      return Object.values(known.current).some(pending) || Boolean(snapshot?.page.items.some((paper) =>
        paper.import_id && !Object.values(known.current).some((item) => item.id === paper.import_id) &&
        (paper.import_status === 'queued' || paper.import_status === 'running' ||
          (paper.import_status === 'succeeded' && (paper.paper_status === 'uploaded' || paper.paper_status === 'processing')))));
    }
    async function load() {
      try {
        const ids = [...new Set([...visibleImportIds.split(',').filter(Boolean), ...Object.values(known.current).filter((item) => pending(item) || visibleIdentities.split(',').includes(item.external_id)).map((item) => item.id)])];
        if (!ids.length) return;
        const results = await Promise.allSettled(ids.map((id) => api.paperImport(id, controller.signal)));
        if (controller.signal.aborted) return;
        let failed = false;
        results.forEach((result, index) => {
          if (result.status === 'fulfilled') remember([result.value]);
          else if (!isCanceled(result.reason)) {
            const error = asApiError(result.reason);
            if (error.status === 404) forgetImport(ids[index]);
            else { failed = true; notifyStatusFailure(error); rateLimit(error); }
          }
        });
        if (!failed) { statusFailure.current = ''; notification.destroy('paper-search-status'); }
        if (shouldPoll()) timer = window.setTimeout(() => void load(), 2000);
      } catch (error) {
        if (!isCanceled(error) && !controller.signal.aborted) {
          notifyStatusFailure(asApiError(error));
          if (shouldPoll()) timer = window.setTimeout(() => void load(), 2000);
        }
      }
    }
    void load();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [refresh, visibleImportIds, visibleIdentities]);

  useEffect(() => {
    const refreshStatus = () => setRefresh((value) => value + 1);
    window.addEventListener('focus', refreshStatus);
    return () => window.removeEventListener('focus', refreshStatus);
  }, []);

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
    notification.destroy('paper-search-search');
    try {
      const { sort_by, sort_order } = sortOptions[ordering];
      const page = await api.searchPapers({ q: term.trim(), limit, offset, sort_by, sort_order }, controller.signal);
      if (current === sequence.current && !controller.signal.aborted) {
        setSearching(false);
        const next = { ...known.current };
        page.items.forEach((paper) => {
          if (!paper.import_id || next[paper.external_id]?.id !== paper.import_id) delete next[paper.external_id];
        });
        known.current = next;
        setRecords(next);
        setSnapshot({ page, query: term.trim(), sort: ordering, reveal });
        setRefresh((value) => value + 1);
      }
    } catch (error) {
      if (current === sequence.current && !isCanceled(error) && !controller.signal.aborted) {
        const failure = asApiError(error);
        clearSearch();
        notifyFailure(failure, 'search');
        if (failure.code === 'ARXIV_TIMEOUT') setSearchRetryUntil(Date.now() + 5000);
        rateLimit(failure);
      }
    } finally {
      if (current === sequence.current && !controller.signal.aborted) setSearching(false);
    }
  }

  function clearSearch() {
    sequence.current += 1;
    searchRequest.current?.abort();
    searchRequest.current = null;
    setDraft(''); setQuery(''); setSnapshot(null);
    setSearching(false); setSort('relevance'); setPageSize(10);
    notification.destroy('paper-search-search');
  }

  useEffect(() => { if (active) setRefresh((value) => value + 1); }, [active]);

  function submit(event: FormEvent) {
    event.preventDefault();
    void search(draft);
  }

  async function importPaper(identity: string, retry?: PaperImport, importId?: string) {
    if (actions.current.has(identity) || Date.now() < cooldownUntil) return;
    const controller = new AbortController();
    actions.current.set(identity, controller);
    setBusy([...actions.current.keys()]);
    try {
      if (!retry && importId) retry = await api.paperImport(importId, controller.signal);
      if (retry && retry.status !== 'failed') { remember([retry]); setRefresh((value) => value + 1); return; }
      if (retry && !retryAttempts.current.has(retry.id)) retryAttempts.current.set(retry.id, retry.attempt);
      const item = retry
        ? await api.retryImport(retry.id, retryAttempts.current.get(retry.id)!, controller.signal)
        : await api.importPaper(identity, controller.signal);
      if (controller.signal.aborted) return;
      if (retry) retryAttempts.current.delete(retry.id);
      remember([item], true);
      setRefresh((value) => value + 1);
    } catch (error) {
      if (!isCanceled(error) && !controller.signal.aborted) {
        const failure = asApiError(error);
        notifyFailure(failure, 'import', identity);
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
      {item.status === 'failed' && <Button size="small" disabled={seconds > 0} loading={busy.includes(item.external_id)} onClick={() => void importPaper(item.external_id, item)}>{t("重新下载")}</Button>}
      {item.paper_id && <Link to="/papers">{t("查看论文库")}</Link>}
      {item.paper_id && item.paper_status === 'ready' && <Link to={`/tasks/new?paper_id=${encodeURIComponent(item.paper_id)}`}>{t("用于研究")}<ArrowRightOutlined /></Link>}
    </div>;
  }

  return <>
    {notificationHolder}
    <PageHeader title={t("搜索论文")} description={t("从 arXiv 发现文献，将指定版本保存为可追溯的研究资料。")} action={<Link to="/papers"><Button>{t("返回论文库")}</Button></Link>} />
    <div className="search-layout"><section className="content-panel search-panel">
      <form className="arxiv-search-form" onSubmit={submit}>
        <label htmlFor="arxiv-keywords">{t("arXiv 关键词")}</label>
        <div className="search-input-row"><Input id="arxiv-keywords" value={draft} maxLength={200} placeholder={t("例如：attention transformer")} onChange={(event) => setDraft(event.target.value)} /><Button type="primary" htmlType="submit" aria-label={t("搜索")} icon={<SearchOutlined />} loading={searching} disabled={!draft.trim() || searchSeconds > 0}>{searchSeconds > 0 ? t("{0} 秒后可重试搜索", [searchSeconds]) : t("搜索")}</Button><Button htmlType="button" onClick={clearSearch} disabled={!draft && !query && !snapshot && !searching}>{t("清除搜索")}</Button></div>
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
      {searching && <div className="search-loading" role="status"><Spin size="small" />{t("正在查询 arXiv…")}</div>}
      {snapshot && result && <div aria-busy={searching} data-stale={searching}>
        <div className="search-result-heading"><h2 id="search-results-heading" ref={resultsHeading} tabIndex={-1}>{t("检索结果")}</h2><span role="status">{t("共 {0} 篇 · 第 {1} 页", [result.total, Math.floor(result.offset / resultPageSize) + 1])}</span></div>
        {result.items.length === 0 && <Empty description={t("没有找到匹配论文")} />}
        <div className="search-results" key={snapshot.query + ':' + result.offset + ':' + result.limit + ':' + snapshot.sort}>{result.items.map((paper) => {
          const item = records[paper.external_id];
          return <article key={paper.external_id} className="search-paper">
            <div className="source-identity"><span>arXiv · {paper.external_id}</span><span>{t('发布于 {0}', [new Date(paper.published_at).toLocaleDateString(getLocale())])}</span>{snapshot.sort.startsWith('updated') && <span>{t('更新于 {0}', [new Date(paper.source_updated_at).toLocaleDateString(getLocale())])}</span>}</div>
            <h3><MathText inline>{paper.title}</MathText></h3><p className="paper-authors">{paper.authors.join(' · ')}</p>
            <PaperAbstract text={paper.abstract} />
            <div className="source-categories">{paper.categories.map((category) => <Tag key={category}>{category}</Tag>)}</div>
            <div className="search-paper-footer"><div className="source-links">{arxivUrl(paper.external_id, 'abs') && <a href={arxivUrl(paper.external_id, 'abs')} target="_blank" rel="noopener noreferrer">{t("arXiv 原文")}</a>}{arxivUrl(paper.external_id, 'pdf') && <a href={arxivUrl(paper.external_id, 'pdf')} target="_blank" rel="noopener noreferrer">{t("来源 PDF")}</a>}</div>
              {item ? importActions(item) : paper.import_status ? <div className="import-actions"><Tag>{importLabel(paper.import_status, paper.paper_status)}</Tag>{paper.import_status === 'failed' && <Button size="small" disabled={seconds > 0} loading={busy.includes(paper.external_id)} onClick={() => void importPaper(paper.external_id, undefined, paper.import_id ?? undefined)}>{t('重新下载')}</Button>}{paper.paper_id && <Link to="/papers">{t('查看论文库')}</Link>}</div> : <Button disabled={seconds > 0} loading={busy.includes(paper.external_id)} onClick={() => void importPaper(paper.external_id)}>{seconds > 0 ? t("{0} 秒后可重试", [seconds]) : t("导入 PDF")}</Button>}
            </div>
          </article>;
        })}</div>
        {result.total > 0 && <nav className="search-pagination" aria-label={t('搜索结果分页')}>
          <p>{t('每页 {0} 篇 · 可浏览 {1} 页', [resultPageSize, Math.ceil(Math.min(result.total, maximumResults) / resultPageSize)])}{result.total > maximumResults && <span>{t('仅展示前 {0} 页，可缩小关键词范围以查找更多论文。', [maximumPages])}</span>}</p>
          <Pagination current={Math.floor(result.offset / resultPageSize) + 1} pageSize={resultPageSize} total={Math.min(result.total, maximumResults)} disabled={searching || searchSeconds > 0} showSizeChanger={false} showQuickJumper showLessItems onChange={(page) => void search(snapshot.query, (page - 1) * resultPageSize, snapshot.sort, true, resultPageSize)} />
        </nav>}
      </div>}
    </section>
</div>
  </>;
}
