import { t } from '../../../i18n/store';

export const maxFileBytes = 50 * 1024 * 1024;

export async function validatePdf(file: File): Promise<string | null> {
  if (!/\.pdf$/i.test(file.name) || !file.name.slice(0, -4).trim()) return t("请选择名称有效的 PDF 文件。");
  if (file.name.length > 255 || /[/\\\u0000-\u001f\u007f-\u009f]/.test(file.name)) return t("文件名过长，或包含路径、控制字符。");
  if (file.size > maxFileBytes) return t("文件超过 50 MB，请选择更小的 PDF。");
  if (file.size === 0) return t("文件为空，请选择有效的 PDF。");
  const header = new TextDecoder().decode(await file.slice(0, 5).arrayBuffer());
  return header === '%PDF-' ? null : t("文件缺少 PDF 文件头，请确认文件格式。");
}
