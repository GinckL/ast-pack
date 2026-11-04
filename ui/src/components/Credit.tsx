import { Globe, Linkedin, Send } from "lucide-react";

export const AUTHOR = {
  name: "Azimxon Vaxobov",
  nick: "Ginckl",
  site: "https://azimxonvaxobov.netlify.app",
  linkedin: "https://www.linkedin.com/in/azimxon-vaxobov/",
  telegram: "https://t.me/A_Vakhobov",
  github: "https://github.com/ginckl/ast-pack",
};

/** Inline author credit ("by Azimxon Vaxobov · Ginckl"). */
export function CreditInline() {
  return (
    <a
      href={AUTHOR.site}
      target="_blank"
      rel="noreferrer"
      className="pointer-events-auto text-faint transition-colors hover:text-accent"
      title={`${AUTHOR.name} (${AUTHOR.nick})`}
    >
      by <span className="font-medium text-mute">{AUTHOR.name}</span> · {AUTHOR.nick}
    </a>
  );
}

/** Footer with author links, shown in the shortcuts dialog. */
export function CreditCard() {
  const link = "flex items-center gap-1.5 rounded-lg px-2 py-1 text-mute transition-colors hover:bg-elev hover:text-fg";
  return (
    <div className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line/70 pt-4 text-[12px]">
      <span className="text-faint">
        ast-pack is created by <span className="font-semibold text-fg">{AUTHOR.name}</span> <span className="text-faint">({AUTHOR.nick})</span>
      </span>
      <span className="ml-auto flex flex-wrap gap-1">
        <a className={link} href={AUTHOR.site} target="_blank" rel="noreferrer">
          <Globe size={13} /> Website
        </a>
        <a className={link} href={AUTHOR.linkedin} target="_blank" rel="noreferrer">
          <Linkedin size={13} /> LinkedIn
        </a>
        <a className={link} href={AUTHOR.telegram} target="_blank" rel="noreferrer">
          <Send size={13} /> Telegram
        </a>
      </span>
    </div>
  );
}
