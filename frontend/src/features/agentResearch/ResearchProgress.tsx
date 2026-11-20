import { Spin } from 'antd';
import { t, useLocale, getLocale } from '../../i18n';

export default function ResearchProgress({ queued, disconnected, checkedAt }: { queued: boolean; disconnected: boolean; checkedAt?: number }) {
  useLocale();
  return <section className="content-panel task-progress" aria-label={t('研究进度')}>
    <div className="task-progress-heading">{!disconnected && <Spin />}<h2>{t(disconnected ? '状态读取已中断' : queued ? '任务正在等待处理' : '研究正在进行')}</h2></div>
    <p role="status">{t(disconnected ? '暂时无法确认任务最新状态，请刷新重试。' : queued ? '任务已提交，正在等待开始。你可以离开页面，稍后回来查看。' : '系统正在处理研究任务，生成结果可能需要几分钟。你可以离开页面，稍后回来查看。')}</p>
    <div className={'task-progress-track' + (disconnected ? ' is-disconnected' : '')} role="progressbar" aria-label={t(disconnected ? '等待恢复连接' : queued ? '等待处理' : '研究处理中')}><span /></div>
    <div className="task-progress-note"><span>{t('完成后会自动显示结果，无需手动刷新。')}</span>{checkedAt && <span>{t('最近状态确认：{0}', [new Date(checkedAt).toLocaleTimeString(getLocale(), { hour12: false })])}</span>}</div>
  </section>;
}
