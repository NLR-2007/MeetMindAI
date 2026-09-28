"use client";

import Image from "next/image";
import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Paperclip, Plus, Send, Sparkles } from "lucide-react";

import { cn } from "@/lib/utils";
import { Textarea } from "@/components/ui/textarea";

interface AiInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  disabled?: boolean;
  busy?: boolean;
  compact?: boolean;
  placeholder?: string;
}

function useAutoResizeTextarea(minHeight: number, maxHeight: number) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const adjustHeight = useCallback(
    (reset = false) => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      textarea.style.height = `${minHeight}px`;
      if (!reset) {
        textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
      }
    },
    [maxHeight, minHeight],
  );

  useEffect(() => {
    const handleResize = () => adjustHeight();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [adjustHeight]);

  return { textareaRef, adjustHeight };
}

export function AiInput({
  value,
  onChange,
  onSubmit,
  disabled = false,
  busy = false,
  compact = false,
  placeholder = "Ask MeetMind about this meeting…",
}: AiInputProps) {
  const { textareaRef, adjustHeight } = useAutoResizeTextarea(
    compact ? 42 : 50,
    compact ? 112 : 164,
  );
  const [contextMode, setContextMode] = useState(true);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function selectImage(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setImagePreview((current) => {
      if (current) URL.revokeObjectURL(current);
      return URL.createObjectURL(file);
    });
  }

  function clearImage() {
    if (imagePreview) URL.revokeObjectURL(imagePreview);
    if (fileInputRef.current) fileInputRef.current.value = "";
    setImagePreview(null);
  }

  function submit() {
    if (!value.trim() || disabled || busy) return;
    onSubmit(value.trim());
    adjustHeight(true);
    clearImage();
  }

  useEffect(
    () => () => {
      if (imagePreview) URL.revokeObjectURL(imagePreview);
    },
    [imagePreview],
  );

  return (
    <div className={cn("w-full", compact ? "p-2.5" : "p-3 sm:p-4")}>
      <div className="relative mx-auto w-full rounded-[22px] border border-[var(--border)] bg-white p-1 shadow-[0_16px_45px_-28px_rgb(36_43_76/.45)] transition focus-within:border-[var(--accent)]/35 focus-within:shadow-[0_18px_48px_-26px_rgb(99_91_255/.35)]">
        <div className="relative overflow-visible rounded-[18px] bg-[var(--background)]">
          <AnimatePresence>
            {imagePreview && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: compact ? 76 : 100 }}
                exit={{ opacity: 0, height: 0 }}
                className="overflow-hidden px-3 pt-3"
              >
                <div className="relative h-full w-24 overflow-hidden rounded-xl border border-[var(--border)] bg-white">
                  <Image src={imagePreview} alt="Attachment preview" fill unoptimized className="object-cover" />
                  <button type="button" onClick={clearImage} aria-label="Remove attachment" className="absolute right-1 top-1 grid h-6 w-6 place-items-center rounded-full bg-white/90 text-[var(--foreground)] shadow-sm">
                    <Plus className="h-3.5 w-3.5 rotate-45" />
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <div className="relative overflow-y-auto" style={{ maxHeight: compact ? 112 : 164 }}>
            <Textarea
              ref={textareaRef}
              value={value}
              rows={1}
              disabled={disabled || busy}
              aria-label="Message MeetMind"
              placeholder={placeholder}
              className={cn(
                "min-h-0 w-full resize-none rounded-[18px] rounded-b-none border-0 bg-transparent px-4 py-3.5 leading-6 shadow-none focus-visible:ring-0",
                compact ? "text-xs" : "text-sm",
              )}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  submit();
                }
              }}
              onChange={(event) => {
                onChange(event.target.value);
                adjustHeight();
              }}
            />
          </div>

          <div className={cn("flex items-center justify-between px-2.5 pb-2.5", compact ? "min-h-10" : "min-h-12")}>
            <div className="flex items-center gap-2">
              <label className={cn("grid cursor-pointer place-items-center rounded-full border transition", compact ? "h-8 w-8" : "h-9 w-9", imagePreview ? "border-[var(--coral)] bg-[var(--coral-soft)] text-[var(--coral)]" : "border-transparent bg-white text-[var(--muted)] hover:text-[var(--foreground)]")}>
                <input ref={fileInputRef} type="file" accept="image/*" onChange={selectImage} className="hidden" disabled={disabled || busy} />
                <Paperclip className="h-4 w-4" />
                <span className="sr-only">Attach an image</span>
              </label>
              <button
                type="button"
                onClick={() => setContextMode((active) => !active)}
                aria-pressed={contextMode}
                className={cn(
                  "flex h-8 items-center gap-1.5 rounded-full border px-2.5 text-[11px] font-semibold transition",
                  contextMode
                    ? "border-[var(--accent)]/25 bg-[var(--accent-soft)] text-[var(--accent)]"
                    : "border-transparent bg-white text-[var(--muted)] hover:text-[var(--foreground)]",
                )}
              >
                <motion.span animate={{ rotate: contextMode ? 180 : 0 }} transition={{ type: "spring", stiffness: 260, damping: 24 }}>
                  <Sparkles className="h-3.5 w-3.5" />
                </motion.span>
                {!compact && <span>Meeting context</span>}
              </button>
            </div>

            <motion.button
              whileTap={{ scale: 0.9 }}
              type="button"
              onClick={submit}
              disabled={disabled || busy || !value.trim()}
              aria-label="Send message"
              className={cn(
                "grid place-items-center rounded-full transition",
                compact ? "h-8 w-8" : "h-9 w-9",
                value.trim() && !disabled && !busy
                  ? "bg-[var(--accent)] text-white shadow-[0_8px_20px_-8px_rgb(99_91_255/.8)]"
                  : "bg-white text-[var(--muted)]",
              )}
            >
              <Send className="h-4 w-4" />
            </motion.button>
          </div>
        </div>
      </div>
      {imagePreview && (
        <p className="mt-1.5 px-2 text-[10px] text-[var(--muted)]">Image preview only; meeting answers currently use transcript text.</p>
      )}
    </div>
  );
}
