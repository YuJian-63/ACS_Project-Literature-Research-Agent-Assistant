import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Alert, App, Button, Input } from 'antd';
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { asApiError, isCanceled } from '../../../api/client';
import AuthLayout from '../components/AuthLayout';
import { t, useLocale } from '../../../i18n';
import { authPost } from '../../../api/auth';
import { useAuth } from '../AuthProvider';
import { forgetEmailToken, readEmailToken, safeReturnPath } from '../lib/links';

type Values = { username: string; email: string; password: string; confirm: string; current_password: string };
const emptyValues: Values = { username: '', email: '', password: '', confirm: '', current_password: '' };
const titles: Record<string, string> = {
  '/login': '登录', '/register': '创建账号', '/verify-email': '验证邮箱', '/forgot-password': '找回密码',
  '/reset-password': '重置密码', '/account/password': '修改密码',
};
const acceptedMessage = '如果该邮箱符合条件，我们将发送邮件。请查看收件箱和垃圾邮件；受理不代表邮件已送达。';

function validPassword(value: string) {
  const length = Array.from(value).length;
  return length >= 6 && length <= 128;
}

export default function AuthPage() {
  useLocale();
  const auth = useAuth();
  const { notification } = App.useApp();
  const { pathname, state: navigationState } = useLocation();
  const [parameters] = useSearchParams();
  const navigate = useNavigate();
  const [token, setToken] = useState(() => readEmailToken(pathname));
  const [values, setValues] = useState<Values>(emptyValues);
  const [attempted, setAttempted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);
  const [pendingVerification, setPendingVerification] = useState(false);
  const [resendEmail, setResendEmail] = useState('');
  const [resendStatus, setResendStatus] = useState('');
  const [resendError, setResendError] = useState('');
  const [resending, setResending] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const resendController = useRef<AbortController | null>(null);
  const inFlight = useRef(false);
  const login = pathname === '/login';
  const register = pathname === '/register';
  const verify = pathname === '/verify-email';
  const forgot = pathname === '/forgot-password';
  const reset = pathname === '/reset-password';
  const change = pathname === '/account/password';
  const needsToken = verify || reset;
  const next = safeReturnPath(parameters.get('next'));
  const title = titles[pathname];

  useEffect(() => {
    forgetEmailToken();
    return () => { controller.current?.abort(); resendController.current?.abort(); };
  }, []);

  if (login && auth.user && auth.status === 'ready') return <Navigate to={next} replace />;

  const validation: Partial<Record<keyof Values, string>> = {};
  if ((register || login) && !/^[A-Za-z0-9_]{3,32}$/.test(values.username)) validation.username = '用户名须为 3–32 个 ASCII 字母、数字或下划线。';
  if ((register || forgot) && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email.trim())) validation.email = '请输入有效的邮箱地址。';
  if (!forgot && !validPassword(values.password)) validation.password = '密码须为 6–128 个字符，空格会保留。';
  if ((register || reset || change) && values.confirm !== values.password) validation.confirm = '两次输入的密码不一致。';
  if (change && !validPassword(values.current_password)) validation.current_password = '密码须为 6–128 个字符，空格会保留。';

  async function submit(event: FormEvent) {
    event.preventDefault();
    setAttempted(true);
    setError('');
    if (inFlight.current) return;
    if (Object.keys(validation).length || (needsToken && !token)) {
      if (change) notification.error({ title: t('密码修改失败'), description: t(Object.values(validation)[0] || '请求未完成，请稍后重试。'), duration: 3 });
      return;
    }
    inFlight.current = true;
    setBusy(true);
    const pending = new AbortController();
    controller.current = pending;
    try {
      if (login) {
        await auth.login(values.username, values.password, pending.signal);
        navigate(next, { replace: true });
        return;
      }
      if (register) await authPost('register', { username: values.username, email: values.email.trim(), password: values.password }, pending.signal);
      if (verify) await authPost('verify-email', { token, password: values.password }, pending.signal);
      if (forgot) await authPost('forgot-password', { email: values.email.trim() }, pending.signal);
      if (reset) await authPost('reset-password', { token, password: values.password }, pending.signal);
      if (change) await authPost('change-password', { current_password: values.current_password, password: values.password }, pending.signal, true);
      if (pending.signal.aborted) return;
      setResendEmail(values.email.trim());
      setValues(emptyValues);
      setAttempted(false);
      setDone(true);
      setToken('');
      if (reset) auth.endSession();
      if (change) {
        notification.success({ title: t('密码修改成功'), description: t('新密码已生效。'), duration: 3 });
        navigate('/papers', { replace: true });
      }
    } catch (failure) {
      if (pending.signal.aborted || isCanceled(failure)) return;
      const problem = asApiError(failure);
      if (change) {
        const reason = problem.code === 'CURRENT_PASSWORD_INCORRECT' || problem.code === 'INVALID_CREDENTIALS' ? '当前密码不正确，请重新输入。'
          : problem.status === 429 ? '请求过于频繁，请稍后再试。'
          : problem.status === null || (problem.status && problem.status >= 500) ? '服务暂时不可用，请稍后重试。'
          : problem.code === 'CSRF_REJECTED' || problem.code === 'ORIGIN_REJECTED' ? '请求验证失败，请刷新页面后重试。'
          : '密码未能更新，请检查输入后重试。';
        notification.error({ title: t('密码修改失败'), description: t(reason), duration: 3 });
        return;
      }
      if (problem.status === 429) setError('请求过于频繁，请稍后再试。');
      else if (problem.status === null || (problem.status && problem.status >= 500)) setError('服务暂时不可用，请稍后重试。');
      else if (login && /VERIF/i.test(problem.code)) { setPendingVerification(true); setError('请先验证邮箱，再登录。'); }
      else if (login) setError('用户名或密码不正确。');
      else if (register) setError('该注册信息不可用，请重新填写或重新发送验证邮件。');
      else if (verify) setError('链接无效、已过期或密码不正确。请重试或重新申请邮件。');
      else if (reset) setError('链接无效或已过期，请重新申请邮件。');
      else setError('请求未完成，请稍后重试。');
    } finally {
      inFlight.current = false;
      if (!pending.signal.aborted) setBusy(false);
    }
  }

  async function resend(event: FormEvent) {
    event.preventDefault();
    if (resending) return;
    setResendStatus('');
    setResendError('');
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(resendEmail.trim())) { setResendError('请输入有效的邮箱地址。'); return; }
    setResending(true);
    const pending = new AbortController();
    resendController.current = pending;
    try {
      await authPost('resend-verification', { email: resendEmail.trim() }, pending.signal);
      if (!pending.signal.aborted) setResendStatus(acceptedMessage);
    } catch (failure) {
      if (!pending.signal.aborted && !isCanceled(failure)) setResendError(asApiError(failure).status === 429 ? '请求过于频繁，请稍后再试。' : '请求未完成，请稍后重试。');
    } finally { if (!pending.signal.aborted) setResending(false); }
  }

  function field(name: keyof Values, label: string, password = false, autoComplete = '') {
    const invalid = attempted ? validation[name] : undefined;
    const properties = {
      id: 'auth-' + name, name, value: values[name], autoComplete,
      'aria-invalid': Boolean(invalid), 'aria-describedby': invalid ? 'auth-' + name + '-error' : undefined,
      onChange: (event: React.ChangeEvent<HTMLInputElement>) => setValues((previous) => ({ ...previous, [name]: event.target.value })),
      disabled: busy,
    };
    return <div className="auth-field"><label htmlFor={properties.id}>{t(label)}</label>{password
      ? <Input.Password {...properties} /> : <Input {...properties} type={name === 'email' ? 'email' : 'text'} autoCapitalize="none" spellCheck={false} />}
      {invalid ? <p className="auth-field-error" id={'auth-' + name + '-error'} role="alert">{t(invalid)}</p> : null}</div>;
  }

  const content = <>
    <div className="auth-heading"><p className="auth-eyebrow">{t('个人研究空间')}</p><h1>{t(done && register ? '查看验证邮件' : title)}</h1><p>{t(register
      ? '以用户名登录，用邮箱验证和找回密码。论文与研究结果仅对你可见。'
      : verify ? '请输入注册时设置的密码以确认邮箱。打开链接不会自动激活账号。'
      : forgot ? '输入注册邮箱，我们会受理密码重置申请。'
      : reset ? '设置新密码后，所有设备都需要重新登录。'
      : change ? '使用当前密码确认身份。修改后，所有设备都需要重新登录。'
      : '登录后继续整理文献，沿着证据开展研究。')}</p></div>
    {done ? <div role="status" className="auth-status">{t(register || forgot ? acceptedMessage : verify ? '邮箱已验证，请登录。' : '密码已更新，请重新登录。')}</div> : null}
    {login && navigationState?.passwordChanged ? <div role="status" className="auth-status">{t('密码已更新，请重新登录。')}</div> : null}
    {error ? <Alert type="error" title={t(error)} showIcon /> : null}
    {needsToken && !token && !done ? <Alert type="warning" title={t('链接缺少令牌，请从最新邮件重新打开，或重新申请邮件。')} showIcon /> : null}
    {!done ? <form onSubmit={submit} noValidate className="auth-form">
      {login || register ? field('username', '用户名', false, 'username') : null}
      {register || forgot ? field('email', '邮箱', false, 'email') : null}
      {change ? field('current_password', '当前密码', true, 'current-password') : null}
      {!forgot ? field('password', verify ? '原密码' : reset || change ? '新密码' : '密码', true, register || reset || change ? 'new-password' : 'current-password') : null}
      {register || reset || change ? field('confirm', '确认密码', true, 'new-password') : null}
      {!forgot && !login ? <p className="auth-hint">{t('密码为 6–128 个字符，可使用数字、字母、下划线等符号，无需混合字符种类，中文和空格也会保留。')}</p> : null}
      <Button aria-label={t(forgot ? '发送重置链接' : title)} type="primary" htmlType="submit" loading={busy} disabled={(needsToken && !token) || (login && auth.status === 'loading')} block>{t(forgot ? '发送重置链接' : title)}</Button>
    </form> : null}
    {(done && register) || verify || pendingVerification ? <form className="auth-resend" onSubmit={resend} noValidate>
      <p>{t('验证邮件 24 小时内有效。请使用邮件中的链接和原密码完成验证，然后返回登录。')}</p>
      <label htmlFor="resend-email">{t('验证邮箱地址')}</label><Input id="resend-email" type="email" autoComplete="email" value={resendEmail} onChange={(event) => setResendEmail(event.target.value)} disabled={resending} />
      {resendError ? <p role="alert" className="auth-field-error">{t(resendError)}</p> : null}
      <Button aria-label={t('重新发送验证邮件')} htmlType="submit" loading={resending}>{t('重新发送验证邮件')}</Button>
      {resendStatus ? <p role="status">{t(resendStatus)}</p> : null}
    </form> : null}
    <nav className="auth-links" aria-label={t('账号导航')}>
      {login ? <><Link to={'/register?next=' + encodeURIComponent(next)}>{t('创建账号')}</Link><Link to="/forgot-password">{t('忘记密码？')}</Link></> : <Link to={'/login?next=' + encodeURIComponent(next)}>{t('返回登录')}</Link>}
      {reset ? <Link to="/forgot-password">{t('重新申请重置邮件')}</Link> : null}
      {change ? <Link to="/papers">{t('返回论文库')}</Link> : null}
    </nav>
  </>;
  if (change) return <section className="auth-account">{content}</section>;
  return <AuthLayout>{content}</AuthLayout>;
}
