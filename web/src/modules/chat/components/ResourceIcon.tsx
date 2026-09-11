import {
  FileCode2,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileType2,
  Presentation,
  type LucideIcon,
} from "lucide-react";

/** A compact, recognizable file treatment for conversation-native resources. */
export function FileTypeIcon({
  className,
  name,
}: {
  className?: string;
  name: string;
}) {
  const { Icon, tone, label } = resourcePresentation(name);
  return (
    <span aria-label={label} className={`resource-icon resource-icon--${tone}${className ? ` ${className}` : ""}`} role="img">
      <Icon aria-hidden="true" size={16} />
      <span>{label}</span>
    </span>
  );
}

function resourcePresentation(name: string): { Icon: LucideIcon; tone: string; label: string } {
  const normalized = name.trim().toLowerCase();
  if (normalized.includes("confluence")) return { Icon: FileText, tone: "confluence", label: "Confluence" };
  if (/\.(csv|xlsx|xls|tsv)$/.test(normalized)) return { Icon: FileSpreadsheet, tone: "sheet", label: "Sheet" };
  if (/\.(ppt|pptx|key)$/.test(normalized)) return { Icon: Presentation, tone: "slides", label: "Slides" };
  if (/\.(png|jpe?g|gif|webp|svg|avif)$/.test(normalized)) return { Icon: FileImage, tone: "image", label: "Image" };
  if (/\.(md|markdown|txt|json|ya?ml|xml|html?)$/.test(normalized)) return { Icon: FileCode2, tone: "text", label: "Text" };
  if (/\.pdf$/.test(normalized)) return { Icon: FileType2, tone: "pdf", label: "PDF" };
  if (/\.(doc|docx|odt)$/.test(normalized)) return { Icon: FileText, tone: "document", label: "Document" };
  return { Icon: FileText, tone: "document", label: "File" };
}
